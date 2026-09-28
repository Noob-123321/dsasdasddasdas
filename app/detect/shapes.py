"""Shape / flow detectors for the expanded per-minute viewer timeline (idea #9).

Every function here consumes the output of :func:`app.detect.series.expand_series`
-- a uniform per-minute step function -- never raw ``Sample`` rows. Raw rows are
change-aware (59-63% of consecutive rows are identical because the poller dedups),
so any flatness/volatility statistic computed on them measures the poller instead
of the channel (see ``docs/DETECTION_SPEC.md`` §2).

Emitted codes and weights (:data:`WEIGHTS`):

``flatline`` (0.14)
    The viewer count does not move at all. Detection is the *maximal* contiguous
    window of live minutes with ``viewers >= 20`` in which at most 1% of the
    minute-to-minute deltas are non-zero.

    The spec phrases this as "the fraction of zero-delta minutes is < 1 %"; taken
    literally that would fire on *noisy* channels (which change every minute) and
    never on a flat one, i.e. the exact opposite of the signal's name and of the
    required behaviour ("a synthetic perfectly flat 60-minute series fires
    flatline"). We implement the only self-consistent reading: **at most** 1% of
    the deltas inside the window may be non-zero.

``suspicious_smoothness`` (0.10)
    Second differences are ~0: the curve is piecewise linear, no jitter. When the
    channel's own earlier series are available the current median ``|d2|`` must
    additionally be at most half of the history's, otherwise the shape is simply
    what this channel always does. ``threshold`` is 0.5% of the window median.

``low_entropy`` (0.08)
    Shannon entropy of the viewer count rounded to the nearest 10, normalised by
    ``log2(distinct buckets)``. Fires on ``normalised <= 0.25`` (>= 30 live
    minutes, >= 5 buckets) or when one bucket covers >= 90% of the minutes.

``time_of_day_independence`` (0.06)
    Hourly mean viewers are uncorrelated with the diurnal curve built from the
    channel's other streams (>= 1 other series, >= 3 shared hours). Also fires
    when the correlation is undefined because the current stream is flat across
    hours while history is not.

``instant_restore`` (0.06)
    A data gap > 2 minutes *inside one expanded series* (stream ended and
    restarted) after which viewers come back to within 2% of the pre-gap value in
    the very next live sample.

``curve_similarity`` / ``repeat_shape_hints`` are the helpers the spike detector
consumes for ``repeat_shape``: min-max normalised curves compared with Pearson
correlation and max absolute delta.
"""
from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence

from app.detect.series import Point, deltas, median, values
from app.detect.types import Finding, clamp, scale

WEIGHTS: dict[str, float] = {
    "flatline": 0.14,
    "suspicious_smoothness": 0.10,
    "low_entropy": 0.08,
    "time_of_day_independence": 0.06,
    "instant_restore": 0.06,
}

Series = Sequence[Point]

MIN_VIEWERS = 20
MIN_WINDOW_MINUTES = 30
ZERO_DELTA_SHARE = 0.99
NOISE_FLOOR_SHARE = 0.005
SMOOTH_SHARE = 0.95
ENTROPY_ROUNDING = 10
MIN_BUCKETS = 5
LOW_ENTROPY_NORMALISED = 0.25
DOMINANT_SHARE = 0.90
CORRELATION_CEILING = 0.2
RESTORE_TOLERANCE = 0.02
RESTORE_MIN_GAP_MINUTES = 2.0
MIN_SHARED_HOURS = 3
REPEAT_CORRELATION = 0.995
REPEAT_MAX_DELTA = 0.02
MAX_CURVE_POINTS = 240

_MISSING = "-"


# --------------------------------------------------------------------------- #
# small shared helpers
# --------------------------------------------------------------------------- #

def _live_runs(points: Series, min_viewers: int | None = None) -> list[list[Point]]:
    """Maximal contiguous runs of minutes that carry an observed viewer count.

    ``None`` viewers (a real data gap) always break a run, so statistics never
    stitch two separate live runs together.
    """
    runs: list[list[Point]] = []
    current: list[Point] = []
    for point in points:
        value = point.viewers
        if value is None or (min_viewers is not None and value < min_viewers):
            if current:
                runs.append(current)
                current = []
            continue
        current.append(point)
    if current:
        runs.append(current)
    return runs


def _longest_run(runs: Sequence[list[Point]]) -> list[Point]:
    if not runs:
        return []
    return max(runs, key=len)


def _longest_equal_streak(run: Sequence[Point]) -> list[Point]:
    """The longest slice of consecutive equal viewer counts inside ``run``."""
    if not run:
        return []
    best = list(run[:1])
    start = 0
    for index in range(1, len(run)):
        if run[index].viewers != run[index - 1].viewers:
            start = index
        elif index - start + 1 > len(best):
            best = list(run[start:index + 1])
    return best


def _second_differences(numbers: Sequence[float]) -> list[float]:
    return deltas(deltas(numbers))


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    """Sample Pearson correlation, ``None`` when undefined (constant input)."""
    if len(left) != len(right) or len(left) < 2:
        return None
    count = len(left)
    mean_left = sum(left) / count
    mean_right = sum(right) / count
    covariance = 0.0
    variance_left = 0.0
    variance_right = 0.0
    for a_value, b_value in zip(left, right):
        delta_left = a_value - mean_left
        delta_right = b_value - mean_right
        covariance += delta_left * delta_right
        variance_left += delta_left * delta_left
        variance_right += delta_right * delta_right
    if variance_left <= 0.0 or variance_right <= 0.0:
        return None
    return covariance / math.sqrt(variance_left * variance_right)


def _num(value: float | None, digits: int = 2) -> str:
    if value is None:
        return _MISSING
    return f"{value:.{digits}f}"


def _pct(fraction: float | None, digits: int = 1) -> str:
    if fraction is None:
        return _MISSING
    return f"{fraction * 100.0:.{digits}f}"


# --------------------------------------------------------------------------- #
# flatline
# --------------------------------------------------------------------------- #

def _flatline_finding(points: Series) -> Finding | None:
    best: tuple[list[Point], int, float] | None = None
    for run in _live_runs(points, min_viewers=MIN_VIEWERS):
        if len(run) < MIN_WINDOW_MINUTES:
            continue
        numbers = [float(point.viewers) for point in run]
        transitions = deltas(numbers)
        zero_minutes = sum(1 for value in transitions if value == 0.0)
        share = zero_minutes / len(transitions) if transitions else 0.0
        if share >= ZERO_DELTA_SHARE:
            candidate = (list(run), zero_minutes, share)
        else:
            core = _longest_equal_streak(run)
            if len(core) < MIN_WINDOW_MINUTES:
                continue
            candidate = (core, len(core) - 1, 1.0)
        if best is None or len(candidate[0]) > len(best[0]):
            best = candidate
    if best is None:
        return None

    window, zero_minutes, share = best
    window_minutes = len(window)
    centre = median([float(point.viewers) for point in window]) or 0.0
    viewers = int(round(centre))
    # scale(window, 30, 120) with a small floor so a fired signal never scores
    # exactly 0; a 30-minute flatline still scores lower than a 2-hour one.
    score = clamp(max(0.05, scale(float(window_minutes), float(MIN_WINDOW_MINUTES), 120.0)))
    observed = {
        "window_minutes": window_minutes,
        "zero_delta_minutes": zero_minutes,
        "zero_delta_fraction": round(share, 6),
        "viewers": viewers,
    }
    note = (
        f"Онлайн не менялся {window_minutes} мин подряд: {_pct(share)}% минут без изменений "
        f"при медиане {viewers} зрителей."
    )
    explanation = (
        f"Окно {window_minutes} мин, из них {zero_minutes} минут нулевого прироста. "
        "Считается по развёрнутой поминутной шкале, а не по сырым замерам."
    )
    return Finding(
        code="flatline",
        score=score,
        weight=WEIGHTS["flatline"],
        observed=observed,
        note=note,
        explanation=explanation,
        note_code="note_flatline",
        note_args={
            "window_minutes": window_minutes,
            "zero_delta_minutes": zero_minutes,
            "zero_delta_fraction": _pct(share),
            "viewers": viewers,
        },
    )


# --------------------------------------------------------------------------- #
# suspicious_smoothness
# --------------------------------------------------------------------------- #

def _smoothness_stats(points: Series) -> tuple[list[float], list[float]] | None:
    """``(values, second differences)`` of the largest ``viewers >= 20`` run."""
    run = _longest_run(_live_runs(points, min_viewers=MIN_VIEWERS))
    if len(run) < MIN_WINDOW_MINUTES:
        return None
    numbers = [float(point.viewers) for point in run]
    return numbers, _second_differences(numbers)


def _history_median_d2(history: Sequence[Series]) -> float | None:
    pooled: list[float] = []
    for series in history:
        stats = _smoothness_stats(series)
        if stats is not None:
            pooled.extend(abs(value) for value in stats[1])
    return median(pooled) if pooled else None


def _smoothness_finding(points: Series, history: Sequence[Series]) -> Finding | None:
    stats = _smoothness_stats(points)
    if stats is None:
        return None
    numbers, second = stats
    if not second:
        return None

    minutes = len(numbers)
    centre = median(numbers) or 0.0
    threshold = NOISE_FLOOR_SHARE * centre
    if threshold > 0.0:
        near_zero = sum(1 for value in second if abs(value) < threshold)
    else:
        near_zero = sum(1 for value in second if value == 0.0)
    near_zero_share = near_zero / len(second)
    median_d2 = median([abs(value) for value in second])
    if median_d2 is None:
        return None
    if near_zero_share < SMOOTH_SHARE:
        return None

    history_d2 = _history_median_d2(history)
    if history_d2 is not None and median_d2 > 0.5 * history_d2:
        return None

    score = clamp(0.5 + 0.5 * scale(near_zero_share, SMOOTH_SHARE, 1.0))
    observed = {
        "near_zero_share": round(near_zero_share, 6),
        "median_d2": round(median_d2, 6),
        "threshold": round(threshold, 6),
        "history_median_d2": None if history_d2 is None else round(history_d2, 6),
        "minutes": minutes,
    }
    note = (
        f"Кривая онлайна подозрительно гладкая: {_pct(near_zero_share)}% вторых разностей "
        f"ниже шума {threshold:.2f} на {minutes} минутах."
    )
    explanation = (
        "Почти линейная кривая без естественного дрожания. "
        "Сравнивается с собственными прошлыми трансляциями канала, когда они переданы."
    )
    return Finding(
        code="suspicious_smoothness",
        score=score,
        weight=WEIGHTS["suspicious_smoothness"],
        observed=observed,
        note=note,
        explanation=explanation,
        note_code="note_suspicious_smoothness",
        note_args={
            "near_zero_share": _pct(near_zero_share),
            "median_d2": _num(median_d2),
            "threshold": _num(threshold),
            "history_median_d2": _num(history_d2),
            "minutes": minutes,
        },
    )


# --------------------------------------------------------------------------- #
# low_entropy
# --------------------------------------------------------------------------- #

def shannon_entropy(values: Sequence[float]) -> float:
    """Shannon entropy in bits of ``values`` (0.0 for an empty input)."""
    numbers = [float(value) for value in values if value is not None]
    if not numbers:
        return 0.0
    counts = Counter(numbers)
    total = float(len(numbers))
    entropy = 0.0
    for count in counts.values():
        probability = count / total
        entropy -= probability * math.log2(probability)
    return entropy


def normalised_entropy(values: Sequence[float]) -> float | None:
    """Entropy divided by ``log2(distinct values)``; ``None`` when < 2 distinct."""
    numbers = [float(value) for value in values if value is not None]
    distinct = len(set(numbers))
    if distinct < 2:
        return None
    return shannon_entropy(numbers) / math.log2(distinct)


def _low_entropy_finding(points: Series) -> Finding | None:
    raw = values(points)
    minutes = len(raw)
    if minutes < MIN_WINDOW_MINUTES:
        return None

    buckets = [int(round(value / ENTROPY_ROUNDING)) * ENTROPY_ROUNDING for value in raw]
    counts = Counter(buckets)
    distinct = len(counts)
    dominant_share = max(counts.values()) / float(minutes)
    entropy_bits = shannon_entropy(buckets)
    normalised = normalised_entropy(buckets)

    scores: list[float] = []
    if distinct >= MIN_BUCKETS and normalised is not None and normalised <= LOW_ENTROPY_NORMALISED:
        scores.append(clamp(1.0 - normalised))
    if dominant_share >= DOMINANT_SHARE:
        scores.append(clamp(dominant_share))
    if not scores:
        return None

    score = max(scores)
    observed = {
        "entropy_bits": round(entropy_bits, 6),
        "normalised": None if normalised is None else round(normalised, 6),
        "buckets": distinct,
        "dominant_share": round(dominant_share, 6),
        "minutes": minutes,
    }
    note = (
        f"Значения онлайна почти не меняются: энтропия {entropy_bits:.2f} бит, "
        f"один уровень занимает {_pct(dominant_share)}% минут."
    )
    explanation = (
        "Энтропия Шеннона значений онлайна, округлённых до 10 зрителей. "
        "Живая аудитория «гуляет», накрутка стоит на одном значении."
    )
    return Finding(
        code="low_entropy",
        score=score,
        weight=WEIGHTS["low_entropy"],
        observed=observed,
        note=note,
        explanation=explanation,
        note_code="note_low_entropy",
        note_args={
            "entropy_bits": _num(entropy_bits),
            "normalised": _num(normalised),
            "buckets": distinct,
            "dominant_share": _pct(dominant_share),
            "minutes": minutes,
        },
    )


# --------------------------------------------------------------------------- #
# time_of_day_independence
# --------------------------------------------------------------------------- #

def _hourly_totals(points: Series) -> dict[int, tuple[float, int]]:
    totals: dict[int, tuple[float, int]] = {}
    for point in points:
        if point.viewers is None:
            continue
        hour = point.ts.hour
        total, count = totals.get(hour, (0.0, 0))
        totals[hour] = (total + float(point.viewers), count + 1)
    return totals


def _hourly_means(totals: dict[int, tuple[float, int]]) -> dict[int, float]:
    return {hour: total / count for hour, (total, count) in totals.items()}


def _merged_hourly_totals(series_list: Sequence[Series]) -> dict[int, tuple[float, int]]:
    merged: dict[int, tuple[float, int]] = {}
    for series in series_list:
        for hour, (total, count) in _hourly_totals(series).items():
            previous_total, previous_count = merged.get(hour, (0.0, 0))
            merged[hour] = (previous_total + total, previous_count + count)
    return merged


def _time_of_day_finding(points: Series, history: Sequence[Series]) -> Finding | None:
    if not history:
        return None
    current = _hourly_means(_hourly_totals(points))
    earlier = _hourly_means(_merged_hourly_totals(history))
    shared = sorted(set(current) & set(earlier))
    if len(shared) < MIN_SHARED_HOURS:
        return None

    current_values = [current[hour] for hour in shared]
    history_values = [earlier[hour] for hour in shared]
    correlation = _pearson(current_values, history_values)
    current_flat = max(current_values) - min(current_values) <= 1e-9
    history_flat = max(history_values) - min(history_values) <= 1e-9

    if correlation is None:
        if not (current_flat and not history_flat):
            return None
        score = 0.6
    elif correlation <= CORRELATION_CEILING:
        score = clamp(1.0 - max(correlation, 0.0))
    else:
        return None

    hours_compared = len(shared)
    observed = {
        "correlation": None if correlation is None else round(correlation, 6),
        "hours_compared": hours_compared,
        "current_hourly": {str(hour): round(current[hour], 2) for hour in shared},
        "history_hourly": {str(hour): round(earlier[hour], 2) for hour in shared},
    }
    correlation_text = "не определена" if correlation is None else f"{correlation:.2f}"
    note = (
        "Средний онлайн по часам не повторяет обычный суточный профиль канала: "
        f"корреляция {correlation_text} на {hours_compared} общих часах."
    )
    explanation = (
        "Сравниваются среднечасовые значения текущей трансляции и прошлых трансляций "
        "канала. Живая аудитория следует суточному ритму, накрутка — нет."
    )
    return Finding(
        code="time_of_day_independence",
        score=score,
        weight=WEIGHTS["time_of_day_independence"],
        observed=observed,
        note=note,
        explanation=explanation,
        note_code="note_time_of_day_independence",
        note_args={
            "correlation": _MISSING if correlation is None else _num(correlation),
            "hours_compared": hours_compared,
        },
    )


# --------------------------------------------------------------------------- #
# instant_restore
# --------------------------------------------------------------------------- #

def _instant_restore_finding(points: Series) -> Finding | None:
    runs = _live_runs(points)
    best: tuple[float, int, int, float] | None = None
    for left, right in zip(runs, runs[1:]):
        before = left[-1].viewers
        after = right[0].viewers
        if before is None or after is None or before <= 0:
            continue
        gap_minutes = (right[0].ts - left[-1].ts).total_seconds() / 60.0 - 1.0
        if gap_minutes <= RESTORE_MIN_GAP_MINUTES:
            continue
        delta_ratio = abs(after - before) / before
        if delta_ratio > RESTORE_TOLERANCE:
            continue
        if best is None or delta_ratio < best[0]:
            best = (delta_ratio, before, after, gap_minutes)
    if best is None:
        return None

    delta_ratio, before, after, gap_minutes = best
    score = clamp(0.5 + 0.5 * scale(RESTORE_TOLERANCE - delta_ratio, 0.0, RESTORE_TOLERANCE))
    observed = {
        "before_viewers": before,
        "after_viewers": after,
        "gap_minutes": round(gap_minutes, 3),
        "delta_ratio": round(delta_ratio, 6),
    }
    note = (
        f"Онлайн вернулся к прежнему значению после перезапуска: {before} → {after} зрителей "
        f"через {gap_minutes:.0f} мин разрыва."
    )
    explanation = (
        "Трансляция прервалась и возобновилась, а онлайн мгновенно вернулся к прежнему "
        "уровню — живая аудитория так себя не ведёт."
    )
    return Finding(
        code="instant_restore",
        score=score,
        weight=WEIGHTS["instant_restore"],
        observed=observed,
        note=note,
        explanation=explanation,
        note_code="note_instant_restore",
        note_args={
            "before_viewers": before,
            "after_viewers": after,
            "gap_minutes": _num(gap_minutes, 1),
            "delta_ratio": _pct(delta_ratio),
        },
    )


# --------------------------------------------------------------------------- #
# curve comparison helpers (consumed by the spike detector as repeat_shape)
# --------------------------------------------------------------------------- #

def _resample(numbers: Sequence[float], count: int) -> list[float]:
    """Linear index-resample ``numbers`` onto ``count`` points."""
    if count <= 0:
        return []
    if len(numbers) == count:
        return list(numbers)
    if len(numbers) == 1:
        return [numbers[0]] * count
    result: list[float] = []
    step = (len(numbers) - 1) / (count - 1)
    for index in range(count):
        position = index * step
        lower = int(math.floor(position))
        upper = min(lower + 1, len(numbers) - 1)
        weight = position - lower
        result.append(numbers[lower] * (1.0 - weight) + numbers[upper] * weight)
    return result


def _min_max(numbers: Sequence[float]) -> list[float]:
    if not numbers:
        return []
    low = min(numbers)
    high = max(numbers)
    if high <= low:
        return [0.0] * len(numbers)
    return [(value - low) / (high - low) for value in numbers]


def curve_similarity(series_a: Series, series_b: Series) -> dict:
    """Compare two expanded series on min-max normalised curves.

    Only minutes with an observed viewer count take part; both curves are
    index-resampled onto a common grid (at most :data:`MAX_CURVE_POINTS`) so
    streams of different lengths stay comparable.
    """
    left = values(series_a)
    right = values(series_b)
    count = min(len(left), len(right), MAX_CURVE_POINTS)
    if count < 2:
        return {"correlation": None, "max_abs_delta": None, "points": count}

    normalised_a = _min_max(_resample(left, count))
    normalised_b = _min_max(_resample(right, count))
    correlation = _pearson(normalised_a, normalised_b)
    max_abs_delta = max(abs(a_value - b_value) for a_value, b_value in zip(normalised_a, normalised_b))
    return {
        "correlation": None if correlation is None else round(correlation, 6),
        "max_abs_delta": round(max_abs_delta, 6),
        "points": count,
    }


def repeat_shape_hints(series_list: Sequence[Series]) -> list[dict]:
    """Pairs of the channel's own series whose normalised curves nearly coincide."""
    items = list(series_list)
    hints: list[dict] = []
    for first in range(len(items)):
        for second in range(first + 1, len(items)):
            result = curve_similarity(items[first], items[second])
            correlation = result["correlation"]
            max_abs_delta = result["max_abs_delta"]
            repeated = (correlation is not None and correlation >= REPEAT_CORRELATION) or (
                max_abs_delta is not None and max_abs_delta <= REPEAT_MAX_DELTA
            )
            if repeated:
                hints.append({"pair": [first, second], "correlation": correlation, "max_abs_delta": max_abs_delta})
    return hints


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #

def shape_findings(points: Series, *, history: Sequence[Series] | None = None) -> list[Finding]:
    """Run every shape detector over one expanded per-minute series.

    ``history`` holds earlier expanded series of the same channel (previous
    streams) and is used only by ``suspicious_smoothness`` and
    ``time_of_day_independence``.
    """
    series = list(points)
    earlier = [list(item) for item in (history or [])]

    findings: list[Finding] = []
    for detector in (
        lambda: _flatline_finding(series),
        lambda: _smoothness_finding(series, earlier),
        lambda: _low_entropy_finding(series),
        lambda: _time_of_day_finding(series, earlier),
        lambda: _instant_restore_finding(series),
    ):
        finding = detector()
        if finding is not None:
            findings.append(finding)
    return findings
