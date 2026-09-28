"""Тесты прокси-детектора рекламных разрывов (idea #8).

Запуск:
    python -m pytest -q tests/test_detect_causes.py

Реклама анонимно не читается (docs/DETECTION_SPEC.md §1), поэтому проверяется не
«нашлась ли реклама», а то, что детектор честно реагирует на наблюдаемые
прокси-признаки и не выдумывает измерения там, где данных нет.
"""
import datetime as dt
import unittest

from app.detect.causes import (
    RAID_WINDOW_MINUTES,
    WEIGHTS,
    ad_break_estimates,
    compare_ad_vs_nonad,
)
from app.detect.series import Point

BASE_TS = dt.datetime(2026, 9, 27, 18, 0)
MINUTE = dt.timedelta(minutes=1)


def timeline(viewers, chatters=None, start=BASE_TS):
    """Per-minute expanded timeline; ``chatters=None`` means no chat data."""
    return [
        Point(start + index * MINUTE, value, None if chatters is None else chatters[index])
        for index, value in enumerate(viewers)
    ]


def flat(count, value, chat):
    return [value] * count, [chat] * count


def cliff_series(count=120, baseline=1000, dip=850, rebound=950, drop_minute=60, rebound_minute=68):
    """Flat online with one >=12% single-minute drop and a rebound within 10 min."""
    viewers, chatters = flat(count, baseline, baseline // 10)
    for minute in range(drop_minute, rebound_minute):
        viewers[minute] = dip
    viewers[rebound_minute] = rebound
    return timeline(viewers, chatters)


def sample_rows(minutes, **fields):
    return [dict(observed_at=BASE_TS + minute * MINUTE, **fields) for minute in minutes]


class ViewerCliffTests(unittest.TestCase):
    def test_drop_and_rebound_is_detected_with_the_numbers_that_produced_it(self):
        points = cliff_series()

        estimates = ad_break_estimates(points)

        self.assertEqual([estimate.kind for estimate in estimates], ['viewer_cliff'])
        estimate = estimates[0]
        self.assertEqual(estimate.ts, BASE_TS + 60 * MINUTE)
        self.assertAlmostEqual(estimate.observed['drop_fraction'], 0.15, places=4)
        self.assertEqual(estimate.observed['viewers_before'], 1000)
        self.assertEqual(estimate.observed['viewers_after'], 850)
        self.assertEqual(estimate.observed['running_median'], 1000)
        self.assertEqual(estimate.observed['rebound_viewers'], 950)
        self.assertEqual(estimate.observed['rebound_minutes'], 8)
        self.assertIs(estimate.observed['proxy'], True)
        self.assertGreater(estimate.confidence, 0.0)
        self.assertLessEqual(estimate.confidence, 1.0)
        self.assertIn('не подтверждено', estimate.note)
        self.assertEqual(estimate.note_code, 'note_viewer_cliff')
        self.assertEqual(estimate.note_args['rebound_minutes'], 8)

    def test_cliff_threshold_is_table_driven(self):
        cases = [
            ('10% below threshold', 900, []),
            ('12% at threshold', 880, ['viewer_cliff']),
            ('30% well above', 700, ['viewer_cliff']),
        ]
        for label, dip, expected in cases:
            with self.subTest(case=label):
                points = cliff_series(dip=dip)
                self.assertEqual([estimate.kind for estimate in ad_break_estimates(points)], expected)

    def test_drop_without_rebound_is_not_a_cliff(self):
        viewers, chatters = flat(120, 1000, 100)
        for minute in range(60, 120):
            viewers[minute] = 700
        self.assertEqual(ad_break_estimates(timeline(viewers, chatters)), [])

    def test_compare_returns_both_windows_with_real_numbers(self):
        points = cliff_series()
        estimates = ad_break_estimates(points)

        result = compare_ad_vs_nonad(points, estimates)

        self.assertTrue(result['available'])
        self.assertEqual(result['reason'], '')
        self.assertEqual(len(result['breaks']), 1)
        self.assertEqual(result['breaks'][0]['kind'], 'viewer_cliff')
        self.assertIsInstance(result['breaks'][0]['ts'], str)
        self.assertEqual(result['ad_window']['minutes'], 21)
        self.assertEqual(result['rest_window']['minutes'], 99)
        self.assertEqual(result['ad_window']['points'], 21)
        self.assertEqual(result['rest_window']['points'], 99)
        self.assertAlmostEqual(result['ad_window']['viewer_growth_ratio'], 1.0, places=4)
        self.assertAlmostEqual(result['rest_window']['viewer_growth_ratio'], 1.0, places=4)
        self.assertAlmostEqual(result['ad_window']['chat_ratio_median'], 0.1, places=6)
        self.assertAlmostEqual(result['ad_window']['chat_ratio_median'], result['rest_window']['chat_ratio_median'])
        self.assertIsNone(result['ad_window']['followers_per_hour'])
        self.assertAlmostEqual(result['growth_ratio'], 1.0, places=4)
        self.assertEqual(result['verdict'], 'organic')
        self.assertIsNone(result['finding'])
        self.assertIn('прокси', result['note'].lower())


class NoSignalTests(unittest.TestCase):
    def test_smooth_series_reports_no_break_and_says_so_explicitly(self):
        viewers, chatters = flat(120, 800, 80)
        points = timeline(viewers, chatters)

        breaks = ad_break_estimates(points)
        result = compare_ad_vs_nonad(points, breaks)

        self.assertEqual(breaks, [])
        self.assertFalse(result['available'])
        self.assertEqual(result['breaks'], [])
        self.assertTrue(result['reason'])
        self.assertIn('не доказано', result['reason'])
        self.assertIsNone(result['growth_ratio'])
        self.assertEqual(result['verdict'], 'inconclusive')
        self.assertIsNone(result['finding'])
        self.assertEqual(result['ad_window']['minutes'], 0)
        self.assertEqual(result['rest_window']['minutes'], 0)
        self.assertIsNone(result['ad_window']['viewer_growth_ratio'])

    def test_empty_timeline_is_safe(self):
        breaks = ad_break_estimates([])
        result = compare_ad_vs_nonad([], breaks)

        self.assertEqual(breaks, [])
        self.assertFalse(result['available'])
        self.assertIn('не обнаружены', result['reason'])

    def test_compare_without_breaks_argument_reports_unavailable(self):
        points = cliff_series()
        result = compare_ad_vs_nonad(points, None)

        self.assertFalse(result['available'])
        self.assertEqual(result['breaks'], [])
        self.assertIn('не обнаружены', result['reason'])


class ChatterDipTests(unittest.TestCase):
    def test_proportional_drop_fires_while_ratio_stays_flat(self):
        viewers, _ = flat(120, 1000, 100)
        chatters = [100] * 60 + [80] * 60
        for minute in range(60, 120):
            viewers[minute] = 800

        estimates = ad_break_estimates(timeline(viewers, chatters))

        self.assertEqual([estimate.kind for estimate in estimates], ['chatter_dip'])
        observed = estimates[0].observed
        self.assertEqual(observed['viewers_before'], 1000)
        self.assertEqual(observed['viewers_after'], 800)
        self.assertEqual(observed['chatters_before'], 100)
        self.assertEqual(observed['chatters_after'], 80)
        self.assertAlmostEqual(observed['chat_ratio_before'], 0.1, places=6)
        self.assertAlmostEqual(observed['chat_ratio_after'], 0.1, places=6)

    def test_viewers_leaving_alone_does_not_fire(self):
        # Chat stays flat while viewers collapse: interest/technical drop, not a shared cause.
        viewers, chatters = flat(120, 1000, 100)
        for minute in range(60, 120):
            viewers[minute] = 700

        estimates = ad_break_estimates(timeline(viewers, chatters))

        self.assertEqual(estimates, [])


class SampleDrivenTests(unittest.TestCase):
    def test_title_change_is_detected_from_samples(self):
        viewers, chatters = flat(120, 900, 90)
        samples = [
            {'observed_at': BASE_TS, 'title': 'Chill stream', 'game': 'Just Chatting'},
            {'observed_at': BASE_TS + 20 * MINUTE, 'title': 'Chill stream', 'game': 'Just Chatting'},
            {'observed_at': BASE_TS + 35 * MINUTE, 'title': 'Ranked grind', 'game': 'Just Chatting'},
        ]

        estimates = ad_break_estimates(timeline(viewers, chatters), samples=samples)

        self.assertEqual([estimate.kind for estimate in estimates], ['title_change'])
        estimate = estimates[0]
        self.assertEqual(estimate.ts, BASE_TS + 35 * MINUTE)
        self.assertEqual(estimate.observed['previous_title'], 'Chill stream')
        self.assertEqual(estimate.observed['title'], 'Ranked grind')
        self.assertEqual(estimate.observed['minutes_into_stream'], 35.0)
        self.assertIs(estimate.observed['proxy'], True)
        self.assertEqual(estimate.note_code, 'note_title_change')
        self.assertEqual(estimate.note_args['current'], 'Ranked grind')

    def test_game_change_is_detected_from_samples(self):
        viewers, chatters = flat(60, 900, 90)
        samples = [
            {'observed_at': BASE_TS, 'game': 'Just Chatting', 'title': 'Same'},
            {'observed_at': BASE_TS + 10 * MINUTE, 'game': 'Escape from Tarkov', 'title': 'Same'},
        ]

        estimates = ad_break_estimates(timeline(viewers, chatters), samples=samples)

        self.assertEqual([estimate.kind for estimate in estimates], ['game_change'])
        self.assertEqual(estimates[0].observed['previous_game'], 'Just Chatting')
        self.assertEqual(estimates[0].observed['game'], 'Escape from Tarkov')

    def test_raid_influx_needs_a_slow_rise_plus_a_follower_jump(self):
        viewers = [1000] * 11 + [1000 + 10 * step for step in range(1, 21)] + [1200] * 29
        chatters = [100] * len(viewers)
        samples = [
            {'observed_at': BASE_TS + 8 * MINUTE, 'followers_count': 5000},
            {'observed_at': BASE_TS + 31 * MINUTE, 'followers_count': 5080},
        ]

        estimates = ad_break_estimates(timeline(viewers, chatters), samples=samples)

        self.assertEqual([estimate.kind for estimate in estimates], ['raid_influx'])
        observed = estimates[0].observed
        self.assertEqual(observed['viewers_start'], 1000)
        self.assertEqual(observed['viewers_end'], 1200)
        self.assertAlmostEqual(observed['rise_fraction'], 0.2, places=4)
        self.assertEqual(observed['followers_delta'], 80)
        self.assertLessEqual(observed['minutes'], RAID_WINDOW_MINUTES[1])
        self.assertGreaterEqual(observed['minutes'], RAID_WINDOW_MINUTES[0])
        self.assertLess(observed['max_step_share'], 0.5)
        self.assertIn('не подтверждено', estimates[0].note)

    def test_raid_influx_ignores_a_single_step_spike(self):
        viewers = [1000] * 20 + [1200] * 20
        samples = [
            {'observed_at': BASE_TS + 19 * MINUTE, 'followers_count': 5000},
            {'observed_at': BASE_TS + 21 * MINUTE, 'followers_count': 5080},
        ]

        estimates = ad_break_estimates(timeline(viewers, [100] * 40), samples=samples)

        self.assertEqual(estimates, [])


class MergeTests(unittest.TestCase):
    def test_nearby_kinds_fold_into_one_combined_estimate(self):
        for offset in (0, 3):
            with self.subTest(offset_minutes=offset):
                samples = [
                    {'observed_at': BASE_TS + (59 + offset) * MINUTE, 'title': 'Старый заголовок'},
                    {'observed_at': BASE_TS + (60 + offset) * MINUTE, 'title': 'Новый заголовок'},
                ]

                estimates = ad_break_estimates(cliff_series(), samples=samples)

                self.assertEqual(len(estimates), 1, estimates)
                estimate = estimates[0]
                self.assertEqual(estimate.kind, 'combined')
                self.assertEqual(estimate.observed['kinds'], ['title_change', 'viewer_cliff'])
                self.assertEqual(estimate.observed['component_count'], 2)
                self.assertEqual(estimate.observed['components'][0]['proxy'], True)
                self.assertIs(estimate.observed['proxy'], True)
                self.assertEqual(estimate.note_code, 'note_combined')
                # The merged estimate keeps the strongest component's confidence,
                # i.e. the cliff (0.5+), not the weaker title change (0.5).
                self.assertGreater(estimate.confidence, 0.5)

    def test_kinds_beyond_the_merge_window_stay_separate(self):
        samples = [
            {'observed_at': BASE_TS + 59 * MINUTE, 'title': 'Старый заголовок'},
            {'observed_at': BASE_TS + 64 * MINUTE, 'title': 'Новый заголовок'},
        ]

        estimates = ad_break_estimates(cliff_series(), samples=samples)

        self.assertEqual([estimate.kind for estimate in estimates], ['viewer_cliff', 'title_change'])


class AdDrivenGrowthTests(unittest.TestCase):
    @staticmethod
    def ad_driven_series():
        """Flat around a break, then online doubles inside the +/-10 min ad window."""
        viewers = [1000] * 120
        viewers[50] = 700
        for offset in range(1, 11):
            viewers[50 + offset] = 700 + 130 * offset
        for offset in range(1, 21):
            viewers[60 + offset] = 2000 - 50 * offset
        return timeline(viewers, [100] * 120)

    @staticmethod
    def constant_follower_samples():
        return sample_rows(range(0, 120, 10), title='Same', game='Same', followers_count=5000)

    def test_growth_concentrated_in_the_ad_window_fires_the_finding(self):
        points = self.ad_driven_series()

        estimates = ad_break_estimates(points, samples=self.constant_follower_samples())
        result = compare_ad_vs_nonad(points, estimates, samples=self.constant_follower_samples())

        self.assertEqual([estimate.kind for estimate in estimates], ['viewer_cliff'])
        self.assertTrue(result['available'])
        self.assertEqual(result['verdict'], 'ad_driven')
        self.assertAlmostEqual(result['ad_window']['viewer_growth_ratio'], 2.0, places=4)
        self.assertAlmostEqual(result['rest_window']['viewer_growth_ratio'], 1.0, places=4)
        self.assertAlmostEqual(result['growth_ratio'], 2.0, places=4)
        self.assertEqual(result['ad_window']['followers_per_hour'], 0.0)
        self.assertEqual(result['rest_window']['followers_per_hour'], 0.0)

        finding = result['finding']
        self.assertIsNotNone(finding)
        self.assertEqual(finding.code, 'ad_driven_growth')
        self.assertEqual(finding.weight, WEIGHTS['ad_driven_growth'])
        self.assertEqual(finding.weight, 0.08)
        self.assertEqual(finding.note_code, 'note_ad_driven_growth')
        self.assertGreater(finding.score, 0.0)
        self.assertLessEqual(finding.score, 1.0)
        self.assertEqual(finding.observed['breaks'], 1)
        self.assertAlmostEqual(finding.observed['ad_growth_ratio'], 2.0, places=4)
        self.assertAlmostEqual(finding.observed['rest_growth_ratio'], 1.0, places=4)
        self.assertAlmostEqual(finding.observed['growth_ratio'], 2.0, places=4)
        self.assertEqual(finding.observed['ad_minutes'], 21)
        self.assertEqual(finding.observed['rest_minutes'], 99)
        self.assertEqual(finding.note_args['growth_ratio'], '×2.00')
        self.assertIn('прокси', finding.note.lower())

    def test_no_finding_when_the_ad_side_does_not_outgrow_the_rest(self):
        points = cliff_series()
        estimates = ad_break_estimates(points)

        result = compare_ad_vs_nonad(points, estimates)

        self.assertEqual(result['verdict'], 'organic')
        self.assertIsNone(result['finding'])

    def test_round_tripped_break_dicts_are_accepted(self):
        points = cliff_series()
        estimates = ad_break_estimates(points)

        result = compare_ad_vs_nonad(points, [estimate.to_dict() for estimate in estimates])

        self.assertTrue(result['available'])
        self.assertEqual(result['ad_window']['minutes'], 21)


if __name__ == '__main__':
    unittest.main()
