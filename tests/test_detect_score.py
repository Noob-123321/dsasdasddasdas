"""Aggregation and pipeline tests: the report the API and CLI actually return."""
from __future__ import annotations

import datetime as dt
import unittest

from app.detect import pipeline, score
from app.detect.series import Point
from app.detect.types import Finding

BASE = dt.datetime(2026, 1, 1, 12, 0, 0)


def series(count: int, viewers: int = 500, chatters: int = 60, start: dt.datetime = BASE) -> list[Point]:
    return [Point(ts=start + dt.timedelta(minutes=index), viewers=viewers, chatters=chatters) for index in range(count)]


class WeightedRiskTests(unittest.TestCase):
    def test_weighted_mean_uses_weights_not_a_plain_average(self):
        findings = [
            Finding(code="a", score=1.0, weight=0.25, observed={}, note=""),
            Finding(code="b", score=0.0, weight=0.75, observed={}, note=""),
        ]
        self.assertEqual(score.weighted_risk(findings), 25.0)

    def test_zero_weight_finding_does_not_move_the_index(self):
        caveat = Finding(code="passive_viewer_caveat", score=1.0, weight=0.0, observed={}, note="")
        fired = Finding(code="flatline", score=0.5, weight=0.2, observed={}, note="")
        self.assertEqual(score.weighted_risk([caveat, fired]), 50.0)

    def test_no_findings(self):
        self.assertIsNone(score.weighted_risk([]))


class VerdictTests(unittest.TestCase):
    def test_thresholds(self):
        cases = [(None, "nd"), (0.0, "green"), (29.9, "green"), (30.0, "yellow"), (60.0, "yellow"), (60.1, "red"), (100.0, "red")]
        for risk, expected in cases:
            with self.subTest(risk=risk):
                self.assertEqual(score.verdict_for(risk), expected)


class ConfidenceTests(unittest.TestCase):
    def test_full_availability_and_full_data_is_certain(self):
        availability = {name: True for name in score.METRICS}
        value, parts = score.confidence_for(samples_used=60, observed_minutes=240.0, availability=availability)
        self.assertEqual(value, 1.0)
        self.assertEqual(parts["metrics_missing"], [])

    def test_missing_metric_lowers_confidence_instead_of_scoring_zero(self):
        availability = {name: True for name in score.METRICS}
        availability["roster"] = False
        value, parts = score.confidence_for(60, 240.0, availability)
        self.assertAlmostEqual(value, 1 - 1 / len(score.METRICS), places=3)
        self.assertEqual(parts["metrics_missing"], ["roster"])

    def test_no_data_at_all(self):
        value, _ = score.confidence_for(0, 0.0, {name: False for name in score.METRICS})
        self.assertEqual(value, 0.0)


class SeriesMetaTests(unittest.TestCase):
    def test_counts_live_and_gap_points(self):
        points = series(3) + [Point(ts=BASE + dt.timedelta(minutes=3), viewers=None, chatters=None)]
        meta = score.series_meta(points, samples_used=2)
        self.assertEqual(meta["expanded_points"], 4)
        self.assertEqual(meta["live_points"], 3)
        self.assertEqual(meta["gap_points"], 1)
        self.assertEqual(meta["samples_used"], 2)
        self.assertEqual(meta["minute_seconds"], 60)


class BuildReportTests(unittest.TestCase):
    def test_warning_always_carries_the_not_probability_wording(self):
        report = score.build_report(
            channel="demo",
            points=[],
            samples_used=0,
            findings=[],
            availability={},
            unavailable=[],
            ad_vs_nonad={},
            window_hours=168.0,
        )
        self.assertIn(score.DISCLAIMER, report.warnings[0])
        self.assertEqual(report.verdict, "nd")
        self.assertIsNone(report.risk_score)
        self.assertEqual(report.warning_codes[0]["code"], score.DISCLAIMER_CODE)

    def test_unavailable_metrics_are_listed_and_do_not_create_a_score(self):
        report = score.build_report(
            channel="demo",
            points=series(30),
            samples_used=10,
            findings=[],
            availability={"series": True, "chat_events": False},
            unavailable=[{"metric": "chat_events", "detail": "нет сообщений"}],
            ad_vs_nonad={},
            window_hours=24.0,
        )
        self.assertEqual(report.risk_score, 0.0)
        self.assertEqual(report.verdict, "green")
        self.assertTrue(any("chat_events" in warning for warning in report.warnings))
        self.assertTrue(any("нет сообщений" in warning for warning in report.warnings))


class PipelineTests(unittest.TestCase):
    def test_flat_series_produces_a_report_with_evidence(self):
        data = pipeline.DetectionInput(channel="flat", points=series(90, viewers=400, chatters=40), samples_used=40, window_hours=24.0)
        report = pipeline.build(data, now=BASE + dt.timedelta(hours=2))
        codes = [factor["code"] for factor in report.factors]
        self.assertIn("flatline", codes)
        for factor in report.factors:
            self.assertTrue(factor["observed"], f"{factor['code']} carries no observed numbers")
            self.assertTrue(factor["note"])
        self.assertGreater(report.risk_score, 0)
        self.assertIn(report.verdict, {"green", "yellow", "red"})
        self.assertEqual(report.series["live_points"], 90)
        # The chat metrics are present but the message-based detector is not.
        self.assertNotIn("chat_events", report.confidence_parts["metrics_present"])
        self.assertIn("chat_events", report.confidence_parts["metrics_missing"])

    def test_empty_input_is_reported_as_no_observations(self):
        report = pipeline.build(pipeline.DetectionInput(channel="empty"), now=BASE)
        self.assertEqual(report.verdict, "nd")
        self.assertIsNone(report.risk_score)
        self.assertTrue(any("нет наблюдений" in warning for warning in report.warnings))
        self.assertTrue(any(item["metric"] == "series" for item in report.unavailable))

    def test_ad_comparison_is_always_serialisable(self):
        data = pipeline.DetectionInput(channel="ads", points=series(60, viewers=1000, chatters=120), samples_used=30, window_hours=24.0)
        report = pipeline.build(data, now=BASE + dt.timedelta(hours=1))
        payload = report.to_dict()
        self.assertIn("ad_vs_nonad", payload)
        self.assertIn("available", payload["ad_vs_nonad"])
        self.assertNotIn("finding", payload["ad_vs_nonad"])
        for factor in payload["factors"]:
            self.assertIsInstance(factor["observed"], dict)


class UnavailableMetricTests(unittest.TestCase):
    """A metric the client cannot read must lower confidence, never score 0.0."""

    def report(self, chat_events):
        # One healthy, noisy window: a constant series would fire `flatline`
        # and make the risk score depend on the chat input, which is exactly
        # what these tests must not measure.
        points = [
            Point(ts=BASE + dt.timedelta(minutes=index), viewers=400 + (index * 37) % 91, chatters=40 + (index * 13) % 17)
            for index in range(90)
        ]
        data = pipeline.DetectionInput(
            channel="chatty",
            points=points,
            samples_used=90,
            chat_events=chat_events,
            window_hours=24.0,
        )
        return pipeline.build(data, now=BASE + dt.timedelta(hours=2))

    def test_missing_chat_events_is_reported_as_unavailable(self):
        report = self.report(chat_events=[])
        self.assertIn("chat_events", [item["metric"] for item in report.unavailable])
        self.assertNotIn("chat_events", report.confidence_parts["metrics_present"])
        self.assertIn("chat_events", report.confidence_parts["metrics_missing"])
        self.assertTrue(any("chat_events" in warning for warning in report.warnings))

    def test_unreadable_chat_events_do_not_fake_a_passing_dominance_check(self):
        # The anonymous client cannot read messages, so `single_chatter_dominance`
        # must never appear as a passing 0.0 factor.
        report = self.report(chat_events=[])
        self.assertNotIn("single_chatter_dominance", [factor["code"] for factor in report.factors])
        self.assertTrue(any(item["metric"] == "chat_events" for item in report.unavailable))

    def test_missing_chat_events_lowers_confidence_versus_supplied_ones(self):
        without = self.report(chat_events=[])
        with_events = self.report(chat_events=[{"author_login": f"user{index % 12}"} for index in range(40)])

        self.assertIn("chat_events", without.confidence_parts["metrics_missing"])
        self.assertIn("chat_events", with_events.confidence_parts["metrics_present"])
        self.assertLess(without.confidence, with_events.confidence)
        # The gap is exactly one metric's share of the (data_factor weighted)
        # confidence: with 90 observed minutes the data factor is 90/240.
        data_factor = 90.0 / 240.0
        self.assertAlmostEqual(
            with_events.confidence - without.confidence,
            (1 / len(score.METRICS)) * (0.65 * data_factor + 0.35),
            places=3,
        )

    def test_confidence_drop_is_covered_by_the_availability_ratio(self):
        without = self.report(chat_events=[])
        with_events = self.report(chat_events=[{"author_login": "solo"} for _ in range(40)])
        parts_without = without.confidence_parts
        parts_with = with_events.confidence_parts

        self.assertEqual(parts_without["data_factor"], parts_with["data_factor"])
        self.assertEqual(parts_without["sample_factor"], parts_with["sample_factor"])
        self.assertLess(parts_without["available_ratio"], parts_with["available_ratio"])


if __name__ == "__main__":
    unittest.main()
