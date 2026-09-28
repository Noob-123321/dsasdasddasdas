"""Pure analytics functions: derived values, spikes, scores and history."""
from __future__ import annotations

import datetime as dt
import statistics
from collections.abc import Iterable

from .clock import as_utc, iso, utcnow

RISK_WEIGHTS = {"low_ratio": 0.40, "spike_no_chat": 0.30, "sawtooth": 0.20, "category_outlier": 0.10}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def derived_metrics(channel) -> dict:
    viewers = channel.latest_viewers
    chatters = channel.latest_chatters
    authorized = None
    guests = None
    ratio = None
    raw_ratio = None
    if chatters is not None:
        authorized = min(chatters, viewers) if viewers is not None else chatters
        if viewers is not None:
            guests = max(viewers - authorized, 0)
            if viewers > 0:
                raw_ratio = round(chatters / viewers, 5)
                ratio = round(min(raw_ratio, 1.0), 5)
    return {
        "is_live": bool(channel.latest_is_live),
        "total_viewers": viewers,
        "authorized": authorized,
        "guests": guests,
        "chat_ratio": ratio,
        "raw_chat_ratio": raw_ratio,
        "title": channel.latest_title,
        "game": channel.latest_game,
        "fetched_at": iso(channel.latest_observed_at),
        "stale": channel.latest_observed_at is None or (utcnow() - channel.latest_observed_at).total_seconds() > 180,
    }


def _sample_dict(row) -> dict:
    return {
        "observed_at": as_utc(row.observed_at) or utcnow(),
        "last_seen_at": as_utc(row.last_seen_at) or utcnow(),
        "is_live": bool(row.is_live),
        "viewers": row.viewer_count,
        "chatters": row.chatters_count,
        "repeat_count": row.repeat_count or 1,
    }


def detect_spikes(rows: Iterable[dict], *, min_amplitude: float = 1.5, min_samples: int = 5) -> list[dict]:
    values = [row for row in sorted(rows, key=lambda item: item["observed_at"]) if row.get("is_live") and row.get("viewers") is not None]
    if len(values) < min_samples:
        return []
    viewers = [float(row["viewers"]) for row in values]
    baseline = float(statistics.median(viewers))
    if baseline <= 0:
        return []
    mad = float(statistics.median(abs(value - baseline) for value in viewers))
    relative = baseline * min_amplitude
    absolute = baseline + 3.0 * mad
    threshold = max(relative, absolute)
    method = "median_mad" if absolute >= relative else "median_window"
    result: list[dict] = []
    index = 0
    while index < len(values):
        if values[index]["viewers"] <= threshold:
            index += 1
            continue
        start = index
        peak = index
        while index < len(values) and values[index]["viewers"] > threshold:
            if values[index]["viewers"] > values[peak]["viewers"]:
                peak = index
            index += 1
        before = values[start - 1] if start else None
        after = values[index] if index < len(values) else None
        is_instant = index - start == 1 and before is not None and after is not None
        shape = "single_point" if is_instant else "flat_top" if index - start >= 3 else "smooth" if before and after else "unknown"
        warnings = []
        if is_instant:
            warnings.append("форма не измерена: пик и возврат попали в один интервал")
        if after is None:
            warnings.append("спад не наблюдался")
        result.append(
            {
                "started_at": before["observed_at"] if before else values[start]["observed_at"],
                "peak_at": values[peak]["observed_at"],
                "ended_at": after["observed_at"] if after else None,
                "baseline_viewers": int(round(baseline)),
                "peak_viewers": int(values[peak]["viewers"]),
                "amplitude": round(values[peak]["viewers"] / baseline, 3),
                "shape": shape,
                "is_instant": is_instant,
                "confidence": round(_clamp(0.45 + min(len(values) / 100, 0.35) - (0.25 if is_instant else 0)), 3),
                "baseline_method": method,
                "baseline_samples": len(values),
                "notes": {"threshold": round(threshold, 2), "mad": round(mad, 2), "warnings": warnings},
            }
        )
    return result


def _ratio_values(rows: list[dict]) -> list[float]:
    return [min(row["chatters"] / row["viewers"], 1.0) for row in rows if row.get("is_live") and row.get("viewers") and row.get("chatters") is not None]


def _sawtooth(rows: list[dict]) -> tuple[float | None, str | None]:
    viewers = [row.get("viewers") for row in rows if row.get("is_live") and row.get("viewers") is not None]
    if len(viewers) < 8:
        return None, None
    median = statistics.median(viewers)
    if median <= 0:
        return None, None
    direction_changes = sum(1 for left, right in zip(viewers, viewers[1:]) if (right - left) * (viewers[max(0, len(viewers) - 3)] - left) < 0)
    score = _clamp(direction_changes / max(len(viewers) - 1, 1) / 0.45)
    return score, str(direction_changes)


def score_rows(rows: list[dict], spikes: list[dict]) -> dict:
    live = [row for row in rows if row.get("is_live") and row.get("viewers") is not None]
    ratios = _ratio_values(live)
    factors: list[dict] = []
    warnings: list[str] = []
    warning_codes: list[dict] = []
    if ratios:
        ratio = statistics.median(ratios)
        low_score = _clamp((0.15 - ratio) / 0.13)
        factors.append({"code": "low_ratio", "value": round(ratio, 5), "score": round(low_score, 4), "weight": RISK_WEIGHTS["low_ratio"], "note_code": "note_low_ratio", "note_args": {"ratio": f"{ratio * 100:.1f}%"}, "note": f"медиана доли чаттеров {ratio * 100:.1f}%"})
    else:
        warnings.append("не хватает данных о чате")
        warning_codes.append({"code": "warn_no_chat_data"})
    if spikes:
        worst = max(item.get("amplitude", 1.0) for item in spikes)
        spike_score = _clamp((worst - 1.5) / 2.5)
        factors.append({"code": "spike_no_chat", "value": round(worst, 3), "score": round(spike_score, 4), "weight": RISK_WEIGHTS["spike_no_chat"], "note_code": "note_spike_amplitude", "note_args": {"amplitude": f"{worst:.2f}"}, "note": f"наибольший всплеск x{worst:.2f}"})
    sawtooth, sawtooth_note = _sawtooth(live)
    if sawtooth is not None:
        factors.append({"code": "sawtooth", "value": round(sawtooth, 4), "score": round(sawtooth, 4), "weight": RISK_WEIGHTS["sawtooth"], "note_code": "note_sawtooth", "note_args": {"changes": sawtooth_note}, "note": f"{sawtooth_note} смен направления"})
    # Category comparison is deliberately absent in the first release.
    total_weight = sum(item["weight"] for item in factors)
    risk = round(100 * sum(item["score"] * item["weight"] for item in factors) / total_weight, 1) if total_weight else None
    observed_seconds = 0.0
    for row in live:
        start = row.get("observed_at")
        end = row.get("last_seen_at", start)
        if isinstance(start, dt.datetime) and isinstance(end, dt.datetime):
            observed_seconds += max(0.0, (end - start).total_seconds())
        else:
            observed_seconds += 60.0
    confidence = _clamp(min(len(live) / 60, 1.0) * min((observed_seconds / 3600) / 4, 1.0)) if live else 0.0
    if confidence < 0.5:
        warnings.append("данных мало, оценка предварительная")
        warning_codes.append({"code": "warn_low_confidence"})
    if risk is None:
        verdict = "nd"
    elif risk < 30:
        verdict = "green"
    elif risk <= 60:
        verdict = "yellow"
    else:
        verdict = "red"
    explanation = (
        "Индекс описывает необычность наблюдаемого поведения, а не вероятность накрутки. "
        "Решение остаётся за человеком. " + (" ".join(warnings) if warnings else "Данных достаточно для предварительного сравнения.")
    )
    return {"risk_score": risk, "confidence": round(confidence, 3), "verdict": verdict, "factors": factors, "warnings": warnings, "warning_codes": warning_codes, "explanation": explanation, "explanation_code": "explain_score", "samples_used": len(live)}


def history_payload(rows: list[dict], channel_login: str) -> list[dict]:
    result = []
    for row in rows:
        viewers = row.get("viewers")
        chatters = row.get("chatters")
        result.append({
            "ts": iso(row["observed_at"]),
            "is_live": bool(row.get("is_live")),
            "total": viewers,
            "authorized": min(chatters, viewers) if chatters is not None and viewers is not None else chatters,
            "guests": max(viewers - min(chatters, viewers), 0) if chatters is not None and viewers is not None else None,
            "chat_ratio": round(min(chatters / viewers, 1.0), 5) if chatters is not None and viewers else None,
            "raw_chat_ratio": round(chatters / viewers, 5) if chatters is not None and viewers else None,
        })
    return result
