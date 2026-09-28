"""Проверка ``app.detect.series``: развёртка серии в поминутный таймлайн и статистика.

Развёртка обязана быть ступенчатой функцией: значение строки держится весь её
интервал (``last_seen_at``/``repeat_count``), короткие пропуски (< ``max_gap_minutes``)
дотягиваются последним наблюдением, а длинные становятся ``None`` и никогда не
интерполируются. Модуль чистый: только stdlib и ``app.detect.series``/``types``.

Запуск: python -m pytest -q tests/test_detect_series.py
"""
from __future__ import annotations

import datetime as dt
import unittest
from types import SimpleNamespace

from app.detect import series
from app.detect.series import Point, deltas, expand_series, live_points, mad, median, quantile, values

# Каденс поллера: одна поминутная точка на итерацию.
POLL_SECONDS = getattr(series, "DEFAULT_POLL_SECONDS", None) or getattr(series, "POLL_SECONDS", 60.0)

T0 = dt.datetime(2026, 9, 28, 10, 0, 0)


def ts(minutes: float) -> dt.datetime:
    """Naive-UTC точка на ``minutes`` минут позже ``T0``."""
    return T0 + dt.timedelta(minutes=minutes)


def row(observed_at, viewers=100, chatters=10, **overrides) -> dict:
    """Строка в форме ``Sample`` (dict-путь чтения атрибутов)."""
    data = {"observed_at": observed_at, "viewers": viewers, "chatters": chatters, "is_live": True}
    data.update(overrides)
    return data


def timeline(*rows, **kwargs) -> list[Point]:
    return expand_series(list(rows), **kwargs)


class ExpandSeriesSpanTests(unittest.TestCase):
    """Строка держится весь свой интервал, включительно на обоих концах."""

    def test_last_seen_at_covers_five_minutes(self):
        points = timeline(row(T0, 250, 25, last_seen_at=ts(5)))
        self.assertEqual([point.ts for point in points], [ts(i) for i in range(6)])
        self.assertEqual(values(points), [250.0] * 6)
        self.assertEqual([point.chatters for point in points], [25] * 6)

    def test_repeat_count_extends_span_over_polls(self):
        points = timeline(row(T0, 250, 25, repeat_count=5))
        self.assertEqual(len(points), 6)
        self.assertEqual([point.ts for point in points], [ts(i) for i in range(6)])
        self.assertEqual(values(points), [250.0] * 6)

    def test_interval_seconds_ignored_so_poller_outages_do_not_become_plateaus(self):
        """A long `interval_seconds` means the poller was DOWN, not that the
        value held. The poller writes `interval_seconds` as the time since the
        previous *changed* row, so it includes every second of an outage. On
        the live database a 21 h outage produced a fake 1277 min plateau and
        fired plateau_lock/flatline against an honest channel, so the span must
        come from `repeat_count` alone.
        """
        points = timeline(row(T0, 40, 4, interval_seconds=300))
        # repeat_count defaults to 1 -> one poll interval -> 2 minute marks.
        self.assertEqual([point.ts for point in points], [ts(0), ts(1)])
        self.assertEqual(values(points), [40.0] * 2)
        self.assertEqual([point.chatters for point in points], [4] * 2)

    def test_outage_then_gap_becomes_none_not_carried_forward(self):
        """A 21 h `interval_seconds` must not smear the old value over the gap."""
        old = row(T0, 40, 4, interval_seconds=76_649.0)
        new = row(T0 + dt.timedelta(hours=21), 90, 9)
        points = expand_series([old, new])
        held = [p for p in points if p.viewers == 40]
        # The old value may only be held for its own poll plus the bounded
        # carry-forward window (max_gap_minutes), never across the 21 h outage.
        max_gap = getattr(series, "DEFAULT_MAX_GAP_MINUTES", 15.0)
        limit = POLL_SECONDS + max_gap * 60 + 60
        self.assertLess(
            (held[-1].ts - T0).total_seconds(),
            limit,
            "old value must not be held across the outage",
        )
        self.assertGreater(len(held), 0)
        self.assertTrue(any(p.viewers is None for p in points), "the outage must appear as a gap")
        self.assertEqual([p.viewers for p in points if p.viewers == 90], [90, 90])

    def test_outage_interval_is_not_the_hold_duration(self):
        """`interval_seconds` is time since the previous CHANGED row, so a
        large value is a poller outage, not a long-stable value. It must never
        extend a sample's span."""
        points = expand_series([row(T0, 40, 4, interval_seconds=76_649.0, last_seen_at=T0)])
        self.assertEqual([p.viewers for p in points if p.viewers is not None], [40, 40])

    def test_repeat_count_scales_with_poll_interval(self):
        points = timeline(row(T0, 7, 1, repeat_count=3))
        end = T0 + dt.timedelta(seconds=POLL_SECONDS * 3)
        self.assertEqual(len(points), 4)
        self.assertEqual(points[0].ts, T0)
        self.assertEqual(points[-1].ts, end)

    def test_last_seen_at_wins_over_repeat_count(self):
        points = timeline(row(T0, 5, 1, last_seen_at=ts(2), repeat_count=10))
        self.assertEqual([point.ts for point in points], [T0, ts(1), ts(2)])
        self.assertEqual(values(points), [5.0, 5.0, 5.0])


class GapHandlingTests(unittest.TestCase):
    """Пропуск < лимита дотягивается, пропуск > лимита становится ``None``."""

    CASES = (
        # (метка, смещение второй строки, дотянутых минут, минут без данных)
        ("short_gap_9min", 10, 8, 0),
        ("gap_exactly_at_limit_15min", 16, 14, 0),
        ("long_gap_19min", 20, 15, 3),
    )

    def test_gap_table(self):
        for label, offset, carried, missing in self.CASES:
            with self.subTest(case=label):
                points = timeline(
                    row(T0, 100, 10, last_seen_at=ts(1)),
                    row(ts(offset), 200, 20, last_seen_at=ts(offset + 1)),
                )
                expected_hold = 2 + carried
                self.assertEqual(len(points), offset + 2)
                self.assertEqual([point.ts for point in points], [ts(i) for i in range(offset + 2)])
                self.assertEqual(values(points), [100.0] * expected_hold + [200.0] * 2)
                self.assertEqual(
                    [point.chatters for point in points],
                    [10] * expected_hold + [None] * missing + [20] * 2,
                )
                self.assertEqual(sum(1 for point in points if point.viewers is None), missing)

    def test_long_gap_minutes_are_exactly_the_dropped_window(self):
        points = timeline(
            row(T0, 100, 10, last_seen_at=ts(1)),
            row(ts(20), 200, 20, last_seen_at=ts(21)),
        )
        blank = [point.ts for point in points if point.viewers is None]
        self.assertEqual(blank, [ts(17), ts(18), ts(19)])
        # Дотянутое наблюдение заканчивается ровно на границе max_gap_minutes.
        self.assertEqual(points[1].viewers, 100)
        self.assertEqual(points[16].ts, ts(16))
        self.assertEqual(points[16].viewers, 100)
        self.assertEqual(points[17].viewers, None)

    def test_long_gap_excluded_from_values_and_never_interpolated(self):
        points = timeline(
            row(T0, 100, 10, last_seen_at=ts(1)),
            row(ts(20), 200, 20, last_seen_at=ts(21)),
        )
        self.assertEqual(values(points), [100.0] * 17 + [200.0] * 2)
        self.assertEqual(values(points, "chatters"), [10.0] * 17 + [20.0] * 2)
        self.assertEqual(len(live_points(points)), 19)
        self.assertNotIn(150.0, values(points))
        self.assertEqual(set(values(points)), {100.0, 200.0})

    def test_carry_forward_can_be_disabled(self):
        points = timeline(
            row(T0, 100, 10, last_seen_at=ts(1)),
            row(ts(10), 200, 20, last_seen_at=ts(11)),
            carry_forward=False,
        )
        self.assertEqual(values(points), [100.0, 100.0, 200.0, 200.0])
        self.assertEqual([point.ts for point in points if point.viewers is None], [ts(i) for i in range(2, 10)])


class OfflineTests(unittest.TestCase):
    """Строки офлайна не несут данных: ``viewers=None``, ``chatters=None``."""

    def test_offline_span_is_empty(self):
        points = timeline(row(T0, 500, 50, is_live=False, last_seen_at=ts(5)))
        self.assertEqual([point.ts for point in points], [ts(i) for i in range(6)])
        self.assertEqual([point.viewers for point in points], [None] * 6)
        self.assertEqual([point.chatters for point in points], [None] * 6)
        self.assertEqual(values(points), [])
        self.assertEqual(live_points(points), [])
        self.assertFalse(any(point.has_data for point in points))

    def test_offline_row_between_live_rows_blanks_its_span(self):
        points = timeline(
            row(T0, 100, 10, last_seen_at=ts(1)),
            row(ts(2), 999, 99, is_live=False, last_seen_at=ts(5)),
            row(ts(20), 200, 20, last_seen_at=ts(21)),
        )
        self.assertEqual([point.viewers for point in points[:6]], [100, 100, None, None, None, None])
        self.assertNotIn(999.0, values(points))
        self.assertEqual(values(points), [100.0, 100.0, 200.0, 200.0])

    def test_viewer_count_aliases_are_read(self):
        points = timeline({"observed_at": T0, "viewer_count": 8, "chatters_count": 2, "last_seen_at": ts(1)})
        self.assertEqual(values(points), [8.0, 8.0])
        self.assertEqual(values(points, "chatters"), [2.0, 2.0])


class OrderingAndInputTests(unittest.TestCase):
    """Порядок строк не важен, дубликаты и перекрытия не ломают таймлайн."""

    def test_empty_input(self):
        self.assertEqual(expand_series([]), [])

    def test_unsorted_input_is_sorted(self):
        early = row(T0, 100, 10, last_seen_at=ts(1))
        late = row(ts(3), 300, 30, last_seen_at=ts(4))
        points = timeline(late, early)
        self.assertEqual([point.ts for point in points], [ts(i) for i in range(5)])
        self.assertEqual(values(points), [100.0, 100.0, 100.0, 300.0, 300.0])
        self.assertEqual(points, timeline(early, late))
        self.assertEqual([point.ts for point in points], sorted(point.ts for point in points))
        self.assertTrue(all(point.ts.tzinfo is None for point in points))

    def test_duplicate_rows_do_not_change_the_timeline(self):
        single = row(T0, 100, 10, last_seen_at=ts(2))
        self.assertEqual(timeline(single, single), timeline(single))

    def test_overlapping_spans_first_row_wins_until_it_ends(self):
        points = timeline(
            row(T0, 100, 10, last_seen_at=ts(4)),
            row(ts(2), 200, 20, last_seen_at=ts(6)),
        )
        self.assertEqual([point.ts for point in points], [ts(i) for i in range(7)])
        self.assertEqual(values(points), [100.0] * 5 + [200.0] * 2)

    def test_sample_like_objects_expand_like_dicts(self):
        obj = SimpleNamespace(observed_at=T0, viewers=120, chatters=12, last_seen_at=ts(2))
        self.assertEqual(expand_series([obj]), timeline(row(T0, 120, 12, last_seen_at=ts(2))))

    def test_rows_without_observed_at_are_skipped(self):
        self.assertEqual(expand_series([{"viewers": 100}]), [])


class StatisticsTests(unittest.TestCase):
    """median/mad/quantile на посчитанных руками данных плюс None для пустого входа."""

    MEDLINE = (
        ([1, 2, 3, 4], 2.5),
        ([1, 2, 3], 2.0),
        ([10, 2, 8, 4], 6.0),
        ([5], 5.0),
        ([1, None, 3], 2.0),
        ([-4, -1, -9], -4.0),
        ([], None),
    )

    def test_median_table(self):
        for numbers, expected in self.MEDLINE:
            with self.subTest(numbers=numbers):
                self.assertEqual(median(numbers), expected)

    MADLINE = (
        # (вход, центр, ожидание) — центр None = вокруг медианы
        ([1, 2, 3, 4], None, 1.0),
        ([1, 2, 3, 4], 2.0, 1.0),
        ([5, 7, 9], None, 2.0),
        ([5, 7, 9], 8.0, 1.0),
        ([1, 1, 1], None, 0.0),
        ([1, None, 3], None, 1.0),
        ([], None, None),
        ([], 3.0, None),
    )

    def test_mad_table(self):
        for numbers, centre, expected in self.MADLINE:
            with self.subTest(numbers=numbers, centre=centre):
                self.assertEqual(mad(numbers, centre), expected)

    QUANTILE = (
        ([10, 20, 30, 40], 0.0, 10.0),
        ([10, 20, 30, 40], 0.25, 17.5),
        ([10, 20, 30, 40], 0.5, 25.0),
        ([10, 20, 30, 40], 0.75, 32.5),
        ([10, 20, 30, 40], 1.0, 40.0),
        ([10, 20, 30, 40], -1.0, 10.0),
        ([10, 20, 30, 40], 2.0, 40.0),
        ([5, None], 0.5, 5.0),
        ([], 0.5, None),
    )

    def test_quantile_table(self):
        for numbers, q, expected in self.QUANTILE:
            with self.subTest(numbers=numbers, q=q):
                self.assertEqual(quantile(numbers, q), expected)

    def test_median_is_not_the_mean(self):
        self.assertEqual(median([0, 0, 0, 1000]), 0.0)
        self.assertEqual(quantile([0, 0, 0, 1000], 0.5), 0.0)


class DerivativesTests(unittest.TestCase):
    """deltas/live_points/values — базовая семантика."""

    def test_deltas(self):
        for numbers, expected in (
            ([1, 3, 6], [2, 3]),
            ([10, 10, 9.5], [0.0, -0.5]),
            ([5], []),
            ([], []),
        ):
            with self.subTest(numbers=numbers):
                self.assertEqual(deltas(numbers), expected)

    def test_live_points_and_values_skip_blanks(self):
        blanks = Point(ts=ts(1), viewers=None, chatters=None)
        filled = Point(ts=ts(2), viewers=42, chatters=7)
        self.assertFalse(blanks.has_data)
        self.assertTrue(filled.has_data)
        self.assertEqual(live_points([blanks, filled]), [filled])
        self.assertEqual(values([blanks, filled]), [42.0])
        self.assertEqual(values([blanks, filled], "chatters"), [7.0])


if __name__ == "__main__":
    unittest.main()
