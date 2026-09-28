"""Synthetic tests for the spike/plateau/staircase detectors (spec sections 3.2, 6).

Everything here is built from explicit per-minute timelines, so the assertions are
about detector behaviour (fired / not fired and the reported numbers), never about
fixtures. No database, no network.
"""
from __future__ import annotations

import datetime as dt
import unittest

from app.detect.series import Point, expand_series
from app.detect.spikes import WEIGHTS, detect_jumps, spike_findings

T0 = dt.datetime(2026, 9, 27, 18, 0, 0)
MINUTE = dt.timedelta(minutes=1)


def timeline(values, *, start=T0):
    """Build an expanded per-minute timeline; ``None`` values are real gaps."""
    return [
        Point(ts=start + MINUTE * index, viewers=value, chatters=None)
        for index, value in enumerate(values)
    ]


def codes(findings):
    return [finding.code for finding in findings]


def only(findings, code):
    matches = [finding for finding in findings if finding.code == code]
    assert len(matches) == 1, f"expected exactly one {code}, got {codes(findings)}"
    return matches[0]


class DetectJumpsTests(unittest.TestCase):
    def test_clean_step_jump_reports_numbers(self):
        jumps = detect_jumps(timeline([100] * 10 + [500] * 6))

        self.assertEqual(len(jumps), 1)
        jump = jumps[0]
        self.assertEqual(jump["started_ts"], T0 + MINUTE * 9)
        self.assertEqual(jump["peak_ts"], T0 + MINUTE * 10)
        self.assertIsNone(jump["ended_ts"])
        self.assertEqual(jump["baseline_viewers"], 100.0)
        self.assertEqual(jump["peak_viewers"], 500)
        self.assertEqual(jump["amplitude"], 5.0)
        self.assertEqual(jump["rise_seconds"], 60)
        self.assertIs(jump["is_instant"], True)
        self.assertEqual(jump["shape"], "flat_top")
        self.assertEqual(jump["threshold"], 150.0)
        self.assertEqual(jump["mad"], 0.0)
        self.assertEqual(jump["points"], 6)

    def test_flat_series_has_no_jump(self):
        self.assertEqual(detect_jumps(timeline([100] * 20)), [])

    def test_smooth_rise_is_not_instant(self):
        values = [100] * 10 + [200, 320, 500, 800, 800, 800] + [100] * 5
        jumps = detect_jumps(timeline(values))

        self.assertEqual(len(jumps), 1)
        jump = jumps[0]
        self.assertEqual(jump["amplitude"], 8.0)
        self.assertEqual(jump["rise_seconds"], 240)
        self.assertIs(jump["is_instant"], False)
        self.assertEqual(jump["shape"], "smooth")
        self.assertEqual(jump["peak_viewers"], 800)
        self.assertEqual(jump["ended_ts"], T0 + MINUTE * 16)

    def test_single_point_spike_shape(self):
        jumps = detect_jumps(timeline([100] * 10 + [400] + [100] * 10))

        self.assertEqual(len(jumps), 1)
        jump = jumps[0]
        self.assertEqual(jump["shape"], "single_point")
        self.assertEqual(jump["points"], 1)
        self.assertEqual(jump["amplitude"], 4.0)
        self.assertEqual(jump["ended_ts"], T0 + MINUTE * 11)

    def test_edge_inputs_do_not_crash(self):
        self.assertEqual(detect_jumps([]), [])
        self.assertEqual(detect_jumps(timeline([500])), [])
        self.assertEqual(detect_jumps(timeline([100, 900])), [])
        self.assertEqual(detect_jumps(timeline([100] * 3 + [900])), [])
        self.assertEqual(detect_jumps(timeline([0] * 8)), [])
        # A rise across a gap is not a jump: no statistic may bridge missing data.
        self.assertEqual(detect_jumps(timeline([100] * 10 + [None] + [500] * 10)), [])

    def test_min_points_is_respected(self):
        values = [100] * 3 + [900]
        self.assertEqual(detect_jumps(timeline(values)), [])
        jumps = detect_jumps(timeline(values), min_points=4)
        self.assertEqual(len(jumps), 1)
        self.assertEqual(jumps[0]["amplitude"], 9.0)
        self.assertEqual(jumps[0]["rise_seconds"], 60)

    def test_min_amplitude_is_respected(self):
        values = [100] * 10 + [130] * 5
        self.assertEqual(detect_jumps(timeline(values)), [])
        jumps = detect_jumps(timeline(values), min_amplitude=1.2)
        self.assertEqual(len(jumps), 1)
        self.assertEqual(jumps[0]["amplitude"], 1.3)

    def test_detects_jump_in_expanded_timeline(self):
        samples = [
            {"observed_at": T0, "last_seen_at": T0 + MINUTE * 10, "viewers": 100, "chatters": 5, "is_live": True},
            {
                "observed_at": T0 + MINUTE * 10,
                "last_seen_at": T0 + MINUTE * 25,
                "viewers": 500,
                "chatters": 20,
                "is_live": True,
            },
        ]
        jumps = detect_jumps(expand_series(samples))

        self.assertEqual(len(jumps), 1)
        self.assertEqual(jumps[0]["baseline_viewers"], 100.0)
        self.assertEqual(jumps[0]["peak_viewers"], 500)
        self.assertEqual(jumps[0]["rise_seconds"], 60)


class SpikeFindingTests(unittest.TestCase):
    def test_weights_table(self):
        self.assertEqual(
            WEIGHTS,
            {
                "no_justification": 0.22,
                "plateau_lock": 0.16,
                "repeat_shape": 0.14,
                "staircase_return": 0.06,
            },
        )

    def test_jump_without_cause_fires(self):
        findings = spike_findings(timeline([100] * 10 + [500] * 10))

        self.assertEqual(codes(findings), ["no_justification"])
        finding = findings[0]
        self.assertEqual(finding.weight, 0.22)
        self.assertEqual(finding.note_code, "note_no_justification")
        self.assertTrue(finding.note)
        self.assertEqual(
            finding.observed,
            {
                "amplitude": 5.0,
                "baseline_viewers": 100.0,
                "peak_viewers": 500,
                "peak_ts": (T0 + MINUTE * 10).isoformat(),
                "rise_seconds": 60,
                "is_instant": True,
                "sudden": True,
                "hints": [],
            },
        )
        # A one-minute climb is the canonical bot/raid shape. The amplitude
        # curve is `0.1 + 0.9 * scale(amp, 3, 12)`, so 5x lands near 0.3 --
        # full weight for its amplitude, not a large score.
        self.assertAlmostEqual(finding.score, 0.3, places=2)

    def test_sudden_large_jump_scores_far_above_small_one(self):
        small = spike_findings(timeline([100] * 10 + [500] * 10))[0]
        large = spike_findings(timeline([100] * 10 + [5000] * 10))[0]

        self.assertTrue(small.observed["is_instant"] and large.observed["is_instant"])
        self.assertLess(small.score, 0.4)
        self.assertGreater(large.score, 0.8)

    def test_slow_ramp_is_damped_even_at_huge_amplitude(self):
        """Amplitude alone must not convict. The live database has xqc climbing
        918 -> 28056 viewers (x30) over 114 minutes of smooth organic ramp; that
        has to score far below an instant jump of the same amplitude."""
        # A genuine ramp: the value climbs every minute, so the threshold is
        # crossed gradually and `rise_seconds` measures the whole climb.
        ramp = [100] * 10 + [100 + 400 * (i + 1) / 60 for i in range(60)] + [500] * 40
        slow_finding = spike_findings(timeline(ramp))[0]
        fast = spike_findings(timeline([100] * 10 + [500] * 10))[0]

        self.assertFalse(slow_finding.observed["sudden"], slow_finding.observed)
        self.assertTrue(fast.observed["sudden"])
        self.assertGreater(
            slow_finding.observed["amplitude"],
            3.0,
            "the ramp must still clear the amplitude bar, or this proves nothing",
        )
        self.assertLess(slow_finding.score, 0.2, "a one-hour ramp is not a suspicious spike")
        self.assertGreater(fast.score, slow_finding.score * 3)

    def test_jump_without_cause_note_args_are_complete(self):
        finding = spike_findings(timeline([100] * 10 + [500] * 10))[0]

        self.assertEqual(finding.note_args["hints"], "нет")
        self.assertTrue(0.0 < finding.score <= 1.0)

    def test_cause_hint_suppresses_no_justification(self):
        points = timeline([100] * 10 + [500] * 10)
        in_window = {"code": "title_change", "ts": T0 + MINUTE * 12}

        for hints in ({"title_change"}, ["title_change"], {"title_change": in_window["ts"]}, [in_window]):
            with self.subTest(hints=hints):
                self.assertEqual(spike_findings(points, cause_hints=hints), [])

    def test_hint_outside_the_jump_window_does_not_suppress(self):
        points = timeline([100] * 10 + [500] * 10)
        hints = [{"code": "raid_influx", "ts": T0 - dt.timedelta(hours=1)}]
        by_object = [type("Hint", (), {"code": "raid_influx", "ts": T0 - dt.timedelta(hours=1)})()]

        self.assertEqual(codes(spike_findings(points, cause_hints=hints)), ["no_justification"])
        self.assertEqual(codes(spike_findings(points, cause_hints=by_object)), ["no_justification"])

    def test_small_jump_does_not_fire_no_justification(self):
        findings = spike_findings(timeline([100] * 10 + [250] * 10))

        self.assertEqual(findings, [])

    def test_plateau_after_jump_fires(self):
        findings = spike_findings(timeline([320] * 10 + [1500] * 25))

        self.assertEqual(codes(findings), ["no_justification", "plateau_lock"])
        finding = only(findings, "plateau_lock")
        self.assertEqual(finding.weight, 0.16)
        self.assertEqual(finding.note_code, "note_plateau_lock")
        self.assertEqual(
            finding.observed,
            {
                "value": 1500.0,
                "minutes": 25,
                "delta_ratio": 0.0,
                "start_ts": (T0 + MINUTE * 10).isoformat(),
                "end_ts": (T0 + MINUTE * 34).isoformat(),
            },
        )
        self.assertTrue(0.0 < finding.score <= 1.0)

    def test_noisy_series_does_not_lock(self):
        pattern = [1000, 1150, 980, 1080, 920, 1120, 1010, 890, 1100, 960]
        findings = spike_findings(timeline(pattern * 4))

        self.assertEqual(findings, [])

    def test_short_plateau_does_not_fire(self):
        # A jump that is held for 19 minutes stays below the 20-minute rule.
        findings = spike_findings(timeline([100] * 10 + [500] * 19))

        self.assertEqual(codes(findings), ["no_justification"])

    def test_plateau_without_jump_does_not_fire(self):
        # The flat stretch must follow a jump: a flat stretch that *is* the baseline is normal.
        findings = spike_findings(timeline([100] * 40))

        self.assertEqual(findings, [])

    def test_repeat_shape_translates_matching_pairs(self):
        flat = timeline([100] * 20)
        repeats = [
            {"pair": ["stream_41", "stream_48"], "correlation": 0.9985, "max_abs_delta": 0.05},
            {"pair": ["stream_40", "stream_41"], "correlation": 0.90, "max_abs_delta": 0.15},
        ]

        findings = spike_findings(flat, shape_repeats=repeats)

        self.assertEqual(codes(findings), ["repeat_shape"])
        finding = findings[0]
        self.assertEqual(finding.weight, 0.14)
        self.assertEqual(finding.note_code, "note_repeat_shape")
        self.assertEqual(finding.observed, {"pairs": [["stream_41", "stream_48"]], "best_correlation": 0.9985})
        self.assertTrue(0.0 < finding.score <= 1.0)

    def test_repeat_shape_by_max_delta_and_empty_input(self):
        flat = timeline([100] * 20)
        by_delta = [{"pair": ["stream_2", "stream_7"], "correlation": 0.90, "max_abs_delta": 0.01}]

        findings = spike_findings(flat, shape_repeats=by_delta)

        self.assertEqual(codes(findings), ["repeat_shape"])
        self.assertEqual(findings[0].observed["best_correlation"], 0.9)
        self.assertEqual(spike_findings(flat, shape_repeats=[]), [])
        self.assertEqual(spike_findings(flat, shape_repeats=None), [])
        self.assertEqual(
            spike_findings(flat, shape_repeats=[{"pair": ["a", "b"], "correlation": 0.9, "max_abs_delta": 0.4}]),
            [],
        )

    def test_staircase_return_fires_on_one_minute_collapse(self):
        findings = spike_findings(timeline([120] * 30 + [0]))

        self.assertEqual(codes(findings), ["staircase_return"])
        finding = findings[0]
        self.assertEqual(finding.weight, 0.06)
        self.assertEqual(finding.note_code, "note_staircase_return")
        self.assertEqual(finding.observed["last_viewers"], 0)
        self.assertEqual(finding.observed["pre_median"], 120.0)
        self.assertEqual(finding.observed["collapse_seconds"], 60)
        self.assertAlmostEqual(finding.score, 1.0)

    def test_staircase_return_accepts_single_leftover_viewer(self):
        findings = spike_findings(timeline([120] * 30 + [1]))

        self.assertEqual(codes(findings), ["staircase_return"])
        self.assertEqual(findings[0].observed["last_viewers"], 1)

    def test_gradual_decay_is_not_a_staircase_return(self):
        findings = spike_findings(timeline([120] * 30 + [60, 30, 15, 7]))

        self.assertEqual(findings, [])

    def test_collapse_across_a_gap_is_not_a_staircase_return(self):
        findings = spike_findings(timeline([120] * 30 + [None] + [0]))

        self.assertEqual(findings, [])

    def test_every_finding_is_well_formed(self):
        points = timeline([320] * 10 + [1500] * 25 + [1])
        repeats = [{"pair": ["stream_1", "stream_2"], "correlation": 0.9999, "max_abs_delta": 0.0}]
        findings = spike_findings(points, shape_repeats=repeats)

        self.assertEqual(codes(findings), ["no_justification", "plateau_lock", "repeat_shape", "staircase_return"])
        for finding in findings:
            with self.subTest(code=finding.code):
                self.assertEqual(finding.weight, WEIGHTS[finding.code])
                self.assertEqual(finding.note_code, f"note_{finding.code}")
                self.assertTrue(finding.note)
                self.assertTrue(finding.explanation)
                self.assertTrue(0.0 < finding.score <= 1.0)
                self.assertTrue(finding.note_args)
        self.assertEqual(only(findings, "no_justification").note_args["hints"], "нет")
        self.assertEqual(only(findings, "staircase_return").observed["pre_median"], 1500.0)


if __name__ == "__main__":
    unittest.main()
