"""Inferential ad-break detection and the ad vs non-ad comparison (idea #8).

**Ad breaks cannot be read anonymously.** The anonymous Twitch GQL client is
explicitly rejected for ``User.adBreak``/``adBreaks``/``adSchedule``/
``isAdBreak`` and ``Stream.videoAds``/``preRollAds`` (verified 2026-09-28, see
``docs/DETECTION_SPEC.md`` §1). Nothing in this module observes an ad; every
value it returns is an **inferential estimate built from observable proxies**:

1. ``viewer_cliff`` -- one-minute drop of >= 12 % of the running median with a
   rebound to >= 90 % of that median within 10 minutes.
2. ``chatter_dip`` -- chatters fall together with viewers while the
   ``chatters/viewers`` ratio stays flat within +/- 15 %, i.e. people left for a
   reason unrelated to interest.
3. ``title_change`` / ``game_change`` -- an explicit mid-stream external event
   diffed between consecutive ``samples`` rows (``observed`` reports
   ``minutes_into_stream`` measured from the first supplied sample, which is the
   closest available stand-in for the stream start).
4. ``raid_influx`` -- a slow rise spread over 10-30 minutes plus a follower jump
   taken from the ``followers_count`` key of ``samples``.

Every returned object carries the disclaimer twice: ``observed['proxy'] is True``
and a Russian ``note`` that names the estimate a proxy ("не подтверждено").
Each estimate also exposes ``note_code`` (``note_<kind>``) and ``note_args`` so
the integrator can add the matching RU/EN i18n templates, mirroring
:class:`app.detect.types.Finding`. ``AdBreakEstimate.to_dict`` renders ``ts`` as
an ISO-8601 string, so a list of estimates is directly JSON-serialisable.

The module is pure: stdlib + :mod:`app.detect.types` + :mod:`app.detect.series`
only. It operates on the EXPANDED per-minute timeline from
``series.expand_series`` -- never on raw ``Sample`` rows (see §2).

Known false-positive modes: a Twitch-side player stutter, a raid of the channel
by a partner, a deliberate title edit, or a view-farm drop all produce the same
proxy shapes. That is exactly why the comparison below is a proxy estimate and
why no verdict below is presented as an observation of an ad.
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field

from app.detect.series import Point, median
from app.detect.types import Finding, clamp, scale

WEIGHTS: dict[str, float] = {"ad_driven_growth": 0.08}

# --- viewer cliff ---------------------------------------------------------
CLIFF_DROP_FRACTION = 0.12
CLIFF_MAX_BEFORE_FRACTION = 1.12
CLIFF_REBOUND_FRACTION = 0.90
CLIFF_REBOUND_MINUTES = 10.0
CLIFF_BASELINE_MINUTES = 10.0
CLIFF_MIN_BASELINE_POINTS = 3
CLIFF_DROP_FULL_SCALE = 0.35
CLIFF_BASE_CONFIDENCE = 0.45
CLIFF_DROP_CONFIDENCE = 0.35
CLIFF_SPEED_CONFIDENCE = 0.20

# --- chatter dip ----------------------------------------------------------
CHATTER_DIP_MIN_DROP = 0.10
CHATTER_RATIO_TOLERANCE = 0.15
CHATTER_DIP_BASE_CONFIDENCE = 0.40
CHATTER_DIP_DROP_CONFIDENCE = 0.30
CHATTER_DIP_FLAT_CONFIDENCE = 0.20

# --- title / game change --------------------------------------------------
TITLE_CHANGE_CONFIDENCE = 0.50
GAME_CHANGE_CONFIDENCE = 0.45

# --- raid influx ----------------------------------------------------------
RAID_WINDOW_MINUTES = (10.0, 30.0)
RAID_MIN_RISE = 0.10
RAID_RISE_FULL_SCALE = 0.60
RAID_MAX_STEP_SHARE = 0.40
RAID_FOLLOWER_JUMP_MIN = 10.0
RAID_FOLLOWER_JUMP_RATIO = 0.01
RAID_FOLLOWER_FULL_SCALE = 50.0
RAID_BASE_CONFIDENCE = 0.35
RAID_RISE_CONFIDENCE = 0.35
RAID_FOLLOWER_CONFIDENCE = 0.30

# --- merging --------------------------------------------------------------
MERGE_WINDOW_MINUTES = 3.0

# --- ad vs non-ad comparison ----------------------------------------------
AD_WINDOW_MINUTES = 10.0
AD_WINDOW_MIN_POINTS = 3
REST_WINDOW_MIN_POINTS = 3
REST_WINDOW_MIN_MINUTES = 5
AD_DRIVEN_GROWTH_RATIO = 1.5
ORGANIC_GROWTH_RATIO = 1.1
AD_DRIVEN_SCORE_BASE = 0.40
AD_DRIVEN_SCORE_RANGE = 0.60
AD_DRIVEN_SCORE_FULL_SCALE = 3.0

NOTE_TEMPLATES: dict[str, str] = {
    "note_viewer_cliff": (
        "Прокси-признак рекламы (не подтверждено): онлайн упал на {drop_pct}% за минуту "
        "({viewers_before} → {viewers_after}) при медиане {baseline}, отскок до {rebound_viewers} через {rebound_minutes} мин."
    ),
    "note_chatter_dip": (
        "Прокси-признак рекламы (не подтверждено): онлайн -{viewers_drop_pct}% и чат -{chatters_drop_pct}% "
        "({viewers_before} → {viewers_after}, {chatters_before} → {chatters_after}), но доля чата почти неизменна "
        "({ratio_before} → {ratio_after}, {ratio_change_pct}%) — зрители ушли по общей причине."
    ),
    "note_title_change": (
        "Прокси-признак внешнего события (не подтверждено): заголовок на {minutes_into_stream}-й минуте "
        "сменился «{previous}» → «{current}». Смена заголовка бывает и без рекламы."
    ),
    "note_game_change": (
        "Прокси-признак внешнего события (не подтверждено): категория на {minutes_into_stream}-й минуте "
        "сменилась «{previous}» → «{current}». Смена категории бывает и без рекламы."
    ),
    "note_raid_influx": (
        "Прокси-признак рейда или закупки (не подтверждено): плавный рост онлайна {viewers_start} → {viewers_end} "
        "(+{rise_pct}%) за {minutes} мин с приростом подписчиков +{followers_delta} ({followers_before} → {followers_after})."
    ),
    "note_combined": (
        "Прокси-признаки рекламы совпали (не подтверждено): {kinds} — {component_count} сигнала(ов), "
        "уверенность {confidence}. Наблюдается не реклама, а её косвенные признаки."
    ),
    "note_ad_driven_growth": (
        "Рост онлайна сосредоточен в окнах предполагаемой рекламы: {ad_growth_ratio} за {ad_minutes} мин против "
        "{rest_growth_ratio} за {rest_minutes} мин вне окон (отношение {growth_ratio}, разрывов {breaks}). "
        "Это прокси-оценка: реклама анонимно не читается."
    ),
}

KIND_LABELS_RU: dict[str, str] = {
    "viewer_cliff": "провал онлайна с отскоком",
    "chatter_dip": "пропорциональный провал чата",
    "title_change": "смена заголовка",
    "game_change": "смена категории",
    "raid_influx": "плавный прилив с подписчиками",
    "combined": "совпадение признаков",
}


@dataclass
class AdBreakEstimate:
    """One *estimated* (never observed) mid-roll ad break.

    ``confidence`` is 0..1 and describes how well the proxy shape matched, not
    the probability that an ad actually ran. ``observed`` holds the raw numbers
    that produced the estimate plus ``'proxy': True``.
    """

    ts: dt.datetime
    kind: str
    confidence: float
    observed: dict
    note: str
    note_code: str = ""
    note_args: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """JSON-ready dump: ``ts`` becomes an ISO-8601 string."""
        payload = asdict(self)
        payload["ts"] = self.ts.isoformat()
        return payload


def _field(row: object, name: str, default=None):
    if isinstance(row, Mapping):
        return row.get(name, default)
    return getattr(row, name, default)


def _number(row: object, name: str) -> float | None:
    value = _field(row, name)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_datetime(value: object) -> dt.datetime | None:
    """Naive-UTC datetime from a datetime or an ISO-8601 string, else ``None``."""
    if isinstance(value, dt.datetime):
        moment = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            moment = dt.datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return moment


def _iso(point: object) -> str:
    moment = _as_datetime(_field(point, "ts"))
    return "" if moment is None else moment.isoformat()


def _elapsed_minutes(points: Sequence[Point], start: int, index: int) -> float:
    """Minutes between two timeline indexes; falls back to the index distance."""
    begin = _as_datetime(_field(points[start], "ts"))
    moment = _as_datetime(_field(points[index], "ts"))
    if begin is not None and moment is not None:
        return (moment - begin).total_seconds() / 60.0
    return float(index - start)


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def _format_note(code: str, args: Mapping) -> str:
    """Render the Russian note; string arguments are brace-escaped."""
    safe = {
        key: value.replace("{", "{{").replace("}", "}}") if isinstance(value, str) else value
        for key, value in args.items()
    }
    return NOTE_TEMPLATES[code].format(**safe)


# --- proxies --------------------------------------------------------------


def _trailing_baseline(points: Sequence[Point], index: int) -> tuple[float | None, int]:
    """Median viewers over the ``CLIFF_BASELINE_MINUTES`` before ``index``."""
    anchor = _as_datetime(_field(points[index], "ts"))
    window: list[float] = []
    for back in range(index - 1, -1, -1):
        moment = _as_datetime(_field(points[back], "ts"))
        if anchor is not None and moment is not None:
            if (anchor - moment).total_seconds() > CLIFF_BASELINE_MINUTES * 60.0:
                break
        elif index - back > CLIFF_BASELINE_MINUTES:
            break
        value = _number(points[back], "viewers")
        if value is not None:
            window.append(value)
    if len(window) < CLIFF_MIN_BASELINE_POINTS:
        return None, len(window)
    return median(window), len(window)


def _rebound_within(
    points: Sequence[Point], index: int, baseline: float, limit_minutes: float
) -> tuple[int, int] | None:
    """First index reaching 90 % of ``baseline`` within ``limit_minutes``."""
    threshold = baseline * CLIFF_REBOUND_FRACTION
    for forward in range(index + 1, len(points)):
        elapsed = _elapsed_minutes(points, index, forward)
        if elapsed > limit_minutes:
            return None
        value = _number(points[forward], "viewers")
        if value is not None and value >= threshold:
            return forward, int(round(elapsed))
    return None


def _viewer_cliffs(points: Sequence[Point]) -> list[AdBreakEstimate]:
    found: list[AdBreakEstimate] = []
    for index in range(1, len(points)):
        before = _number(points[index - 1], "viewers")
        after = _number(points[index], "viewers")
        moment = _as_datetime(_field(points[index], "ts"))
        if before is None or after is None or before <= 0 or moment is None:
            continue
        baseline, baseline_points = _trailing_baseline(points, index)
        if baseline is None or baseline <= 0:
            continue
        drop = (before - after) / baseline
        if drop < CLIFF_DROP_FRACTION:
            continue
        # The fall must start from the running level, not from a spike: an
        # up-then-back-down shape is not an ad cliff.
        if before > baseline * CLIFF_MAX_BEFORE_FRACTION:
            continue
        rebound = _rebound_within(points, index, baseline, CLIFF_REBOUND_MINUTES)
        if rebound is None:
            continue
        rebound_index, rebound_minutes = rebound
        rebound_viewers = _number(points[rebound_index], "viewers")
        confidence = clamp(
            CLIFF_BASE_CONFIDENCE
            + CLIFF_DROP_CONFIDENCE * scale(drop, CLIFF_DROP_FRACTION, CLIFF_DROP_FULL_SCALE)
            + CLIFF_SPEED_CONFIDENCE * clamp(1.0 - rebound_minutes / CLIFF_REBOUND_MINUTES)
        )
        args = {
            "drop_pct": f"{drop * 100:.1f}",
            "viewers_before": int(round(before)),
            "viewers_after": int(round(after)),
            "baseline": int(round(baseline)),
            "rebound_viewers": int(round(rebound_viewers or 0.0)),
            "rebound_minutes": rebound_minutes,
        }
        observed = {
            "proxy": True,
            "observed_at": _iso(points[index]),
            "viewers_before": int(round(before)),
            "viewers_after": int(round(after)),
            "running_median": int(round(baseline)),
            "baseline_points": baseline_points,
            "drop_fraction": _round(drop),
            "drop_pct": _round(drop * 100.0, 1),
            "rebound_viewers": int(round(rebound_viewers or 0.0)),
            "rebound_minutes": rebound_minutes,
            "proxies": "single-interval drop >= 12% of the running median, rebound to >= 90% within 10 min",
        }
        found.append(
            AdBreakEstimate(
                ts=moment,
                kind="viewer_cliff",
                confidence=_round(confidence) or 0.0,
                observed=observed,
                note=_format_note("note_viewer_cliff", args),
                note_code="note_viewer_cliff",
                note_args=args,
            )
        )
    return found


def _chatter_dips(points: Sequence[Point]) -> list[AdBreakEstimate]:
    found: list[AdBreakEstimate] = []
    for index in range(1, len(points)):
        prev_viewers = _number(points[index - 1], "viewers")
        cur_viewers = _number(points[index], "viewers")
        prev_chatters = _number(points[index - 1], "chatters")
        cur_chatters = _number(points[index], "chatters")
        moment = _as_datetime(_field(points[index], "ts"))
        if None in (prev_viewers, cur_viewers, prev_chatters, cur_chatters) or moment is None:
            continue
        if prev_viewers <= 0 or cur_viewers <= 0 or prev_chatters <= 0:
            continue
        viewers_drop = (prev_viewers - cur_viewers) / prev_viewers
        chatters_drop = (prev_chatters - cur_chatters) / prev_chatters
        if viewers_drop < CHATTER_DIP_MIN_DROP or chatters_drop < CHATTER_DIP_MIN_DROP:
            continue
        ratio_before = prev_chatters / prev_viewers
        ratio_after = cur_chatters / cur_viewers
        ratio_change = abs(ratio_after - ratio_before) / ratio_before
        if ratio_change > CHATTER_RATIO_TOLERANCE:
            continue
        confidence = clamp(
            CHATTER_DIP_BASE_CONFIDENCE
            + CHATTER_DIP_DROP_CONFIDENCE * scale(viewers_drop, CHATTER_DIP_MIN_DROP, 0.30)
            + CHATTER_DIP_FLAT_CONFIDENCE * (1.0 - ratio_change / CHATTER_RATIO_TOLERANCE)
        )
        args = {
            "viewers_before": int(round(prev_viewers)),
            "viewers_after": int(round(cur_viewers)),
            "chatters_before": int(round(prev_chatters)),
            "chatters_after": int(round(cur_chatters)),
            "viewers_drop_pct": f"{viewers_drop * 100:.1f}",
            "chatters_drop_pct": f"{chatters_drop * 100:.1f}",
            "ratio_before": f"{ratio_before:.3f}",
            "ratio_after": f"{ratio_after:.3f}",
            "ratio_change_pct": f"{ratio_change * 100:.1f}",
        }
        observed = {
            "proxy": True,
            "observed_at": _iso(points[index]),
            "viewers_before": int(round(prev_viewers)),
            "viewers_after": int(round(cur_viewers)),
            "chatters_before": int(round(prev_chatters)),
            "chatters_after": int(round(cur_chatters)),
            "viewers_drop_fraction": _round(viewers_drop),
            "chatters_drop_fraction": _round(chatters_drop),
            "chat_ratio_before": _round(ratio_before),
            "chat_ratio_after": _round(ratio_after),
            "chat_ratio_change_fraction": _round(ratio_change),
            "proxies": "chatters fall with viewers while chatters/viewers stays flat within +/-15%",
        }
        found.append(
            AdBreakEstimate(
                ts=moment,
                kind="chatter_dip",
                confidence=_round(confidence) or 0.0,
                observed=observed,
                note=_format_note("note_chatter_dip", args),
                note_code="note_chatter_dip",
                note_args=args,
            )
        )
    return found


def _sample_rows(samples: Iterable[object] | None) -> list[dict]:
    """Normalise ``samples`` into timestamp-sorted rows with title/game/followers."""
    rows: list[dict] = []
    for item in samples or ():
        moment = _as_datetime(_field(item, "observed_at"))
        if moment is None:
            continue
        rows.append(
            {
                "ts": moment,
                "title": _text(_field(item, "title")),
                "game": _text(_field(item, "game")),
                "followers": _number(item, "followers_count"),
            }
        )
    rows.sort(key=lambda row: row["ts"])
    return rows


def _change_estimates(rows: Sequence[dict], field_name: str, kind: str, confidence: float) -> list[AdBreakEstimate]:
    found: list[AdBreakEstimate] = []
    for previous, current in zip(rows, rows[1:]):
        before = previous[field_name]
        after = current[field_name]
        if not before or not after or before == after:
            continue
        minutes_into_stream = (current["ts"] - rows[0]["ts"]).total_seconds() / 60.0
        args = {
            "previous": before,
            "current": after,
            "minutes_into_stream": int(round(minutes_into_stream)),
        }
        observed = {
            "proxy": True,
            "observed_at": current["ts"].isoformat(),
            "previous_" + field_name: before,
            field_name: after,
            "minutes_into_stream": _round(minutes_into_stream, 1),
            "proxies": "consecutive samples differ mid-stream; may be an edit rather than an ad",
        }
        found.append(
            AdBreakEstimate(
                ts=current["ts"],
                kind=kind,
                confidence=confidence,
                observed=observed,
                note=_format_note("note_" + kind, args),
                note_code="note_" + kind,
                note_args=args,
            )
        )
    return found


def _steps_within(points: Sequence[Point], start: int, end: int) -> list[float]:
    steps: list[float] = []
    for index in range(start, end):
        left = _number(points[index], "viewers")
        right = _number(points[index + 1], "viewers")
        if left is None or right is None:
            continue
        steps.append(right - left)
    return steps


def _followers_delta(rows: Sequence[dict], start: dt.datetime, end: dt.datetime) -> tuple[float, float, float] | None:
    inside = [row["followers"] for row in rows if start <= row["ts"] <= end and row["followers"] is not None]
    if len(inside) < 2:
        return None
    return inside[-1] - inside[0], inside[0], inside[-1]


def _raid_influxes(points: Sequence[Point], rows: Sequence[dict]) -> list[AdBreakEstimate]:
    """Slow rise (10-30 min) plus a follower jump; oversized single steps excluded."""
    if not rows:
        return []
    low, high = RAID_WINDOW_MINUTES
    candidates: list[tuple[float, int, int, dict, dict]] = []
    for start in range(len(points)):
        start_viewers = _number(points[start], "viewers")
        start_ts = _as_datetime(_field(points[start], "ts"))
        if start_viewers is None or start_viewers <= 0 or start_ts is None:
            continue
        best: tuple[float, int, int, dict, dict] | None = None
        for end in range(start + 1, len(points)):
            elapsed = _elapsed_minutes(points, start, end)
            if elapsed < low:
                continue
            if elapsed > high:
                break
            end_viewers = _number(points[end], "viewers")
            end_ts = _as_datetime(_field(points[end], "ts"))
            if end_viewers is None or end_ts is None:
                continue
            rise = (end_viewers - start_viewers) / start_viewers
            if rise < RAID_MIN_RISE:
                continue
            total = end_viewers - start_viewers
            steps = _steps_within(points, start, end)
            if not steps or max(steps) > RAID_MAX_STEP_SHARE * total:
                continue
            followers = _followers_delta(rows, start_ts, end_ts)
            if followers is None:
                continue
            delta, followers_before, followers_after = followers
            if delta < RAID_FOLLOWER_JUMP_MIN:
                continue
            if followers_before > 0 and delta / followers_before < RAID_FOLLOWER_JUMP_RATIO:
                continue
            confidence = clamp(
                RAID_BASE_CONFIDENCE
                + RAID_RISE_CONFIDENCE * scale(rise, RAID_MIN_RISE, RAID_RISE_FULL_SCALE)
                + RAID_FOLLOWER_CONFIDENCE * scale(delta, RAID_FOLLOWER_JUMP_MIN, RAID_FOLLOWER_FULL_SCALE)
            )
            args = {
                "viewers_start": int(round(start_viewers)),
                "viewers_end": int(round(end_viewers)),
                "rise_pct": f"{rise * 100:.1f}",
                "minutes": int(round(elapsed)),
                "followers_before": int(round(followers_before)),
                "followers_after": int(round(followers_after)),
                "followers_delta": int(round(delta)),
            }
            observed = {
                "proxy": True,
                "observed_at": end_ts.isoformat(),
                "window_start": start_ts.isoformat(),
                "window_end": end_ts.isoformat(),
                "minutes": int(round(elapsed)),
                "viewers_start": int(round(start_viewers)),
                "viewers_end": int(round(end_viewers)),
                "rise_fraction": _round(rise),
                "rise_pct": _round(rise * 100.0, 1),
                "max_step": _round(max(steps), 2),
                "max_step_share": _round(max(steps) / total),
                "followers_before": int(round(followers_before)),
                "followers_after": int(round(followers_after)),
                "followers_delta": int(round(delta)),
                "proxies": "gradual rise over 10-30 min with a simultaneous follower jump",
            }
            if best is None or confidence > best[0] or (confidence == best[0] and end - start > best[2] - best[1]):
                best = (confidence, start, end, args, observed)
        if best is not None:
            candidates.append(best)

    found: list[AdBreakEstimate] = []
    accepted: list[tuple[int, int]] = []
    for confidence, start, end, args, observed in sorted(candidates, key=lambda item: (-item[0], item[1])):
        if any(not (end < taken_start or start > taken_end) for taken_start, taken_end in accepted):
            continue
        accepted.append((start, end))
        found.append(
            AdBreakEstimate(
                ts=end_ts,
                kind="raid_influx",
                confidence=_round(confidence) or 0.0,
                observed=observed,
                note=_format_note("note_raid_influx", args),
                note_code="note_raid_influx",
                note_args=args,
            )
        )
    return sorted(found, key=lambda item: item.ts)


# --- merging --------------------------------------------------------------


def _merge(estimates: Sequence[AdBreakEstimate]) -> list[AdBreakEstimate]:
    """Fold estimates within ``MERGE_WINDOW_MINUTES`` into one; duplicates dropped."""
    ordered = sorted(estimates, key=lambda item: item.ts)
    groups: list[list[AdBreakEstimate]] = []
    for estimate in ordered:
        if groups and (estimate.ts - groups[-1][0].ts).total_seconds() <= MERGE_WINDOW_MINUTES * 60.0:
            groups[-1].append(estimate)
        else:
            groups.append([estimate])
    merged = [_merge_group(group) for group in groups]
    return sorted(merged, key=lambda item: item.ts)


def _merge_group(group: Sequence[AdBreakEstimate]) -> AdBreakEstimate:
    primary = max(group, key=lambda item: item.confidence)
    kinds = sorted({item.kind for item in group})
    if len(group) == 1 or len(kinds) == 1:
        return primary
    confidence = round(max(item.confidence for item in group), 4)
    observed = dict(primary.observed)
    observed["proxy"] = True
    observed["kinds"] = kinds
    observed["component_count"] = len(group)
    observed["components"] = [dict(item.observed) for item in group]
    observed["ts_offsets_seconds"] = [round((item.ts - primary.ts).total_seconds(), 1) for item in group]
    args = {
        "kinds": " + ".join(kinds),
        "confidence": f"{confidence:.2f}",
        "component_count": len(group),
    }
    return AdBreakEstimate(
        ts=primary.ts,
        kind="combined",
        confidence=confidence,
        observed=observed,
        note=_format_note("note_combined", args),
        note_code="note_combined",
        note_args=args,
    )


# --- public API -----------------------------------------------------------


def ad_break_estimates(points: Sequence[Point], *, samples: Iterable[object] | None = None) -> list[AdBreakEstimate]:
    """Estimate mid-roll ad breaks from observable proxies on the expanded timeline.

    ``points`` is the per-minute timeline from ``series.expand_series``.
    ``samples`` (optional) is an iterable of dicts with ``observed_at`` plus
    ``title``/``game``/``followers_count``; without it only the timeline proxies
    (viewer cliff, chatter dip) are available and no estimate invents a title,
    game or follower number.

    Estimates within ``MERGE_WINDOW_MINUTES`` of each other are merged: same kind
    keeps the highest-confidence member, different kinds fold into one estimate
    with ``kind='combined'``. Every estimate is a proxy, never an observed ad.
    """
    timeline = list(points)
    rows = _sample_rows(samples)
    found: list[AdBreakEstimate] = []
    found.extend(_viewer_cliffs(timeline))
    found.extend(_chatter_dips(timeline))
    found.extend(_change_estimates(rows, "title", "title_change", TITLE_CHANGE_CONFIDENCE))
    found.extend(_change_estimates(rows, "game", "game_change", GAME_CHANGE_CONFIDENCE))
    found.extend(_raid_influxes(timeline, rows))
    return _merge(found)


def _as_estimates(breaks: object) -> list[AdBreakEstimate]:
    """Accept estimates, a single estimate, or round-tripped ``to_dict`` payloads."""
    if breaks is None:
        return []
    if isinstance(breaks, AdBreakEstimate):
        return [breaks]
    result: list[AdBreakEstimate] = []
    for item in breaks:
        if isinstance(item, AdBreakEstimate):
            result.append(item)
        elif isinstance(item, Mapping):
            moment = _as_datetime(item.get("ts"))
            if moment is None:
                continue
            result.append(
                AdBreakEstimate(
                    ts=moment,
                    kind=str(item.get("kind") or "unknown"),
                    confidence=float(item.get("confidence") or 0.0),
                    observed=dict(item.get("observed") or {}),
                    note=str(item.get("note") or ""),
                )
            )
    return result


def _split_windows(
    points: Sequence[Point], estimates: Sequence[AdBreakEstimate]
) -> tuple[list[Point], list[Point]]:
    """Ad windows = every break timestamp +/- ``AD_WINDOW_MINUTES``; rest = the rest."""
    span = dt.timedelta(minutes=AD_WINDOW_MINUTES)
    ad_points: list[Point] = []
    rest_points: list[Point] = []
    for point in points:
        moment = _as_datetime(_field(point, "ts"))
        inside = moment is not None and any(abs(moment - estimate.ts) <= span for estimate in estimates)
        (ad_points if inside else rest_points).append(point)
    return ad_points, rest_points


def _followers_per_hour(rows: Sequence[dict], points: Sequence[Point]) -> float | None:
    moments = [moment for moment in (_as_datetime(_field(point, "ts")) for point in points) if moment is not None]
    if not moments or not rows:
        return None
    start, end = min(moments), max(moments)
    span_hours = (end - start).total_seconds() / 3600.0
    inside = [row["followers"] for row in rows if start <= row["ts"] <= end and row["followers"] is not None]
    if len(inside) < 2 or span_hours <= 0:
        return None
    return round((inside[-1] - inside[0]) / span_hours, 4)


def _window_stats(points: Sequence[Point], rows: Sequence[dict]) -> dict:
    data = [point for point in points if _number(point, "viewers") is not None]
    growth: float | None = None
    if len(data) >= 2:
        first = _number(data[0], "viewers")
        last = _number(data[-1], "viewers")
        if first and first > 0 and last is not None:
            growth = last / first
    ratios: list[float] = []
    for point in data:
        viewers = _number(point, "viewers")
        chatters = _number(point, "chatters")
        if viewers and viewers > 0 and chatters is not None:
            ratios.append(chatters / viewers)
    chat_median = median(ratios)
    return {
        "minutes": len(points),
        "viewer_growth_ratio": _round(growth),
        "chat_ratio_median": _round(chat_median),
        "followers_per_hour": _followers_per_hour(rows, points),
        "points": len(data),
    }


def _empty_window() -> dict:
    return {
        "minutes": 0,
        "viewer_growth_ratio": None,
        "chat_ratio_median": None,
        "followers_per_hour": None,
        "points": 0,
    }


def compare_ad_vs_nonad(
    points: Sequence[Point], breaks: object, *, samples: Iterable[object] | None = None
) -> dict:
    """Compare the timeline inside estimated ad windows against the rest of it.

    Ad windows are the break timestamps +/- ``AD_WINDOW_MINUTES`` (10 min); every
    other timeline minute is "rest". Both sides report minutes, viewer growth
    ratio (last/first), median chat ratio, followers per hour (only when
    ``samples`` carries ``followers_count``; otherwise ``None`` -- never a
    fabricated number) and the count of points that actually had data.

    ``verdict`` is ``'ad_driven'`` when the ad-side growth is at least
    ``AD_DRIVEN_GROWTH_RATIO`` times the rest-side growth, ``'organic'`` at or
    below ``ORGANIC_GROWTH_RATIO``, ``'inconclusive'`` in between or when a side
    cannot be measured. ``finding`` (code ``ad_driven_growth``, weight 0.08) is
    emitted only for ``'ad_driven'``. When no break proxy fired, ``available`` is
    ``False`` and ``reason`` says so explicitly instead of reporting zeros: an ad
    that cannot be read anonymously is not an ad that did not run.
    """
    timeline = list(points)
    estimates = _as_estimates(breaks)
    rows = _sample_rows(samples)
    ad_points, rest_points = _split_windows(timeline, estimates)
    ad_window = _window_stats(ad_points, rows) if estimates else _empty_window()
    rest_window = _window_stats(rest_points, rows) if estimates else _empty_window()
    ad_growth = ad_window["viewer_growth_ratio"]
    rest_growth = rest_window["viewer_growth_ratio"]

    available = False
    reason = ""
    if not estimates:
        reason = (
            "Прокси-разрывы не обнаружены: ни один признак рекламы не сработал, сравнивать рекламные и остальные "
            "окна не с чем. Реклама анонимно не читается, поэтому её отсутствие здесь не доказано."
        )
    elif ad_window["points"] < AD_WINDOW_MIN_POINTS:
        reason = (
            f"В окнах предполагаемой рекламы всего {ad_window['points']} точек онлайна "
            f"(нужно >= {AD_WINDOW_MIN_POINTS}) — сравнение недостоверно."
        )
    elif rest_window["points"] < REST_WINDOW_MIN_POINTS or rest_window["minutes"] < REST_WINDOW_MIN_MINUTES:
        reason = (
            f"Вне рекламных окон всего {rest_window['points']} точек онлайна за {rest_window['minutes']} мин "
            f"(нужно >= {REST_WINDOW_MIN_POINTS} точек и {REST_WINDOW_MIN_MINUTES} мин) — сравнение недостоверно."
        )
    elif ad_growth is None or rest_growth is None:
        reason = "На одной из сторон нет двух точек онлайна с данными — прирост определить нельзя."
    else:
        available = True

    growth_ratio: float | None = None
    verdict = "inconclusive"
    if available and rest_growth:
        growth_ratio = round(ad_growth / rest_growth, 4)
        if growth_ratio >= AD_DRIVEN_GROWTH_RATIO:
            verdict = "ad_driven"
        elif growth_ratio <= ORGANIC_GROWTH_RATIO:
            verdict = "organic"

    followers_suffix = "" if rows else " Динамика подписчиков не передана, followers_per_hour не измерен."
    if available:
        verdict_ru = {
            "ad_driven": "рост похож на закупленный трафик вокруг разрывов",
            "organic": "рост выглядит органическим",
            "inconclusive": "разница между окнами неубедительна",
        }[verdict]
        # `rest_growth` can be 0 (a flat "rest of stream" window), which leaves
        # `growth_ratio` None. Never format None as a float.
        ratio_text = "не определено" if growth_ratio is None else f"×{growth_ratio:.2f}"
        ad_growth_text = "н/д" if ad_growth is None else f"×{ad_growth:.2f}"
        rest_growth_text = "н/д" if rest_growth is None else f"×{rest_growth:.2f}"
        note = (
            f"Прокси-сравнение реклама/не-реклама: разрывов {len(estimates)}, рост онлайна в окнах "
            f"{ad_growth_text} за {ad_window['minutes']} мин против {rest_growth_text} за "
            f"{rest_window['minutes']} мин вне окон, отношение {ratio_text} — {verdict_ru}. "
            f"Реклама анонимно не читается: это оценка по прокси-признакам.{followers_suffix}"
        )
    else:
        note = f"Прокси-сравнение недоступно. {reason}{followers_suffix}"

    result = {
        "available": available,
        "reason": reason,
        "breaks": [estimate.to_dict() for estimate in estimates],
        "ad_window": ad_window,
        "rest_window": rest_window,
        "growth_ratio": growth_ratio,
        "verdict": verdict,
        "note": note,
        "finding": None,
    }
    if verdict == "ad_driven":
        args = {
            "ad_growth_ratio": f"×{ad_growth:.2f}",
            "rest_growth_ratio": f"×{rest_growth:.2f}",
            "growth_ratio": f"×{growth_ratio:.2f}",
            "ad_minutes": ad_window["minutes"],
            "rest_minutes": rest_window["minutes"],
            "breaks": len(estimates),
        }
        result["finding"] = Finding(
            code="ad_driven_growth",
            score=clamp(
                AD_DRIVEN_SCORE_BASE
                + AD_DRIVEN_SCORE_RANGE * scale(growth_ratio, AD_DRIVEN_GROWTH_RATIO, AD_DRIVEN_SCORE_FULL_SCALE)
            ),
            weight=WEIGHTS["ad_driven_growth"],
            observed={
                "proxy": True,
                "ad_growth_ratio": ad_growth,
                "rest_growth_ratio": rest_growth,
                "growth_ratio": growth_ratio,
                "breaks": len(estimates),
                "ad_minutes": ad_window["minutes"],
                "rest_minutes": rest_window["minutes"],
            },
            note=_format_note("note_ad_driven_growth", args),
            explanation=(
                "Прирост зрителей внутри окон, где сработал прокси-признак рекламы, materially выше, чем вне их. "
                "Возможная причина — закупленный трафик или запуск рекламы, но это не наблюдение рекламы: "
                "поля adBreak/adSchedule анонимно недоступны."
            ),
            note_code="note_ad_driven_growth",
            note_args=args,
        )
    return result
