"""Regression tests for the two data bugs that only real data exposed.

Both were found by running the pipeline against the live ``data/tvb.db``, so they
need permanent tests: a regression here silently convicts honest channels.

* :class:`PollerOutageTests` -- a poller outage recorded as one ``Sample`` whose
  ``interval_seconds`` spans ~21 h must NOT become a fake multi-hour plateau.
* :class:`RiseSpeedTests` -- the same amplitude delivered slowly must not be
  convicted, because amplitude alone cannot tell a raid from an organic ramp.
"""
from __future__ import annotations

import datetime as dt
import unittest

from app.detect import pipeline
from app.detect.series import Point, expand_series, live_points
from app.detect.shapes import shape_findings
from app.detect.spikes import spike_findings

T0 = dt.datetime(2026, 9, 27, 18, 0, 0)
MINUTE = dt.timedelta(minutes=1)

#: A real, honest channel ticking around 300 viewers: it moves every minute and
#: never sits on one value. Chatters track viewers at a healthy 12 %.
HONEST = (300, 305, 298, 310, 302, 297, 309, 301, 296, 304, 302, 299, 307, 303, 298, 305, 301, 306, 299, 302, 300, 304, 298, 301, 303, 297, 306, 300, 302, 299)


def sample(minute, viewers, chatters, *, repeat=1, interval=60, live=True):
    ts = T0 + MINUTE * minute
    return {
        "observed_at": ts,
        "last_seen_at": ts,
        "repeat_count": repeat,
        "interval_seconds": interval,
        "is_live": live,
        "viewer_count": viewers,
        "chatters_count": chatters,
    }


def expand(rows):
    return expand_series(rows)


def codes(findings):
    return [finding.code for finding in findings]


def _expand_using_interval_seconds(rows, *, minute_seconds=60.0, max_gap_minutes=15.0):
    """The OLD, buggy expansion: hold each row for ``interval_seconds``.

    Kept only so the regression test can prove the fixture still reproduces the
    failure it was written for. Nothing in the product may call this.
    """
    step = dt.timedelta(seconds=minute_seconds)
    gap = dt.timedelta(minutes=max_gap_minutes)
    spans = [
        (row["observed_at"], row["observed_at"] + dt.timedelta(seconds=float(row["interval_seconds"] or minute_seconds)),
         row["viewer_count"], row["chatters_count"])
        for row in rows
    ]
    spans.sort(key=lambda item: item[0])
    points, index, previous, previous_end = [], 0, None, None
    moment = spans[0][0]
    last = max(span[1] for span in spans)
    while moment <= last:
        while index < len(spans) and spans[index][1] < moment:
            previous, previous_end = (spans[index][2], spans[index][3]), spans[index][1]
            index += 1
        if index < len(spans) and spans[index][0] <= moment <= spans[index][1]:
            viewers, chatters = spans[index][2], spans[index][3]
        elif previous is not None and moment - previous_end <= gap:
            viewers, chatters = previous
        else:
            viewers, chatters = None, None
        points.append(Point(ts=moment, viewers=viewers, chatters=chatters))
        moment += step
    return points


class PollerOutageTests(unittest.TestCase):
    """`interval_seconds` includes every second the poller was down."""

    def setUp(self):
        self.rows = [sample(i, value, max(1, value // 8)) for i, value in enumerate(HONEST)]
        # The poller restarts ~21 h later and sees the same viewer count, so the
        # row records a 21 h `interval_seconds` (time since the previous CHANGED
        # row) while `repeat_count` is 1: the value was seen exactly once.
        outage = T0 + MINUTE * len(HONEST) + dt.timedelta(hours=21)
        self.rows.append(
            {
                "observed_at": outage,
                "last_seen_at": outage,
                "repeat_count": 1,
                "interval_seconds": 21 * 3600,
                "is_live": True,
                "viewer_count": HONEST[-1],
                "chatters_count": max(1, HONEST[-1] // 8),
            }
        )
        self.points = expand(self.rows)

    def test_outage_does_not_become_a_multi_hour_plateau(self):
        # `repeat_count == 1` means the value was seen exactly once, so it is
        # held for one poll interval, not for the 21 h `interval_seconds`. The
        # post-outage minute plus the 15-minute carry-forward tolerance of
        # `max_gap_minutes` account for the rest; 21 h would mean ~1260.
        self.assertEqual(len(live_points(self.points)), len(HONEST) + 18)
        self.assertNotIn("plateau_lock", codes(spike_findings(self.points)))
        self.assertNotIn("flatline", codes(shape_findings(self.points)))

    def test_the_outage_is_reported_as_a_gap_not_as_flatness(self):
        report = pipeline.build(
            pipeline.DetectionInput(channel="honest", points=self.points, samples_used=len(self.rows), window_hours=48.0),
            now=self.points[-1].ts,
        )
        meta = report.series
        self.assertGreater(meta["gap_points"], 1000)
        self.assertEqual(meta["observed_minutes"], float(len(HONEST) + 18))
        self.assertNotIn("plateau_lock", [factor["code"] for factor in report.factors])
        self.assertNotIn("flatline", [factor["code"] for factor in report.factors])

    def test_reading_interval_seconds_as_the_hold_time_reproduces_the_bug(self):
        # The point of the fixture: with the OLD semantics the very same rows
        # report ~1277 observed minutes and convict the honest channel. That
        # failure mode is what `expand_series` must never reintroduce.
        buggy = _expand_using_interval_seconds(self.rows)
        live = live_points(buggy)
        self.assertGreater(len(live), 1200)
        self.assertIn("flatline", codes(shape_findings(buggy)))
        # ... while the shipped expansion stays at a handful of minutes.
        self.assertLess(len(live_points(self.points)), 60)


class RiseSpeedTests(unittest.TestCase):
    """Amplitude alone must not convict: xqc ramped 918 -> 28056 (x30) in 114 min."""

    START = dt.datetime(2026, 9, 27, 19, 47, 0)
    BASELINE = 918
    PEAK = 28056
    RAMP_MINUTES = 114
    CHAT_RATIO = 0.12
    MINUTES = 190

    def rows(self, value_at):
        rows: list[dict] = []
        last = None
        for index in range(self.MINUTES):
            moment = self.START + MINUTE * index
            viewers = value_at(index)
            if viewers == last:
                continue  # change-aware poller: an unchanged value adds no row
            rows.append(
                {
                    "observed_at": moment,
                    "last_seen_at": moment,
                    "repeat_count": 1,
                    "interval_seconds": 60,
                    "is_live": True,
                    "viewer_count": viewers,
                    "chatters_count": max(1, round(viewers * self.CHAT_RATIO)),
                }
            )
            last = viewers
        return rows

    def organic_ramp(self) -> list[dict]:
        """xqc's measured shape: 918 held, then +27138 viewers over 114 minutes."""

        def value_at(index):
            if index < 40:
                return self.BASELINE + (index % 3) * 2
            step = index - 40
            if step < self.RAMP_MINUTES:
                share = (step / self.RAMP_MINUTES) ** 1.35
                return round(self.BASELINE + (self.PEAK - self.BASELINE) * share + 120 * ((step % 7) - 3))
            return round(self.PEAK * (1 + 0.04 * ((step - self.RAMP_MINUTES) % 11) / 10.0))

        return self.rows(value_at)

    def instant_rise(self) -> list[dict]:
        """The same amplitude, delivered inside a single minute."""

        def value_at(index):
            if index < 40:
                return self.BASELINE + (index % 3) * 2
            if index == 40:
                return self.PEAK
            return round(self.PEAK * (1 + 0.04 * ((index - 40) % 11) / 10.0))

        return self.rows(value_at)

    def report(self, rows):
        points = expand(rows)
        return points, pipeline.build(
            pipeline.DetectionInput(channel="xqc", points=points, samples_used=len(rows), window_hours=6.0),
            now=points[-1].ts,
        )

    def test_organic_ramp_is_not_convicted(self):
        points, report = self.report(self.organic_ramp())
        factors = [factor["code"] for factor in report.factors]

        self.assertNotIn("no_justification", factors)
        self.assertEqual(report.risk_score, 0.0)
        self.assertEqual(report.verdict, "green")

    def test_organic_114_minute_ramp_scores_below_a_fifth(self):
        points, report = self.report(self.organic_ramp())
        jump = [
            finding
            for finding in spike_findings(points)
            if finding.code == "no_justification"
        ]
        # The finding is still reported -- only suppressed once a cause hint
        # lands inside the window -- but it must carry no weight.
        if jump:
            self.assertLess(jump[0].score, 0.2)
        self.assertLessEqual(report.risk_score, 20.0)

    def test_instant_rise_of_the_same_amplitude_scores_above_a_third(self):
        points, _report = self.report(self.instant_rise())
        instant = [
            finding
            for finding in spike_findings(points)
            if finding.code == "no_justification"
        ]
        self.assertEqual(len(instant), 1)
        self.assertGreater(instant[0].score, 0.3)
        self.assertGreater(instant[0].observed["amplitude"], 30.0)

    def test_the_two_shapes_differ_only_in_speed(self):
        slow_points, _ = self.report(self.organic_ramp())
        fast_points, _ = self.report(self.instant_rise())
        slow = [f for f in spike_findings(slow_points) if f.code == "no_justification"][0]
        fast = [f for f in spike_findings(fast_points) if f.code == "no_justification"][0]

        # Same peak, same baseline, the discriminator is rise_seconds alone.
        self.assertEqual(slow.observed["peak_viewers"], fast.observed["peak_viewers"])
        self.assertGreater(fast.observed["rise_seconds"], slow.observed["rise_seconds"] * 0.01)
        self.assertLess(slow.score, 0.2)
        self.assertGreater(fast.score, 0.3)


if __name__ == "__main__":
    unittest.main()
