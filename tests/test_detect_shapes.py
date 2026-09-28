"""Tests for :mod:`app.detect.shapes` (spec §6: synthetic flatline fires, noise does not).

Everything here is driven by hand-built :class:`~app.detect.series.Point`
timelines, so the assertions state the exact numbers the detectors observed.
"""
from __future__ import annotations

import datetime as dt
import unittest

from app.detect.series import Point
from app.detect.shapes import (
    WEIGHTS,
    curve_similarity,
    normalised_entropy,
    repeat_shape_hints,
    shape_findings,
    shannon_entropy,
)

BASE = dt.datetime(2026, 1, 1, 0, 0)

# A deterministic but deliberately irregular audience: the value moves every
# minute, by varying amounts, so nothing is flat or piecewise linear.
NOISY = [
    300, 305, 298, 312, 290, 330, 315, 288, 301, 345,
    299, 277, 320, 310, 296, 333, 281, 308, 322, 295,
    340, 289, 313, 301, 327, 276, 318, 307, 292, 336,
    304, 311, 299, 325, 285, 316, 302, 331, 294, 309,
]


def series(numbers, start=BASE):
    """Expanded per-minute timeline from a list of viewer counts."""
    return [
        Point(ts=start + dt.timedelta(minutes=index), viewers=value, chatters=None)
        for index, value in enumerate(numbers)
    ]


def point(minute, viewers, start=BASE):
    return Point(ts=start + dt.timedelta(minutes=minute), viewers=viewers, chatters=None)


def hourly(values, start=BASE):
    """One live point per hour starting at ``start``; ``values`` gives viewers."""
    return [
        Point(ts=start + dt.timedelta(hours=hour), viewers=value, chatters=None)
        for hour, value in enumerate(values)
    ]


def codes(findings):
    return [finding.code for finding in findings]


def one(findings, code):
    matches = [finding for finding in findings if finding.code == code]
    assert len(matches) == 1, f"expected exactly one {code}, got {codes(findings)}"
    return matches[0]


class WeightTests(unittest.TestCase):
    def test_weights_match_spec(self):
        self.assertEqual(
            WEIGHTS,
            {
                "flatline": 0.14,
                "suspicious_smoothness": 0.10,
                "low_entropy": 0.08,
                "time_of_day_independence": 0.06,
                "instant_restore": 0.06,
            },
        )


class FlatlineTests(unittest.TestCase):
    def test_perfectly_flat_series_fires(self):
        finding = one(shape_findings(series([300] * 60)), "flatline")
        self.assertEqual(
            finding.observed,
            {
                "window_minutes": 60,
                "zero_delta_minutes": 59,
                "zero_delta_fraction": 1.0,
                "viewers": 300,
            },
        )
        self.assertEqual(finding.weight, WEIGHTS["flatline"])
        self.assertEqual(finding.note_code, "note_flatline")
        # spec scaling: scale(60, 30, 120) == 1/3
        self.assertAlmostEqual(finding.score, 1 / 3, places=4)

    def test_longer_flatline_scores_higher(self):
        scores = [one(shape_findings(series([300] * minutes)), "flatline").score for minutes in (30, 60, 120)]
        self.assertLess(scores[0], scores[1])
        self.assertLess(scores[1], scores[2])
        self.assertAlmostEqual(scores[2], 1.0, places=6)

    def test_natural_noise_does_not_fire(self):
        findings = shape_findings(series(NOISY))
        self.assertNotIn("flatline", codes(findings))
        self.assertEqual(findings, [])

    def test_viewers_below_twenty_do_not_fire(self):
        flattened = [15] * 60
        self.assertNotIn("flatline", codes(shape_findings(series(flattened))))

    def test_gap_splits_the_window(self):
        timeline = series([300] * 40) + [point(minute, None) for minute in range(40, 50)]
        timeline += [point(minute, 300) for minute in range(50, 90)]
        finding = one(shape_findings(timeline), "flatline")
        self.assertEqual(finding.observed["window_minutes"], 40)
        self.assertEqual(finding.observed["zero_delta_minutes"], 39)


class SuspiciousSmoothnessTests(unittest.TestCase):
    def test_piecewise_linear_curve_fires_without_history(self):
        finding = one(shape_findings(series([100 + 2 * index for index in range(60)])), "suspicious_smoothness")
        self.assertEqual(
            finding.observed,
            {
                "near_zero_share": 1.0,
                "median_d2": 0.0,
                "threshold": 0.795,
                "history_median_d2": None,
                "minutes": 60,
            },
        )
        self.assertEqual(finding.weight, WEIGHTS["suspicious_smoothness"])

    def test_natural_noise_does_not_fire(self):
        self.assertNotIn("suspicious_smoothness", codes(shape_findings(series(NOISY))))

    def test_history_blocks_a_channel_that_is_always_smooth(self):
        alternating = series([3000 + (index % 2) for index in range(60)])
        self.assertIn("suspicious_smoothness", codes(shape_findings(alternating)))
        with_history = shape_findings(alternating, history=[series([3000] * 60)])
        self.assertNotIn("suspicious_smoothness", codes(with_history))

    def test_smooth_current_series_against_noisy_history_fires(self):
        finding = one(
            shape_findings(series([100 + 2 * index for index in range(60)]), history=[series(NOISY)]),
            "suspicious_smoothness",
        )
        self.assertEqual(finding.observed["history_median_d2"], 51.5)
        self.assertEqual(finding.observed["median_d2"], 0.0)


class EntropyHelperTests(unittest.TestCase):
    def test_shannon_entropy_hand_computable(self):
        self.assertAlmostEqual(shannon_entropy([10, 10, 20, 20]), 1.0, places=9)
        self.assertAlmostEqual(shannon_entropy([10, 20, 30, 40]), 2.0, places=9)
        self.assertAlmostEqual(shannon_entropy([1, 1, 1, 2, 3, 4]), 1.79248125, places=8)
        self.assertAlmostEqual(shannon_entropy([10] * 8), 0.0, places=9)
        self.assertAlmostEqual(shannon_entropy([]), 0.0, places=9)

    def test_normalised_entropy_hand_computable(self):
        self.assertAlmostEqual(normalised_entropy([10, 20, 30, 40]), 1.0, places=9)
        self.assertAlmostEqual(normalised_entropy([1, 1, 1, 2, 3, 4]), 0.89624063, places=8)
        self.assertIsNone(normalised_entropy([5] * 8))
        self.assertIsNone(normalised_entropy([]))


class LowEntropyTests(unittest.TestCase):
    def test_dominant_bucket_fires(self):
        finding = one(shape_findings(series([500] * 56 + [900] * 4)), "low_entropy")
        observed = finding.observed
        self.assertEqual(observed["minutes"], 60)
        self.assertEqual(observed["buckets"], 2)
        self.assertAlmostEqual(observed["dominant_share"], 56 / 60, places=6)
        self.assertAlmostEqual(observed["entropy_bits"], 0.353359, places=5)
        self.assertAlmostEqual(finding.score, 56 / 60, places=6)
        self.assertEqual(finding.weight, WEIGHTS["low_entropy"])

    def test_normalised_entropy_arm_fires_on_spread_but_uneven_series(self):
        finding = one(shape_findings(series([5000] * 76 + [5100, 5200, 5300, 5400])), "low_entropy")
        observed = finding.observed
        self.assertEqual(observed["minutes"], 80)
        self.assertEqual(observed["buckets"], 5)
        self.assertAlmostEqual(observed["normalised"], 0.166412, places=5)
        self.assertLessEqual(observed["normalised"], 0.25)
        self.assertAlmostEqual(finding.score, 0.95, places=5)

    def test_needs_five_buckets(self):
        # 80% dominance over four buckets: normalised entropy is high and the
        # single-bucket arm is not reached either.
        timeline = series([500] * 40 + [700] * 3 + [800] * 4 + [900] * 3)
        self.assertNotIn("low_entropy", codes(shape_findings(timeline)))

    def test_varied_audience_does_not_fire(self):
        self.assertNotIn("low_entropy", codes(shape_findings(series(NOISY))))

    def test_needs_thirty_minutes(self):
        self.assertNotIn("low_entropy", codes(shape_findings(series([500] * 20))))


class TimeOfDayTests(unittest.TestCase):
    CURRENT = [600, 500, 400, 300, 200, 100]

    def test_anti_correlated_diurnal_curve_fires(self):
        finding = one(
            shape_findings(hourly(self.CURRENT), history=[hourly([100, 200, 300, 400, 500, 600])]),
            "time_of_day_independence",
        )
        observed = finding.observed
        self.assertEqual(observed["hours_compared"], 6)
        self.assertAlmostEqual(observed["correlation"], -1.0, places=6)
        self.assertEqual(observed["current_hourly"]["0"], 600.0)
        self.assertEqual(observed["history_hourly"]["5"], 600.0)
        self.assertAlmostEqual(finding.score, 1.0, places=6)
        self.assertEqual(finding.weight, WEIGHTS["time_of_day_independence"])

    def test_without_history_never_fires(self):
        self.assertNotIn("time_of_day_independence", codes(shape_findings(hourly(self.CURRENT))))

    def test_matching_history_does_not_fire(self):
        findings = shape_findings(hourly(self.CURRENT), history=[hourly([1200, 1000, 800, 600, 400, 200])])
        self.assertEqual(findings, [])

    def test_undefined_correlation_fires_when_current_is_flat_across_hours(self):
        finding = one(
            shape_findings(hourly([100] * 6), history=[hourly([100, 200, 300, 400, 500, 600])]),
            "time_of_day_independence",
        )
        self.assertIsNone(finding.observed["correlation"])
        self.assertEqual(finding.observed["hours_compared"], 6)
        self.assertEqual(finding.note_args["correlation"], "-")

    def test_needs_three_shared_hours(self):
        findings = shape_findings(hourly([100, 200]), history=[hourly([900, 800])])
        self.assertEqual(findings, [])


class InstantRestoreTests(unittest.TestCase):
    @staticmethod
    def restart_timeline(before, after, gap_minutes):
        timeline = [point(minute, before) for minute in range(20)]
        timeline += [point(minute, None) for minute in range(20, 20 + gap_minutes)]
        timeline += [point(minute, after) for minute in range(20 + gap_minutes, 40 + gap_minutes)]
        return timeline

    def test_end_and_restart_fires(self):
        finding = one(shape_findings(self.restart_timeline(300, 303, 3)), "instant_restore")
        self.assertEqual(
            finding.observed,
            {
                "before_viewers": 300,
                "after_viewers": 303,
                "gap_minutes": 3.0,
                "delta_ratio": 0.01,
            },
        )
        self.assertEqual(finding.weight, WEIGHTS["instant_restore"])
        self.assertEqual(finding.note_code, "note_instant_restore")
        self.assertAlmostEqual(finding.score, 0.75, places=6)

    def test_viewers_that_do_not_return_do_not_fire(self):
        self.assertNotIn("instant_restore", codes(shape_findings(self.restart_timeline(300, 350, 3))))

    def test_short_gap_does_not_fire(self):
        self.assertNotIn("instant_restore", codes(shape_findings(self.restart_timeline(300, 300, 2))))

    def test_single_live_run_does_not_fire(self):
        self.assertNotIn("instant_restore", codes(shape_findings(series(NOISY))))


class CurveSimilarityTests(unittest.TestCase):
    def test_scaled_identical_curves(self):
        left = series([100 + 5 * index for index in range(20)])
        right = series([300 + 5 * index for index in range(20)])
        result = curve_similarity(left, right)
        self.assertEqual(result["points"], 20)
        self.assertAlmostEqual(result["correlation"], 1.0, places=6)
        self.assertAlmostEqual(result["max_abs_delta"], 0.0, places=6)

    def test_opposite_curves(self):
        left = series([100 + 5 * index for index in range(20)])
        right = series([300 - 5 * index for index in range(20)])
        result = curve_similarity(left, right)
        self.assertAlmostEqual(result["correlation"], -1.0, places=6)
        self.assertAlmostEqual(result["max_abs_delta"], 1.0, places=6)

    def test_unrelated_curves(self):
        left = series([100 + 5 * index for index in range(20)])
        zigzag = series([100 if index % 2 else 200 for index in range(20)])
        result = curve_similarity(left, zigzag)
        self.assertLess(result["correlation"], 0.5)
        self.assertGreater(result["max_abs_delta"], 0.5)

    def test_resamples_onto_a_common_grid(self):
        left = series([100 + 4 * index for index in range(20)])
        right = series([100 + 2 * index for index in range(40)])
        result = curve_similarity(left, right)
        self.assertEqual(result["points"], 20)
        self.assertAlmostEqual(result["correlation"], 1.0, places=6)

    def test_too_short_series_have_no_correlation(self):
        result = curve_similarity(series([5]), series([7]))
        self.assertEqual(result, {"correlation": None, "max_abs_delta": None, "points": 1})


class RepeatShapeHintTests(unittest.TestCase):
    def test_scaled_repeat_is_detected(self):
        left = series([100 + 5 * index for index in range(20)])
        right = series([700 + 9 * index for index in range(20)])
        hints = repeat_shape_hints([left, right])
        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0]["pair"], [0, 1])
        self.assertAlmostEqual(hints[0]["correlation"], 1.0, places=6)
        self.assertAlmostEqual(hints[0]["max_abs_delta"], 0.0, places=6)

    def test_unrelated_curves_are_not_hinted(self):
        left = series([100 + 5 * index for index in range(20)])
        right = series([300 - 5 * index for index in range(20)])
        self.assertEqual(repeat_shape_hints([left, right]), [])

    def test_constant_curves_match_by_max_delta(self):
        hints = repeat_shape_hints([series([50] * 20), series([90] * 20)])
        self.assertEqual(len(hints), 1)
        self.assertIsNone(hints[0]["correlation"])
        self.assertAlmostEqual(hints[0]["max_abs_delta"], 0.0, places=6)


class FindingContractTests(unittest.TestCase):
    EXPECTED_KEYS = {
        "flatline": {"window_minutes", "zero_delta_minutes", "zero_delta_fraction", "viewers"},
        "suspicious_smoothness": {"near_zero_share", "median_d2", "threshold", "history_median_d2", "minutes"},
        "low_entropy": {"entropy_bits", "normalised", "buckets", "dominant_share", "minutes"},
        "time_of_day_independence": {
            "correlation",
            "hours_compared",
            "current_hourly",
            "history_hourly",
        },
        "instant_restore": {"before_viewers", "after_viewers", "gap_minutes", "delta_ratio"},
    }

    def test_empty_and_short_series_produce_nothing(self):
        self.assertEqual(shape_findings([]), [])
        self.assertEqual(shape_findings(series([100] * 10)), [])

    def test_every_finding_is_self_describing(self):
        timeline = series([300] * 60) + [point(minute, None) for minute in range(60, 64)]
        timeline += [point(minute, 301) for minute in range(64, 94)]
        findings = shape_findings(timeline)
        self.assertIn("flatline", codes(findings))
        self.assertIn("instant_restore", codes(findings))
        for finding in findings:
            with self.subTest(code=finding.code):
                self.assertIn(finding.code, WEIGHTS)
                self.assertEqual(finding.weight, WEIGHTS[finding.code])
                self.assertEqual(finding.note_code, f"note_{finding.code}")
                self.assertTrue(finding.note)
                self.assertTrue(finding.explanation)
                self.assertEqual(set(finding.observed), self.EXPECTED_KEYS[finding.code])
                self.assertTrue(finding.note_args)
                for value in finding.note_args.values():
                    self.assertIsInstance(value, (str, int, float))
                    self.assertNotIsInstance(value, bool)

    def test_scores_stay_inside_the_unit_interval(self):
        timeline = series([300] * 60) + [point(minute, None) for minute in range(60, 64)]
        timeline += [point(minute, 301) for minute in range(64, 94)]
        for finding in shape_findings(timeline):
            self.assertGreater(finding.score, 0.0)
            self.assertLessEqual(finding.score, 1.0)

    def test_results_are_deterministic(self):
        timeline = series([300] * 60)
        first = [(finding.code, finding.observed) for finding in shape_findings(timeline)]
        second = [(finding.code, finding.observed) for finding in shape_findings(timeline)]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
