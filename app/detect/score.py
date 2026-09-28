"""Aggregate detector findings into the explainable detection report.

The wording rules from the product carry over unchanged: the index describes how
unusual the observed behaviour is, never the probability of bots, and a metric
whose input was missing lowers ``confidence`` instead of scoring 0 as if it had
passed.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field

from ..clock import iso
from .series import Point, live_points
from .types import Finding, clamp

GREEN_MAX = 30.0
YELLOW_MAX = 60.0

DISCLAIMER = "оценка описывает необычность поведения, а не вероятность ботов"
DISCLAIMER_CODE = "detect_not_probability"

# The inputs the detectors need; a missing one lowers confidence and is reported.
METRICS = ("series", "chat", "roster", "intel", "causes", "shapes", "chat_events")


@dataclass
class DetectionReport:
    channel: str
    risk_score: float | None
    confidence: float
    verdict: str
    factors: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    warning_codes: list[dict] = field(default_factory=list)
    unavailable: list[dict] = field(default_factory=list)
    series: dict = field(default_factory=dict)
    ad_vs_nonad: dict = field(default_factory=dict)
    confidence_parts: dict = field(default_factory=dict)
    generated_at: str | None = None
    window_hours: float = 0.0
    explanation_code: str = "detect_explain"
    explanation: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def verdict_for(risk: float | None) -> str:
    if risk is None:
        return "nd"
    if risk < GREEN_MAX:
        return "green"
    if risk <= YELLOW_MAX:
        return "yellow"
    return "red"


def weighted_risk(findings: list[Finding]) -> float | None:
    """Weighted mean of the fired findings' scores, scaled to 0..100."""
    total = sum(max(finding.weight, 0.0) for finding in findings)
    if total <= 0:
        return 0.0 if findings else None
    score = sum(clamp(finding.score) * max(finding.weight, 0.0) for finding in findings)
    return round(100.0 * score / total, 1)


def confidence_for(samples_used: int, observed_minutes: float, availability: dict[str, bool]) -> tuple[float, dict]:
    """Confidence in the report: coverage of data, not strength of the signal."""
    data_factor = clamp(min(observed_minutes, 240.0) / 240.0)
    sample_factor = clamp(min(samples_used, 60) / 60.0)
    total = [name for name in METRICS if name in availability]
    present = [name for name in total if availability.get(name)]
    available_ratio = (len(present) / len(total)) if total else 0.0
    value = clamp((0.65 * data_factor + 0.35 * sample_factor) * available_ratio)
    return round(value, 3), {
        "data_factor": round(data_factor, 3),
        "sample_factor": round(sample_factor, 3),
        "available_ratio": round(available_ratio, 3),
        "metrics_present": present,
        "metrics_missing": [name for name in total if not availability.get(name)],
    }


def series_meta(points: list[Point], samples_used: int) -> dict:
    live = [point for point in points if point.has_data]
    return {
        "expanded_points": len(points),
        "live_points": len(live),
        "gap_points": len(points) - len(live),
        "samples_used": samples_used,
        "observed_minutes": float(len(live)),
        "from": iso(points[0].ts) if points else None,
        "to": iso(points[-1].ts) if points else None,
        "minute_seconds": 60,
    }


def build_report(
    *,
    channel: str,
    points: list[Point],
    samples_used: int,
    findings: list[Finding],
    availability: dict[str, bool],
    unavailable: list[dict],
    ad_vs_nonad: dict,
    window_hours: float,
    now: dt.datetime | None = None,
) -> DetectionReport:
    live = live_points(points)
    meta = series_meta(points, samples_used)
    confidence, parts = confidence_for(samples_used, meta["observed_minutes"], availability)
    risk = (weighted_risk(findings) if findings else 0.0) if live else None
    warnings = [f"{DISCLAIMER}."]
    warning_codes: list[dict] = [{"code": DISCLAIMER_CODE, "args": {}}]
    for item in unavailable:
        metric = item.get("metric", "?")
        detail = item.get("detail") or "нет данных"
        warnings.append(f"{metric}: {detail}")
        warning_codes.append({"code": item.get("code") or f"unavailable_{metric}", "args": {"detail": detail}})
    if not live:
        warnings.append("нет наблюдений в выбранном окне")
        warning_codes.append({"code": "detect_no_observations", "args": {}})
    elif confidence < 0.5:
        warnings.append("данных мало, оценка предварительная")
        warning_codes.append({"code": "warn_low_confidence", "args": {}})
    factors = [finding.to_dict() for finding in findings]
    explanation = (
        "Детекция сопоставляет формы кривой, поведение чата и выборку аккаунтов "
        "с собственными наблюдениями канала. " + DISCLAIMER + "."
    )
    return DetectionReport(
        channel=channel,
        risk_score=risk,
        confidence=confidence,
        verdict=verdict_for(risk),
        factors=factors,
        warnings=warnings,
        warning_codes=warning_codes,
        unavailable=unavailable,
        series=meta,
        ad_vs_nonad=ad_vs_nonad,
        confidence_parts=parts,
        generated_at=iso(now or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)),
        window_hours=window_hours,
        explanation=explanation,
    )
