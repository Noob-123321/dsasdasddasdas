"""Expand change-aware ``Sample`` rows into a uniform per-minute timeline.

The poller stores one row per *change*: an unchanged (viewers, chatters) pair
extends ``last_seen_at``/``repeat_count`` instead of writing a new row. Measured
on the live database, 59-63% of consecutive rows are therefore identical, which
means any flatness/volatility statistic computed on raw rows measures the poller,
not the channel. Every remaining detector consumes the output of
:func:`expand_series` for exactly that reason.

The expansion is a step function: the value of a row is held for the whole span
it covers. Short gaps (poller hiccups, up to ``max_gap_minutes``) keep the last
observed value; longer gaps become ``None`` and are excluded from statistics --
never interpolated across.
"""
from __future__ import annotations

import datetime as dt
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

DEFAULT_POLL_SECONDS = 60.0
DEFAULT_MAX_GAP_MINUTES = 15.0


@dataclass(frozen=True)
class Point:
    """One minute of the reconstructed timeline. ``viewers is None`` = no data."""

    ts: dt.datetime
    viewers: int | None
    chatters: int | None

    @property
    def has_data(self) -> bool:
        return self.viewers is not None


def _attr(row: object, name: str, default=None):
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _floor_minute(moment: dt.datetime, minute_seconds: float) -> dt.datetime:
    if minute_seconds == 60:
        return moment.replace(second=0, microsecond=0)
    epoch = dt.datetime(1970, 1, 1)
    step = dt.timedelta(seconds=minute_seconds)
    return epoch + step * math.floor((moment - epoch) / step)


def expand_series(
    samples: Iterable[object],
    *,
    max_gap_minutes: float = DEFAULT_MAX_GAP_MINUTES,
    minute_seconds: float = 60.0,
    carry_forward: bool = True,
) -> list[Point]:
    """Rebuild a per-minute timeline from samples.

    ``samples`` may be ``Sample`` rows or dicts with ``observed_at``,
    ``last_seen_at``, ``repeat_count``, ``interval_seconds``, ``is_live``,
    ``viewer_count``/``viewers``, ``chatters_count``/``chatters``.
    """
    rows = []
    for row in samples:
        start = _attr(row, "observed_at")
        if start is None:
            continue
        viewers = _attr(row, "viewers", None)
        if viewers is None:
            viewers = _attr(row, "viewer_count", None)
        chatters = _attr(row, "chatters", None)
        if chatters is None:
            chatters = _attr(row, "chatters_count", None)
        if not _attr(row, "is_live", True):
            viewers = None
            chatters = None
        end = _attr(row, "last_seen_at", None) or start
        if end < start:
            end = start
        if end == start:
            # The poller only re-stamps `last_seen_at` while it is actually
            # observing, so `last_seen_at == observed_at` means "we saw this
            # value once and nothing since". The hold time is therefore
            # `repeat_count * poll_interval` -- NOT `interval_seconds`, which
            # the poller fills with the time since the previous *changed* row
            # and therefore includes every second the poller was down. Using
            # it turned a 21 h poller outage into a fake 1277 min flat
            # plateau and fired plateau_lock/flatline on an honest channel.
            repeat = _attr(row, "repeat_count", 1) or 1
            end = start + dt.timedelta(seconds=max(DEFAULT_POLL_SECONDS * float(repeat), 0.0))
        rows.append((start, end, viewers, chatters))
    if not rows:
        return []
    rows.sort(key=lambda item: item[0])

    step = dt.timedelta(seconds=minute_seconds)
    timeline_start = _floor_minute(rows[0][0], minute_seconds)
    timeline_end = _floor_minute(max(end for _, end, _, _ in rows), minute_seconds)
    gap = dt.timedelta(minutes=max_gap_minutes)

    points: list[Point] = []
    index = 0
    previous: tuple[int | None, int | None] | None = None
    previous_end: dt.datetime | None = None
    moment = timeline_start
    while moment <= timeline_end:
        while index < len(rows) and rows[index][1] < moment:
            # The row is fully in the past; remember it as the carry source.
            previous = (rows[index][2], rows[index][3])
            previous_end = rows[index][1]
            index += 1
        if index < len(rows) and rows[index][0] <= moment <= rows[index][1]:
            viewers, chatters = rows[index][2], rows[index][3]
        elif carry_forward and previous is not None and previous_end is not None and moment - previous_end <= gap:
            viewers, chatters = previous
        else:
            viewers, chatters = None, None
        points.append(Point(ts=moment, viewers=viewers, chatters=chatters))
        moment += step
    return points


def live_points(points: Sequence[Point]) -> list[Point]:
    """Points that carry an observed viewer count."""
    return [point for point in points if point.viewers is not None]


def values(points: Sequence[Point], field: str = "viewers") -> list[float]:
    """Numeric, non-null values of ``viewers``/``chatters`` in timeline order."""
    result = []
    for point in points:
        raw = getattr(point, field, None)
        if raw is not None:
            result.append(float(raw))
    return result


def deltas(numbers: Sequence[float]) -> list[float]:
    """Successive differences."""
    return [right - left for left, right in zip(numbers, numbers[1:])]


def median(numbers: Iterable[float]) -> float | None:
    """Median of the numeric values, ``None`` for an empty input."""
    data = sorted(float(value) for value in numbers if value is not None)
    if not data:
        return None
    middle = len(data) // 2
    if len(data) % 2:
        return data[middle]
    return (data[middle - 1] + data[middle]) / 2.0


def mad(numbers: Iterable[float], centre: float | None = None) -> float | None:
    """Median absolute deviation around ``centre`` (default: the median)."""
    data = [float(value) for value in numbers if value is not None]
    if not data:
        return None
    middle = median(data) if centre is None else float(centre)
    if middle is None:
        return None
    return median([abs(value - middle) for value in data])


def quantile(numbers: Iterable[float], q: float) -> float | None:
    """Linear-interpolated quantile, ``q`` in 0..1."""
    data = sorted(float(value) for value in numbers if value is not None)
    if not data:
        return None
    if q <= 0:
        return data[0]
    if q >= 1:
        return data[-1]
    position = q * (len(data) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return data[int(position)]
    weight = position - lower
    return data[lower] * (1 - weight) + data[upper] * weight
