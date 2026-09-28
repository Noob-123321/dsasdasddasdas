"""Load detection inputs from the database and build the detection report.

This is the only bridge between persistence and the pure ``app.detect`` package:
the detectors never import SQLAlchemy, and this module never computes a signal.
Databases that predate migration 0005 (for example the untouched live
``data/tvb.db``) degrade instead of failing: the missing tables are reported as
unavailable metrics, which lowers confidence, exactly as the spec requires.
"""
from __future__ import annotations

import bisect
import datetime as dt

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ..clock import iso, utcnow
from ..detect.pipeline import DetectionInput, build
from ..detect.series import expand_series, median
from ..models import Channel, ChannelIntel, ChatterAccount, ChatterSnapshot, Sample

DEFAULT_WINDOW_HOURS = 168.0
PREVIOUS_STREAMS = 3

SAMPLE_NOTE = (
    "Выборка — это случайный алфавитный срез до 100 логинов из CommunityTab, "
    "а не весь чат канала. По ней считаются распределения (возраст аккаунтов, "
    "подписчики), но нельзя отслеживать конкретных людей."
)


def _rows(db: Session, statement, missing: list[dict], metric: str, detail: str) -> list:
    try:
        return list(db.scalars(statement))
    except OperationalError:
        if not any(item.get("metric") == metric for item in missing):
            missing.append({"metric": metric, "code": f"missing_table_{metric}", "detail": detail})
        return []


def _viewer_index(samples: list[Sample]) -> tuple[list[dt.datetime], list[int]]:
    stamps: list[dt.datetime] = []
    viewers: list[int] = []
    for row in sorted(samples, key=lambda item: item.observed_at):
        if row.viewer_count is None:
            continue
        stamps.append(row.observed_at)
        viewers.append(row.viewer_count)
    return stamps, viewers


def _median_between(stamps: list[dt.datetime], viewers: list[int], start: dt.datetime, end: dt.datetime) -> float | None:
    left = bisect.bisect_left(stamps, start)
    right = bisect.bisect_right(stamps, end)
    if right <= left:
        return None
    return median(viewers[left:right])


def _stream_windows(intel: list[ChannelIntel]) -> list[dict]:
    windows: list[dict] = []
    for row in intel:
        if not row.stream_id:
            continue
        if windows and windows[-1]["stream_id"] == row.stream_id:
            windows[-1]["end"] = max(windows[-1]["end"], row.last_seen_at)
            continue
        windows.append({"stream_id": row.stream_id, "start": row.observed_at, "end": row.last_seen_at})
    return windows


def detection_input(db: Session, login: str, *, hours: float = DEFAULT_WINDOW_HOURS, now: dt.datetime | None = None) -> DetectionInput:
    """Load everything the detectors can use for one channel and one window."""
    moment = now or utcnow()
    since = moment - dt.timedelta(hours=hours)
    missing: list[dict] = []

    samples = _rows(
        db,
        select(Sample).where(Sample.channel_login == login, Sample.observed_at >= since).order_by(Sample.observed_at.asc()),
        missing,
        "detection_tables",
        "таблицы детекции отсутствуют: примените alembic upgrade head",
    )
    intel_rows = _rows(
        db,
        select(ChannelIntel).where(ChannelIntel.channel_login == login, ChannelIntel.observed_at >= since).order_by(ChannelIntel.observed_at.asc()),
        missing,
        "detection_tables",
        "таблицы детекции отсутствуют: примените alembic upgrade head",
    )
    snapshots = _rows(
        db,
        select(ChatterSnapshot).where(ChatterSnapshot.channel_login == login).order_by(ChatterSnapshot.observed_at.desc()).limit(1),
        missing,
        "detection_tables",
        "таблицы детекции отсутствуют: примените alembic upgrade head",
    )

    stamps, viewers = _viewer_index(samples)
    intel_payload: list[dict] = []
    for row in intel_rows:
        intel_payload.append(
            {
                "observed_at": row.observed_at,
                "followers": row.followers_count,
                "stream_id": row.stream_id,
                "is_live": bool(row.is_live),
                "game": row.game,
                "title": row.title,
                "viewers_median": _median_between(stamps, viewers, row.observed_at, row.last_seen_at),
            }
        )
    for previous, current in zip(intel_payload, intel_payload[1:]):
        first, last = previous.get("followers"), current.get("followers")
        if first and last and last >= first * 1.5:
            current["followers_jump"] = True

    roster: list[str] = []
    roles: dict = {}
    if snapshots:
        roster = [str(item).lower() for item in (snapshots[0].roster or []) if item]
        roles = dict(snapshots[0].roles or {})
    accounts: dict[str, dict] = {}
    if roster:
        rows = _rows(
            db,
            select(ChatterAccount).where(ChatterAccount.login.in_(roster)),
            missing,
            "detection_tables",
            "таблицы детекции отсутствуют: примените alembic upgrade head",
        )
        for row in rows:
            accounts[row.login] = {
                "id": row.account_id,
                "created_at": row.twitch_created_at,
                "followers": row.followers_count,
                "last_broadcast_at": row.last_broadcast_at,
                "source": row.source,
            }

    history: list[list] = []
    # `reversed()` returns an iterator, which is not sliceable. Slice first,
    # then reverse, so the newest previous streams come first.
    for window in list(reversed(_stream_windows(intel_rows)))[:-1][::-1][:PREVIOUS_STREAMS]:
        if window["end"] >= moment:
            continue
        rows = [row for row in samples if window["start"] <= row.observed_at <= window["end"]]
        if rows:
            history.append(expand_series(rows))

    data = DetectionInput(
        channel=login,
        points=expand_series(samples),
        samples=[
            {
                "observed_at": row["observed_at"],
                "title": row.get("title"),
                "game": row.get("game"),
                "followers_count": row.get("followers"),
            }
            for row in intel_payload
        ],
        intel=intel_payload,
        roster=roster,
        roster_roles=roles,
        accounts=accounts,
        chat_events=[],
        history=history,
        missing=missing,
        window_hours=float(hours),
        samples_used=len(samples),
    )
    return data


def detection_report(db: Session, login: str, *, hours: float = DEFAULT_WINDOW_HOURS, now: dt.datetime | None = None) -> dict:
    """Full detection report for one channel (see ``docs/DETECTION_SPEC.md`` §5)."""
    moment = now or utcnow()
    channel = db.get(Channel, login)
    data = detection_input(db, login, hours=hours, now=moment)
    report = build(data, now=moment).to_dict()
    report["channel"] = login
    report["title"] = channel.latest_title if channel else None
    report["game"] = channel.latest_game if channel else None
    report["is_live"] = bool(channel.latest_is_live) if channel else False
    report["points"] = [
        {"ts": iso(point.ts), "total": point.viewers, "chatters": point.chatters}
        for point in data.points
    ]
    return report


def chatters_payload(db: Session, login: str, *, limit: int = 100) -> dict:
    """The sampled roster plus per-account enrichment, so the user sees evidence."""
    missing: list[dict] = []
    snapshots = _rows(
        db,
        select(ChatterSnapshot).where(ChatterSnapshot.channel_login == login).order_by(ChatterSnapshot.observed_at.desc()).limit(1),
        missing,
        "detection_tables",
        "таблицы детекции отсутствуют: примените alembic upgrade head",
    )
    snapshot = snapshots[0] if snapshots else None
    roster = [str(item).lower() for item in (snapshot.roster or []) if item] if snapshot else []
    accounts = []
    if roster:
        rows = _rows(db, select(ChatterAccount).where(ChatterAccount.login.in_(roster)), missing, "detection_tables", "таблицы детекции отсутствуют")
        today = utcnow()
        for row in sorted(rows, key=lambda item: item.login):
            age_days = (today - row.twitch_created_at).days if row.twitch_created_at else None
            accounts.append(
                {
                    "login": row.login,
                    "account_id": row.account_id,
                    "created_at": iso(row.twitch_created_at),
                    "account_age_days": age_days,
                    "followers": row.followers_count,
                    "last_broadcast_at": iso(row.last_broadcast_at),
                    "enriched_at": iso(row.enriched_at),
                    "source": row.source,
                }
            )
    enriched = [item["enriched_at"] for item in accounts if item["enriched_at"]]
    return {
        "channel": login,
        "sample": None
        if snapshot is None
        else {
            "observed_at": iso(snapshot.observed_at),
            "stream_id": snapshot.stream_id,
            "count": snapshot.count,
            "sampled": snapshot.sampled,
            "roles": snapshot.roles or {},
            "roster": roster[:limit],
            "enriched_at": iso(snapshot.enriched_at),
        },
        "accounts": accounts[:limit],
        "enrichment": {
            "sample_size": len(roster),
            "enriched": len(accounts),
            "oldest_enriched_at": min(enriched) if enriched else None,
            "newest_enriched_at": max(enriched) if enriched else None,
            "missing": missing,
        },
        "note": SAMPLE_NOTE,
    }
