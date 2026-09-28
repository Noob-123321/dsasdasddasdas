"""Tests for `app.detect.chat` -- chat liveness detectors on expanded series.

Pure unit tests: synthetic expanded per-minute timelines built with
``expand_series``; nothing touches a database, the network or ``app.config``.
"""
import datetime as dt
import unittest

from app.detect.chat import (
    WEIGHTS,
    _message_rate,
    chat_findings,
    chat_message_input_state,
    starvation_floor,
)
from app.detect.series import expand_series
from app.detect.types import scale

START = dt.datetime(2026, 1, 1, 12, 0, 0)


def series_of(segments, start=START):
    """Expanded per-minute timeline from ``(viewers, chatters, minutes)`` segments."""
    samples = []
    cursor = start
    for viewers, chatters, minutes in segments:
        samples.append({
            "observed_at": cursor,
            "last_seen_at": cursor + dt.timedelta(minutes=minutes - 1),
            "viewers": viewers,
            "chatters": chatters,
            "is_live": True,
        })
        cursor += dt.timedelta(minutes=minutes)
    return expand_series(samples)


def moving(viewers, chatters, minutes, *, span=7):
    """Timeline where the chatter count changes every single minute."""
    return series_of([(viewers, chatters + index % span, 1) for index in range(minutes)])


def flat(viewers, chatters, minutes=5):
    """Timeline with one constant ``(viewers, chatters)`` pair."""
    return series_of([(viewers, chatters, minutes)])


def findings_for(points, **kwargs):
    return chat_findings(points, **kwargs)


def pick(findings, code):
    return next((finding for finding in findings if finding.code == code), None)


def codes_of(findings):
    return [finding.code for finding in findings]


def messages(author, count, *, author_start=START):
    return [
        {"author_login": author, "ts": author_start + dt.timedelta(seconds=index)}
        for index in range(count)
    ]


def _only(findings):
    """The single finding of a one-shot detector call (or a loud failure)."""
    assert len(findings) == 1, [item.code for item in findings]
    return findings[0]


class StarvationFloorTest(unittest.TestCase):
    """The floor curve itself: monotone, bounded, and off below 50 viewers."""

    def test_below_meaningful_viewers_is_none(self):
        for viewers in (None, 0, 1, 49):
            with self.subTest(viewers=viewers):
                self.assertIsNone(starvation_floor(viewers))

    def test_reference_rows_sit_on_the_right_side_of_the_floor(self):
        # AGENTS.md: 30/5 ok, 300/30-60 ok, 500/1 suspicious.
        self.assertIsNone(starvation_floor(30))                       # 30/5 -> ratio meaningless
        self.assertLess(starvation_floor(300), 30 / 300)              # 300/30 stays ok
        self.assertLess(starvation_floor(300), 60 / 300)              # 300/60 stays ok
        self.assertLess(starvation_floor(300), 0.1)
        self.assertGreater(starvation_floor(500), 1 / 500)            # 500/1 fires
        self.assertGreater(starvation_floor(500), 0.01)
        self.assertGreater(starvation_floor(1000), 2 / 1000)          # 1000/0-2 flagged

    def test_monotone_and_bounded(self):
        viewers = [50, 60, 100, 250, 300, 500, 1000, 5000]
        floors = [starvation_floor(value) for value in viewers]
        self.assertEqual(floors, sorted(floors))
        self.assertEqual(len(set(floors)), len(floors))
        for floor in floors:
            self.assertGreater(floor, 0.0)
            self.assertLess(floor, 0.09)

    def test_genre_needs_adjustments_to_change_anything(self):
        base = starvation_floor(500)
        self.assertEqual(starvation_floor(500, genre="Just Chatting"), base)
        self.assertEqual(starvation_floor(500, genre="Just Chatting", adjustments={}), base)
        self.assertEqual(starvation_floor(500, genre="Just Chatting", adjustments={"Other": 2.0}), base)
        self.assertAlmostEqual(
            starvation_floor(500, genre="Just Chatting", adjustments={"Just Chatting": 0.5}),
            base / 2,
        )
        self.assertAlmostEqual(starvation_floor(500, adjustments={"default": 3.0}), base * 3)


class ReferenceRatioTableTest(unittest.TestCase):
    """Table-driven: the repo's own reference rows (AGENTS.md) through the detector."""

    ROWS = [
        # viewers, chatters, starvation_expected
        (30, 5, False),
        (300, 30, False),
        (300, 60, False),
        (500, 1, True),
        (1000, 2, True),
        (1000, 0, True),
    ]

    def test_reference_rows(self):
        scores = {}
        for viewers, chatters, expected in self.ROWS:
            with self.subTest(viewers=viewers, chatters=chatters):
                points = flat(viewers, chatters)
                findings = findings_for(points)
                starvation = pick(findings, "chat_starvation_ratio")

                if not expected:
                    self.assertIsNone(starvation, codes_of(findings))
                    self.assertEqual(codes_of(findings), [])
                    continue

                self.assertIsNotNone(starvation, codes_of(findings))
                ratio = chatters / viewers
                observed = starvation.observed
                self.assertEqual(set(observed), {"ratio_median", "floor", "viewers_median", "minutes"})
                self.assertAlmostEqual(observed["ratio_median"], ratio, places=9)
                self.assertEqual(observed["floor"], starvation_floor(viewers))
                self.assertEqual(observed["viewers_median"], viewers)
                self.assertEqual(observed["minutes"], 5)
                self.assertEqual(starvation.weight, WEIGHTS["chat_starvation_ratio"])
                self.assertGreater(starvation.score, 0.0)
                self.assertLessEqual(starvation.score, 1.0)
                self.assertAlmostEqual(
                    starvation.score,
                    scale(observed["floor"] - ratio, 0.0, observed["floor"]),
                )
                scores[(viewers, chatters)] = starvation.score

        # The score reports how far below the floor the channel is, not a binary flag.
        self.assertEqual(len(set(scores.values())), len(scores))


class SilentChatTest(unittest.TestCase):

    def test_flat_chatters_with_big_audience_fires(self):
        findings = findings_for(flat(500, 40, 15))
        silent = pick(findings, "silent_chat")
        self.assertIsNotNone(silent, codes_of(findings))
        self.assertEqual(silent.observed["chatters"], 40)
        self.assertEqual(silent.observed["still_minutes"], 14.0)
        self.assertEqual(silent.observed["viewers_median"], 500.0)
        self.assertEqual(silent.observed["start_ts"], START.isoformat())
        self.assertEqual(silent.observed["end_ts"], (START + dt.timedelta(minutes=14)).isoformat())
        self.assertEqual(silent.weight, WEIGHTS["silent_chat"])
        self.assertGreater(silent.score, 0.0)

    def test_moving_chatters_does_not_fire(self):
        findings = findings_for(moving(500, 60, 15))
        self.assertIsNone(pick(findings, "silent_chat"), codes_of(findings))
        self.assertEqual(codes_of(findings), [])

    def test_ten_minute_boundary(self):
        fired = pick(findings_for(flat(500, 40, 11)), "silent_chat")
        self.assertIsNotNone(fired)
        self.assertEqual(fired.observed["still_minutes"], 10.0)

        short = findings_for(flat(500, 40, 10))
        self.assertIsNone(pick(short, "silent_chat"), codes_of(short))

    def test_small_audience_is_ignored(self):
        findings = findings_for(flat(30, 5, 15))
        self.assertEqual(codes_of(findings), [])

    def test_longest_flat_run_wins(self):
        points = series_of([(600, 70, 6), (600, 71, 20), (600, 70, 6)])
        silent = pick(findings_for(points), "silent_chat")
        self.assertIsNotNone(silent)
        self.assertEqual(silent.observed["chatters"], 71)
        self.assertEqual(silent.observed["still_minutes"], 19.0)
        self.assertEqual(silent.observed["viewers_median"], 600.0)


class ChatCollapseTest(unittest.TestCase):

    def test_ratio_halves_while_viewers_rise(self):
        points = series_of([(500, 50, 12), (900, 9, 12)])
        collapse = pick(findings_for(points), "chat_collapse")
        self.assertIsNotNone(collapse)
        observed = collapse.observed
        self.assertEqual(
            set(observed),
            {"early_ratio", "late_ratio", "drop_ratio", "early_viewers", "late_viewers", "boundary_ts"},
        )
        self.assertAlmostEqual(observed["early_ratio"], 0.1, places=9)
        self.assertAlmostEqual(observed["late_ratio"], 0.01, places=9)
        self.assertAlmostEqual(observed["drop_ratio"], 0.9, places=9)
        self.assertEqual(observed["early_viewers"], 500.0)
        self.assertEqual(observed["late_viewers"], 900.0)
        self.assertEqual(observed["boundary_ts"], (START + dt.timedelta(minutes=12)).isoformat())
        self.assertEqual(collapse.weight, WEIGHTS["chat_collapse"])
        self.assertGreater(collapse.score, 0.0)

    def test_ratio_halves_but_viewers_fall_does_not_fire(self):
        points = series_of([(900, 90, 12), (500, 5, 12)])
        self.assertIsNone(pick(findings_for(points), "chat_collapse"))

    def test_viewers_rise_without_ratio_drop_does_not_fire(self):
        points = series_of([(500, 50, 12), (900, 90, 12)])
        self.assertIsNone(pick(findings_for(points), "chat_collapse"))

    def test_stream_points_restrict_the_window(self):
        whole = series_of([(500, 50, 12), (900, 9, 12)])
        self.assertIsNotNone(pick(findings_for(whole), "chat_collapse"))

        healthy_tail = series_of([(500, 50, 12)])
        narrowed = findings_for(whole, stream_points=healthy_tail)
        self.assertIsNone(pick(narrowed, "chat_collapse"), codes_of(narrowed))


class ChatterDominanceTest(unittest.TestCase):

    def test_no_events_means_unavailable_and_no_finding(self):
        for events in (None, [], [{"ts": START}]):
            with self.subTest(events=events):
                state, detail = chat_message_input_state(events)
                self.assertEqual(state, "unavailable")
                self.assertTrue(detail)
                findings = findings_for(flat(500, 80, 5), chat_events=events)
                self.assertIsNone(pick(findings, "single_chatter_dominance"), codes_of(findings))
                self.assertEqual(codes_of(findings), [])

    def test_too_few_messages_is_insufficient(self):
        events = messages("bot_1", 9)
        state, detail = chat_message_input_state(events)
        self.assertEqual(state, "insufficient")
        self.assertTrue(detail)
        self.assertIsNone(pick(findings_for(flat(500, 80, 5), chat_events=events), "single_chatter_dominance"))

    def test_dominating_author_fires(self):
        events = messages("bot_1", 8) + messages("real_user", 2, author_start=START + dt.timedelta(minutes=1))
        state, detail = chat_message_input_state(events)
        self.assertEqual(state, "available")
        self.assertTrue(detail)

        findings = findings_for(flat(500, 80, 5), chat_events=events)
        dominance = pick(findings, "single_chatter_dominance")
        self.assertIsNotNone(dominance)
        self.assertEqual(set(dominance.observed), {"messages", "top_author", "top_share"})
        self.assertEqual(dominance.observed["messages"], 10)
        self.assertEqual(dominance.observed["top_author"], "bot_1")
        self.assertAlmostEqual(dominance.observed["top_share"], 0.8, places=9)
        self.assertEqual(dominance.weight, WEIGHTS["single_chatter_dominance"])
        self.assertGreater(dominance.score, 0.0)
        self.assertEqual(codes_of(findings), ["single_chatter_dominance", "passive_viewer_caveat"])

    def test_balanced_chat_does_not_fire(self):
        events = messages("bot_1", 7) + messages("real_user", 3, author_start=START + dt.timedelta(minutes=1))
        findings = findings_for(flat(500, 80, 5), chat_events=events)
        self.assertIsNone(pick(findings, "single_chatter_dominance"), codes_of(findings))
        self.assertEqual(codes_of(findings), [])


class MessageRateTest(unittest.TestCase):
    """`message_rate` is a PROXY: Δ of the chatter count, never real messages."""

    def varying(self, viewers=5000, minutes=60, *, start=0, span=29):
        """Timeline whose chatter count moves every minute, the natural case."""
        return series_of([(viewers + (index * 37) % 91, 400 + ((start + index) % span), 1) for index in range(minutes)])

    def test_frozen_chat_on_a_high_viewer_series_fires(self):
        findings = findings_for(flat(5000, 40, 60))
        rate = pick(findings, "message_rate")
        self.assertIsNotNone(rate, codes_of(findings))
        observed = rate.observed
        self.assertEqual(observed["source"], "chatters_proxy")
        self.assertEqual(observed["minutes"], 59)
        self.assertEqual(observed["stale_minutes"], 59)
        self.assertEqual(observed["stale_share"], 1.0)
        self.assertEqual(observed["messages_per_minute"], 0.0)
        self.assertEqual(observed["chatter_turnover"], 0.0)
        self.assertEqual(observed["chatters_median"], 40.0)
        self.assertEqual(observed["viewers_median"], 5000.0)
        self.assertTrue(observed["frozen"])
        self.assertFalse(observed["erratic"])
        self.assertEqual(rate.weight, WEIGHTS["message_rate"])
        self.assertGreater(rate.score, 0.0)
        self.assertLessEqual(rate.score, 1.0)

    def test_busy_naturally_varying_chat_does_not_fire(self):
        findings = findings_for(self.varying())
        self.assertIsNone(pick(findings, "message_rate"), codes_of(findings))

    def test_the_observed_numbers_describe_a_moving_chat(self):
        # A chat that moves every minute, in a window that fires for the other
        # reason (erratic): the reported rate must describe real movement, and
        # stale_minutes must stay far below the 47-65% every honest channel
        # shows on the live DB.
        points = series_of([(5000, 400 if index % 2 else 460, 1) for index in range(30)])
        observed = _only(_message_rate(points)).observed
        self.assertEqual(observed["minutes"], 30)
        # 31 expanded points, 30 deltas; `expand_series` carries the first
        # sample forward for a minute, so 12:00 is the one flat pair.
        self.assertEqual(observed["stale_minutes"], 1)
        self.assertEqual(observed["messages_per_minute"], 60.0)
        self.assertFalse(observed["frozen"])
        self.assertTrue(observed["erratic"])

    def test_turnover_counts_joins_and_leaves_separately(self):
        # A one-way climb: everyone joins, nobody leaves, so turnover is the
        # whole positive movement, not a net zero.
        points = series_of([(5000, 100 + index * 10, 1) for index in range(20)])
        # 21 expanded points, 20 deltas: the first sample is held for a minute
        # by `expand_series`, so one pair is flat and 19 steps of +10 join.
        observed = _only(_message_rate(points)).observed
        self.assertEqual(observed["chatter_turnover"], 190.0)
        self.assertEqual(observed["messages_per_minute"], 10.0)
        self.assertEqual(observed["stale_minutes"], 1)

    def test_erratic_chat_without_viewer_movement_fires(self):
        # Chatters swing minute to minute while the audience sits still.
        points = series_of([(5000, 400 if index % 2 else 460, 1) for index in range(30)])
        rate = _only(_message_rate(points))
        observed = rate.observed
        self.assertTrue(observed["erratic"])
        self.assertEqual(observed["unpaired_minutes"], 29)
        self.assertAlmostEqual(observed["unpaired_share"], 29 / 30, places=4)
        self.assertFalse(observed["frozen"])
        self.assertGreater(rate.score, 0.0)

    def test_small_audience_is_not_about_inactive_viewers(self):
        # 30/5 is the repo's own "ok" reference row: a tiny channel whose chat
        # does not move is not evidence of anything.
        self.assertIsNone(pick(findings_for(flat(30, 5, 60)), "message_rate"))

    def test_a_short_window_produces_nothing(self):
        self.assertIsNone(pick(findings_for(flat(5000, 40, 8)), "message_rate"))

    def test_it_never_says_messages_when_it_only_has_chatters(self):
        # The honest-label contract: the proxy is named as a proxy, and the
        # explanation cannot be read as counted messages.
        rate = _only(_message_rate(flat(5000, 40, 60)))
        self.assertIn("Прокси", rate.note)
        self.assertIn("прокси", rate.explanation.lower())
        self.assertIn("chatters_proxy", rate.note_args["source"])

    def test_real_messages_are_preferred_when_the_source_provides_them(self):
        # A future adapter that can read messages must not be ignored: the
        # counted rate replaces the proxy instead of sitting beside it.
        events = [
            {"author_login": f"user{index % 4}", "ts": START + dt.timedelta(seconds=index * 6)}
            for index in range(40)
        ]
        rate = _only(_message_rate(flat(5000, 40, 60), chat_events=events))
        self.assertEqual(rate.observed["source"], "chat_events")
        self.assertEqual(rate.observed["chatters_median"], 40.0)  # the reported chatter count

    def test_partial_message_capture_falls_back_to_the_proxy(self):
        # Events without a usable timestamp cannot be turned into a rate, so
        # the proxy is used rather than a partial count presented as truth.
        events = [{"author_login": "user_1"} for _ in range(40)]
        self.assertEqual(_only(_message_rate(flat(5000, 40, 60), chat_events=events)).observed["source"], "chatters_proxy")

    def test_chat_findings_emit_it_next_to_the_other_chat_signals(self):
        findings = findings_for(flat(5000, 40, 60))
        self.assertIn("message_rate", codes_of(findings))
        self.assertEqual(codes_of(findings)[-1], "passive_viewer_caveat")
        self.assertIn("message_rate", pick(findings, "passive_viewer_caveat").observed["triggered_by"])


class CaveatAndMetadataTest(unittest.TestCase):

    def test_healthy_channel_reports_nothing(self):
        self.assertEqual(findings_for(moving(300, 200, 15)), [])

    def test_no_finding_is_emitted_when_nothing_fired(self):
        findings = findings_for(flat(30, 5, 15))
        self.assertEqual(findings, [])

    def test_every_chat_finding_carries_the_caveat(self):
        events = messages("bot_1", 9) + messages("real_user", 1, author_start=START + dt.timedelta(minutes=1))
        points = series_of([(500, 50, 12), (900, 9, 12)])
        findings = findings_for(points, chat_events=events)

        expected_codes = [
            "silent_chat",
            "chat_starvation_ratio",
            "chat_collapse",
            "message_rate",
            "single_chatter_dominance",
            "passive_viewer_caveat",
        ]
        self.assertEqual(codes_of(findings), expected_codes)

        for finding in findings:
            with self.subTest(code=finding.code):
                self.assertEqual(finding.weight, WEIGHTS[finding.code])
                self.assertEqual(finding.note_code, f"note_{finding.code}")
                self.assertTrue(finding.note)
                self.assertTrue(finding.note_args)
                self.assertTrue(finding.explanation)
                self.assertTrue(finding.observed)
                # The Russian sentence is a template over note_args: it must render.
                rendered = finding.note.format(**finding.note_args)
                self.assertNotIn("{", rendered)
                if finding.code != "passive_viewer_caveat":
                    self.assertGreater(finding.score, 0.0)

        caveat = pick(findings, "passive_viewer_caveat")
        self.assertEqual(caveat.weight, 0.0)
        self.assertEqual(caveat.score, 0.0)
        self.assertEqual(
            caveat.observed["triggered_by"],
            ["silent_chat", "chat_starvation_ratio", "chat_collapse", "message_rate", "single_chatter_dominance"],
        )
        self.assertEqual(caveat.observed["viewers_median"], 700.0)
        self.assertIn("silent_chat", caveat.note)

    def test_caveat_lists_only_the_findings_that_fired(self):
        findings = findings_for(flat(500, 1, 5))
        self.assertEqual(codes_of(findings), ["chat_starvation_ratio", "passive_viewer_caveat"])
        self.assertEqual(pick(findings, "passive_viewer_caveat").observed["triggered_by"], ["chat_starvation_ratio"])

    def test_weights_are_the_contracted_ones(self):
        self.assertEqual(
            WEIGHTS,
            {
                "message_rate": 0.10,
                "silent_chat": 0.16,
                "chat_starvation_ratio": 0.12,
                "chat_collapse": 0.10,
                "single_chatter_dominance": 0.08,
                "passive_viewer_caveat": 0.0,
            },
        )


if __name__ == "__main__":
    unittest.main()
