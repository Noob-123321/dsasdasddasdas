"""Spike, plateau, repeat-shape and staircase detectors (spec section 3.2).

Every function here consumes the EXPANDED per-minute timeline produced by
:func:`app.detect.series.expand_series`, never raw ``Sample`` rows: the poller
deduplicates unchanged values, so statistics over raw rows measure the poller
instead of the channel.

``detect_jumps`` is the corrected re-implementation of
``app/analytics.py::detect_spikes`` -- that function indexes its own rows as if
they were dicts (``values[start]`` / ``values[peak]``), which cannot work. The
deliberate differences from the legacy function are:

* the baseline is the median of the :data:`BASELINE_WINDOW_POINTS` expanded
  minutes *immediately preceding* the jump, not the median of the whole stream,
  so a long stream cannot dilute a late jump into invisibility;
* the threshold is ``max(baseline * min_amplitude, baseline + 3 * mad)`` computed
  on that same window (the legacy "median_mad" philosophy);
* a jump never bridges a real gap -- the baseline window and the elevated run
  both stay inside one contiguous block of observed minutes;
* ``started_ts`` is the last minute that was still at or below the threshold, so
  ``rise_seconds`` measures the real climb and a one-minute step reports
  ``rise_seconds == 60`` with ``is_instant == True``;
* ``points`` counts the consecutive elevated minutes of the jump itself.

``detect_jumps`` reports ``datetime`` objects (it is the Python-level helper);
:func:`spike_findings` renders every timestamp inside ``observed`` as an ISO
string so a ``Finding`` stays JSON-serialisable for the API.

``spike_findings`` adds the four spec rules on top of the jump scan:
``no_justification`` (0.22), ``plateau_lock`` (0.16), ``repeat_shape`` (0.14) and
``staircase_return`` (0.06).
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence

from app.detect.series import Point, live_points, mad, median
from app.detect.types import Finding, clamp, scale

WEIGHTS: dict[str, float] = {
    "no_justification": 0.22,
    "plateau_lock": 0.16,
    "repeat_shape": 0.14,
    "staircase_return": 0.06,
}

#: Size of the expanded minute timeline used for jump detection.
POLL_SECONDS = 60.0
#: Longer spacing than this inside the timeline means "not contiguous".
MAX_STEP_SECONDS = 90.0
#: How many expanded minutes before a jump form its baseline.
BASELINE_WINDOW_POINTS = 30
#: A plateau holds while every minute stays within this relative band of its anchor.
PLATEAU_TOLERANCE = 0.005
#: Minimum consecutive elevated minutes for ``plateau_lock``.
PLATEAU_MIN_MINUTES = 20
#: Two streams count as "the same curve" at/above this correlation ...
REPEAT_CORRELATION = 0.995
#: ... or at/below this maximum absolute difference of the normalised curves.
REPEAT_MAX_ABS_DELTA = 0.02
#: A collapse to <= this share of the pre-collapse median counts as "to ~0".
COLLAPSE_RATIO = 0.01
#: Jump amplitude at/above which an unexplained jump is reported.
NO_JUSTIFICATION_AMPLITUDE = 3.0
#: A jump is only "sudden" if the climb finishes within this many seconds.
#: The spec asks for a rise of "seconds or 1-2 minutes"; a real audience ramps
#: over tens of minutes. Measured on the live database: xqc climbed 918 ->
#: 28056 viewers (x30) over 114 min of smooth organic ramp, and amplitude alone
#: scored that 1.0. Rise speed is what separates a raid/bot hit from a ramp.
SUDDEN_RISE_SECONDS = 300.0
#: At/above this rise time an unexplained jump keeps only the floor share of
#: its amplitude score, i.e. it is reported but can no longer drive a verdict.
SLOW_RISE_SECONDS = 1800.0
#: Floor share of the score kept by a slow ramp.
SLOW_RISE_FLOOR = 0.15


def rise_speed(rise_seconds: float) -> float:
    """1.0 for an instant or near-instant climb, down to :data:`SLOW_RISE_FLOOR`
    for a ramp of :data:`SLOW_RISE_SECONDS` or more. Flat outside both ends, so
    a 60 s step and a 300 s step both count as sudden."""
    if rise_seconds <= SUDDEN_RISE_SECONDS:
        return 1.0
    if rise_seconds >= SLOW_RISE_SECONDS:
        return SLOW_RISE_FLOOR
    span = SLOW_RISE_SECONDS - SUDDEN_RISE_SECONDS
    return 1.0 - (1.0 - SLOW_RISE_FLOOR) * ((rise_seconds - SUDDEN_RISE_SECONDS) / span)


def detect_jumps(
    points: Sequence[Point],
    *,
    min_amplitude: float = 1.5,
    min_points: int = 5,
) -> list[dict]:
    """Find step jumps on the expanded timeline.

    Returns ``[]`` when the timeline holds fewer than ``min_points`` observed
    minutes or when a jump's baseline window has a non-positive median. Each
    jump reports the numbers that produced it: ``started_ts`` (last minute at or
    below the threshold), ``peak_ts``, ``ended_ts`` (first minute back at or below
    the threshold, ``None`` when the stream ends elevated), ``baseline_viewers``
    (median of the pre-jump window), ``peak_viewers``, ``amplitude`` (peak/baseline,
    rounded to 3), ``rise_seconds``, ``is_instant`` (rise <= one minute),
    ``shape`` (``single_point``/``flat_top``/``smooth``/``unknown``), ``threshold``,
    ``mad`` and ``points`` (number of elevated minutes).
    """
    blocks = _blocks(points)
    if sum(len(block) for block in blocks) < min_points:
        return []

    jumps: list[dict] = []
    for block in blocks:
        index = 0
        while index < len(block):
            window = [point.viewers for point in block[max(0, index - BASELINE_WINDOW_POINTS):index]]
            baseline = median(window) if window else None
            if baseline is None or baseline <= 0:
                index += 1
                continue
            spread = mad(window, baseline) or 0.0
            threshold = max(baseline * min_amplitude, baseline + 3.0 * spread)
            if block[index].viewers <= threshold:
                index += 1
                continue
            start = index
            peak = index
            while index < len(block) and block[index].viewers > threshold:
                if block[index].viewers > block[peak].viewers:
                    peak = index
                index += 1
            jumps.append(_summarise(block, start, index, peak, baseline, spread, threshold))
    return jumps


def spike_findings(
    points: Sequence[Point],
    *,
    cause_hints: Iterable | Mapping | None = None,
    shape_repeats: Iterable | None = None,
) -> list[Finding]:
    """Detectors of section 3.2 that need the expanded timeline plus external evidence.

    ``cause_hints`` are the causes observed by ``causes.py``. A bare code string
    (or an object without a timestamp) applies to the whole stream; a hint carrying
    a timestamp applies only to the jump whose window
    ``[started_ts, ended_ts or last observed minute]`` contains it. Any matching
    cause hint suppresses ``no_justification`` for that jump.

    ``shape_repeats`` are the pairwise curve comparisons produced by
    ``shapes.py`` (``{'pair': [label, label], 'correlation': float,
    'max_abs_delta': float}``); entries at/above :data:`REPEAT_CORRELATION` or
    at/below :data:`REPEAT_MAX_ABS_DELTA` become one ``repeat_shape`` finding.
    """
    timeline = list(points)
    jumps = detect_jumps(timeline)
    hints = _normalise_hints(cause_hints)

    findings: list[Finding] = []
    for jump in jumps:
        if jump["amplitude"] < NO_JUSTIFICATION_AMPLITUDE:
            continue
        if _justified(jump, hints, timeline):
            continue
        findings.append(_no_justification(jump))

    plateau = _locked_plateau(timeline, jumps)
    if plateau is not None:
        findings.append(_plateau_lock(plateau))

    shape = _repeated_shape(shape_repeats)
    if shape is not None:
        findings.append(shape)

    staircase = _staircase_return(timeline)
    if staircase is not None:
        findings.append(staircase)
    return findings


def _blocks(points: Iterable[Point]) -> list[list[Point]]:
    """Split the timeline into contiguous runs of observed minutes.

    A ``None`` value (a real gap, see ``expand_series``) or a spacing longer than
    :data:`MAX_STEP_SECONDS` starts a new block, so no statistic ever bridges
    missing data.
    """
    blocks: list[list[Point]] = []
    current: list[Point] = []
    previous: dt.datetime | None = None
    for point in points:
        if point.viewers is None:
            if current:
                blocks.append(current)
            current, previous = [], None
            continue
        if previous is not None and (point.ts - previous).total_seconds() > MAX_STEP_SECONDS:
            if current:
                blocks.append(current)
            current = []
        current.append(point)
        previous = point.ts
    if current:
        blocks.append(current)
    return blocks


def _summarise(
    block: list[Point],
    start: int,
    end: int,
    peak: int,
    baseline: float,
    spread: float,
    threshold: float,
) -> dict:
    """Turn one elevated run of ``block[start:end]`` into a jump record."""
    started = block[start - 1] if start else block[start]
    top = block[peak]
    rise = (top.ts - started.ts).total_seconds()
    run = [float(point.viewers) for point in block[start:end]]
    width = max(run) - min(run)
    if end - start <= 1:
        shape = "single_point"
    elif width <= max(1.0, run[0] * 0.02):
        shape = "flat_top"
    elif end < len(block):
        shape = "smooth"
    else:
        shape = "unknown"
    return {
        "started_ts": started.ts,
        "peak_ts": top.ts,
        "ended_ts": block[end].ts if end < len(block) else None,
        "baseline_viewers": round(float(baseline), 3),
        "peak_viewers": int(top.viewers),
        "amplitude": round(float(top.viewers) / float(baseline), 3),
        "rise_seconds": int(round(rise)),
        "is_instant": rise <= POLL_SECONDS,
        "shape": shape,
        "threshold": round(float(threshold), 2),
        "mad": round(float(spread), 2),
        "points": end - start,
    }


def _plateau_candidates(points: Iterable[Point]) -> list[dict]:
    """Maximal runs in which every minute stays within :data:`PLATEAU_TOLERANCE`.

    The first minute of a run is its anchor and the reported ``value``; runs stop
    at a gap, at a non-positive viewer count, or as soon as a minute leaves the
    +/- tolerance band around the anchor.
    """
    candidates: list[dict] = []
    for block in _blocks(points):
        index = 0
        while index < len(block):
            anchor = block[index].viewers
            if anchor is None or anchor <= 0:
                index += 1
                continue
            end = index + 1
            while end < len(block):
                value = block[end].viewers
                if value is None or value <= 0 or abs(value - anchor) > PLATEAU_TOLERANCE * anchor:
                    break
                end += 1
            run = [float(point.viewers) for point in block[index:end]]
            candidates.append(
                {
                    "value": float(anchor),
                    "minutes": end - index,
                    "delta_ratio": round((max(run) - min(run)) / float(anchor), 5),
                    "start_ts": block[index].ts,
                    "end_ts": block[end - 1].ts,
                }
            )
            index = end
    return candidates


def _locked_plateau(points: Iterable[Point], jumps: list[dict]) -> dict | None:
    """The longest plateau that follows a jump and sits in its elevated regime."""
    best: dict | None = None
    for candidate in _plateau_candidates(points):
        if candidate["minutes"] < PLATEAU_MIN_MINUTES:
            continue
        elevated = any(
            jump["started_ts"] <= candidate["start_ts"] and candidate["value"] >= jump["threshold"]
            for jump in jumps
        )
        if not elevated:
            continue
        if best is None or candidate["minutes"] > best["minutes"]:
            best = candidate
    return best


def _normalise_hints(cause_hints: Iterable | Mapping | None) -> list[tuple[str, dt.datetime | None]]:
    """Normalise caller cause hints into ``(code, moment or None)`` pairs."""
    if cause_hints is None:
        return []
    if isinstance(cause_hints, (str, bytes)):
        return [(str(cause_hints), None)]
    if isinstance(cause_hints, Mapping):
        hint = _hint(cause_hints)
        if hint is not None:
            return [hint]
        return [(str(code), _moment(value)) for code, value in cause_hints.items()]
    hints: list[tuple[str, dt.datetime | None]] = []
    for item in cause_hints:
        if isinstance(item, (str, bytes)):
            hints.append((str(item), None))
            continue
        hint = _hint(item)
        if hint is not None:
            hints.append(hint)
    return hints


_HINT_CODE_KEYS = ("code", "hint", "kind", "name")
_HINT_TIME_KEYS = ("ts", "at", "observed_at", "started_ts", "moment", "time")


def _hint(item) -> tuple[str, dt.datetime | None] | None:
    """Extract ``(code, moment)`` from a mapping or any object exposing those fields."""
    getter = item.get if isinstance(item, Mapping) else lambda key, default=None: getattr(item, key, default)
    found = next((getter(key) for key in _HINT_CODE_KEYS if getter(key) is not None), None)
    if found is None:
        return None
    moment = next((getter(key) for key in _HINT_TIME_KEYS if getter(key) is not None), None)
    return str(found), _moment(moment)


def _moment(value) -> dt.datetime | None:
    """Timestamps may arrive as ``datetime`` or ISO strings."""
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, str):
        try:
            return dt.datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _justified(jump: dict, hints: list[tuple[str, dt.datetime | None]], points: list[Point]) -> bool:
    """True when a supplied cause hint falls inside the jump's window."""
    if not hints:
        return False
    start = jump["started_ts"]
    end = jump["ended_ts"] or _last_observed_ts(points)
    return any(moment is None or start <= moment <= end for _, moment in hints)


def _last_observed_ts(points: Sequence[Point]) -> dt.datetime:
    live = live_points(points)
    return live[-1].ts if live else dt.datetime.min


def _no_justification(jump: dict) -> Finding:
    amplitude = float(jump["amplitude"])
    rise = float(jump["rise_seconds"])
    # Amplitude alone cannot tell a raid from an audience arriving over an hour.
    # Score falls off with the time the climb actually took.
    speed = rise_speed(rise)
    score = clamp((0.1 + 0.9 * scale(amplitude, NO_JUSTIFICATION_AMPLITUDE, 12.0)) * speed)
    observed = {
        "amplitude": amplitude,
        "baseline_viewers": jump["baseline_viewers"],
        "peak_viewers": jump["peak_viewers"],
        "peak_ts": jump["peak_ts"].isoformat(),
        "rise_seconds": jump["rise_seconds"],
        "is_instant": bool(jump.get("is_instant")),
        "sudden": bool(rise <= SUDDEN_RISE_SECONDS),
        # Empty by construction: any cause hint inside the window suppresses this
        # finding, so the reported list is the evidence that none was observed.
        "hints": [],
    }
    pace = (
        f"за {int(rise)} с"
        if rise <= SUDDEN_RISE_SECONDS
        else f"за {int(rise)} с — это плавный набор аудитории, а не резкий скачок"
    )
    note = (
        f"онлайн вырос в {amplitude:.2f} раза (с {jump['baseline_viewers']:g} до {jump['peak_viewers']} зрителей) "
        f"{pace} без наблюдаемой причины"
    )
    return Finding(
        code="no_justification",
        score=round(score, 4),
        weight=WEIGHTS["no_justification"],
        observed=observed,
        note=note,
        explanation=(
            "Ни смена названия или категории, ни скачок фолловеров, ни рейд не совпали с окном скачка. "
            "Настоящий вирусный скачок выглядит так же, поэтому сам по себе сигнал слабый."
        ),
        note_code="note_no_justification",
        note_args={**observed, "hints": "нет"},
    )


def _plateau_lock(plateau: dict) -> Finding:
    minutes = int(plateau["minutes"])
    score = clamp(0.5 + 0.5 * scale(minutes, float(PLATEAU_MIN_MINUTES), 120.0))
    observed = {
        "value": plateau["value"],
        "minutes": minutes,
        "delta_ratio": plateau["delta_ratio"],
        "start_ts": plateau["start_ts"].isoformat(),
        "end_ts": plateau["end_ts"].isoformat(),
    }
    note = (
        f"онлайн зафиксирован на {plateau['value']:g} в течение {minutes} мин "
        f"(разброс {plateau['delta_ratio'] * 100:.2f}%)"
    )
    return Finding(
        code="plateau_lock",
        score=round(score, 4),
        weight=WEIGHTS["plateau_lock"],
        observed=observed,
        note=note,
        explanation=(
            "Живая аудитория колеблется на единицы процентов от минуты к минуте; "
            "удержание одного значения дольше 20 минут характерно для зафиксированной накрутки."
        ),
        note_code="note_plateau_lock",
        note_args=dict(observed),
    )


def _repeated_shape(shape_repeats: Iterable | None) -> Finding | None:
    if not shape_repeats:
        return None
    pairs: list[list[str]] = []
    best_correlation = 0.0
    best_delta: float | None = None
    for entry in shape_repeats:
        correlation = float(_field(entry, "correlation") or 0.0)
        raw_delta = _field(entry, "max_abs_delta")
        delta = None if raw_delta is None else float(raw_delta)
        if correlation < REPEAT_CORRELATION and (delta is None or delta > REPEAT_MAX_ABS_DELTA):
            continue
        labels = [str(label) for label in (_field(entry, "pair") or [])]
        if len(labels) < 2:
            continue
        pairs.append(labels)
        best_correlation = max(best_correlation, correlation)
        if delta is not None:
            best_delta = delta if best_delta is None else min(best_delta, delta)
    if not pairs:
        return None

    correlation_score = scale(best_correlation, REPEAT_CORRELATION, 1.0)
    delta_score = 0.0 if best_delta is None else 1.0 - scale(best_delta, 0.0, REPEAT_MAX_ABS_DELTA)
    labels_text = "; ".join(" ↔ ".join(labels) for labels in pairs)
    observed = {"pairs": pairs, "best_correlation": round(best_correlation, 4)}
    note = f"нормализованные кривые эфиров {labels_text} практически совпадают (r={best_correlation:.4f})"
    return Finding(
        code="repeat_shape",
        score=round(clamp(0.5 + 0.5 * max(correlation_score, delta_score)), 4),
        weight=WEIGHTS["repeat_shape"],
        observed=observed,
        note=note,
        explanation=(
            "Одинаковая форма кривой у нескольких своих же эфиров означает повторяемый сценарий набора онлайна, "
            "а не независимые живые всплески (см. shapes.py для сравнения кривых)."
        ),
        note_code="note_repeat_shape",
        note_args={"pairs": labels_text, "best_correlation": round(best_correlation, 4)},
    )


def _staircase_return(points: Iterable[Point]) -> Finding | None:
    """The last observed minute collapses to ~0 within one minute of its predecessor."""
    live = live_points(points)
    if len(live) < 2:
        return None
    last = live[-1]
    previous = live[-2]
    elapsed = (last.ts - previous.ts).total_seconds()
    if elapsed > MAX_STEP_SECONDS:
        return None
    pool = [point.viewers for point in live[:-1] if point.viewers > 0][-BASELINE_WINDOW_POINTS:]
    pre_median = median(pool)
    if pre_median is None or pre_median <= 0:
        return None
    limit = max(1.0, COLLAPSE_RATIO * pre_median)
    if last.viewers > limit or previous.viewers <= limit:
        return None

    observed = {
        "last_viewers": int(last.viewers),
        "pre_median": round(float(pre_median), 3),
        "collapse_seconds": int(round(elapsed)),
    }
    score = clamp(1.0 - float(last.viewers) / float(pre_median))
    note = (
        f"онлайн обвалился с {pre_median:g} до {last.viewers} зрителей за {int(round(elapsed))} с в конце эфира"
    )
    return Finding(
        code="staircase_return",
        score=round(score, 4),
        weight=WEIGHTS["staircase_return"],
        observed=observed,
        note=note,
        explanation=(
            "Аудитория исчезает за один интервал опроса, а не расходится постепенно: "
            "так выключается накрутка, живой эфир обычно теряет зрителей плавно."
        ),
        note_code="note_staircase_return",
        note_args=dict(observed),
    )


def _field(entry, name: str, default=None):
    if isinstance(entry, Mapping):
        return entry.get(name, default)
    return getattr(entry, name, default)
