"""Assemble every detector into one explainable detection report.

Pure orchestration: the caller (:mod:`app.services.detection`) loads rows from the
database and hands them over as plain data, so this module stays testable without
a database and without a network.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .score import DetectionReport, build_report
from .series import Point, live_points, median, values
from .types import Finding

UNAVAILABLE_DETAIL = {
    "series": "нет наблюдений зрителей в выбранном окне",
    "chat": "нет наблюдений чата в выбранном окне",
    "roster": "выборка чаттеров ещё не собрана",
    "intel": "нет данных о канале (followers, title, game)",
    "causes": "недостаточно данных для сравнения рекламных окон",
    "shapes": "меньше 30 минут наблюдений в окне",
    "chat_events": "анонимный клиент не читает сообщения чата",
}

#: `intel` needs two observations, not one: a follower burst or a title/game
#: change is a delta, so a single snapshot can never support one. Say that
#: instead of claiming the data is missing.
INTEL_MIN_OBSERVATIONS = 2
INTEL_DETAIL = (
    f"нужно минимум {INTEL_MIN_OBSERVATIONS} наблюдения канала в окне, чтобы посчитать прирост "
    "подписчиков и смену названия/категории"
)


@dataclass
class DetectionInput:
    """Everything the detectors may consume, already loaded and normalised."""

    channel: str = ""
    points: list[Point] = field(default_factory=list)
    samples: list[dict] = field(default_factory=list)
    intel: list[dict] = field(default_factory=list)
    roster: list[str] = field(default_factory=list)
    roster_roles: dict = field(default_factory=dict)
    accounts: dict[str, dict] = field(default_factory=dict)
    chat_events: list[dict] = field(default_factory=list)
    history: list[list[Point]] = field(default_factory=list)
    missing: list[dict] = field(default_factory=list)
    window_hours: float = 168.0
    samples_used: int = 0


def _cause_hints(breaks: list, intel: list[dict]) -> set[str]:
    hints: set[str] = set()
    for estimate in breaks:
        kind = getattr(estimate, "kind", "")
        if kind == "title_change":
            hints.add("title_change")
        elif kind == "game_change":
            hints.add("game_change")
        elif kind == "raid_influx":
            hints.add("raid_influx")
        elif kind == "combined":
            hints.update({"title_change", "game_change", "raid_influx"})
    for row in intel:
        if row.get("followers_jump"):
            hints.add("follower_burst")
    return hints


def _availability(data: DetectionInput) -> tuple[dict[str, bool], list[dict]]:
    live = live_points(data.points)
    has_chat = any(point.chatters is not None for point in data.points)
    available = {
        "series": bool(live),
        "chat": has_chat,
        "roster": bool(data.roster and data.accounts),
        "intel": len(data.intel) >= INTEL_MIN_OBSERVATIONS,
        "causes": bool(data.intel) and bool(live),
        "shapes": len(live) >= 30,
        "chat_events": bool(data.chat_events),
    }
    supplied = {item.get("metric"): item for item in data.missing}
    unavailable: list[dict] = list(data.missing)
    for metric, present in available.items():
        if present or metric in supplied:
            continue
        detail = INTEL_DETAIL if metric == "intel" else UNAVAILABLE_DETAIL[metric]
        unavailable.append({"metric": metric, "code": f"unavailable_{metric}", "detail": detail})
    return available, unavailable


def build(data: DetectionInput, *, now: dt.datetime | None = None) -> DetectionReport:
    """Run every detector and aggregate the findings into one report."""
    from . import accounts as accounts_mod
    from . import causes as causes_mod
    from . import chat as chat_mod
    from . import shapes as shapes_mod
    from . import spikes as spikes_mod

    points = data.points
    breaks = causes_mod.ad_break_estimates(points, samples=data.samples)
    shape_repeats = shapes_mod.repeat_shape_hints([*data.history, points]) if data.history else []
    hints = _cause_hints(breaks, data.intel)

    findings: list[Finding] = []
    findings.extend(spikes_mod.spike_findings(points, cause_hints=hints, shape_repeats=shape_repeats))
    findings.extend(shapes_mod.shape_findings(points, history=data.history))
    findings.extend(chat_mod.chat_findings(points, chat_events=data.chat_events))

    viewer_median = median(values(points, "viewers"))
    findings.extend(
        accounts_mod.account_findings(
            data.roster,
            data.accounts,
            follower_history=data.intel,
            viewer_median=viewer_median,
            observed_minutes=float(len(live_points(points))),
            now=now,
        )
    )
    comparison = causes_mod.compare_ad_vs_nonad(points, breaks)
    if comparison.get("finding") is not None:
        findings.append(comparison["finding"])

    availability, unavailable = _availability(data)
    findings.sort(key=lambda item: item.weight * item.score, reverse=True)
    report = build_report(
        channel=data.channel,
        points=points,
        samples_used=data.samples_used,
        findings=findings,
        availability=availability,
        unavailable=unavailable,
        ad_vs_nonad={key: value for key, value in comparison.items() if key != "finding"},
        window_hours=data.window_hours,
        now=now,
    )
    report.confidence_parts["detector_counts"] = {"findings": len(findings)}
    return report
