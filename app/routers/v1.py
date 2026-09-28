"""Public API v1 authenticated with a child tvs_ key."""
from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analytics import derived_metrics, history_payload
from ..clock import iso, utcnow
from ..db import get_db
from ..deps import ApiPrincipal, api_principal
from ..models import Channel, ProfileChannel, Sample, ScoreSnapshot, Spike
from ..security import profile_can_access
from ..services.detection import chatters_payload, detection_report

router = APIRouter(prefix="/api/v1", tags=["api-v1"])


def _channel_or_404(principal: ApiPrincipal, login: str, db: Session) -> Channel:
    login = login.lower()
    member = db.scalar(select(ProfileChannel).where(ProfileChannel.profile_id == principal.profile.id, ProfileChannel.channel_login == login))
    if member is None or not profile_can_access(principal.profile, login):
        raise HTTPException(status_code=404, detail={"code": "channel_not_found", "message": "Канал не найден"})
    channel = db.get(Channel, login)
    if channel is None:
        raise HTTPException(status_code=404, detail={"code": "channel_not_found", "message": "Канал не найден"})
    return channel


def _score(db: Session, login: str) -> dict | None:
    row = db.scalar(select(ScoreSnapshot).where(ScoreSnapshot.channel_login == login).order_by(ScoreSnapshot.computed_at.desc()).limit(1))
    if row is None:
        return None
    return {"risk_score": row.risk_score, "verdict": row.verdict, "confidence": row.confidence, "factors": row.factors or [], "warnings": row.warnings or [], "warning_codes": row.warning_codes, "explanation": row.explanation, "computed_at": iso(row.computed_at)}


@router.get("/me")
def api_me(principal: Annotated[ApiPrincipal, Depends(api_principal)]):
    return {"ok": True, "data": {"profile_id": principal.profile.id, "prefix": principal.api_key.prefix, "scopes": principal.api_key.scopes, "created_at": iso(principal.api_key.created_at), "parent_expires_at": iso(principal.parent.expires_at)}}


@router.get("/channels/{login}/snapshot")
def snapshot(login: str, principal: Annotated[ApiPrincipal, Depends(api_principal)], db: Session = Depends(get_db)):
    channel = _channel_or_404(principal, login, db)
    return {"ok": True, "data": {"channel": channel.login, **derived_metrics(channel), "score": _score(db, channel.login)}, "meta": {"request_id": "api"}}


@router.get("/channels/{login}/history")
def history(login: str, principal: Annotated[ApiPrincipal, Depends(api_principal)], hours: int = Query(default=24, ge=1, le=24 * 365), db: Session = Depends(get_db)):
    login = login.lower()
    _channel_or_404(principal, login, db)
    since = utcnow() - dt.timedelta(hours=hours)
    rows = list(db.scalars(select(Sample).where(Sample.channel_login == login, Sample.observed_at >= since).order_by(Sample.observed_at)))
    points = history_payload([{"observed_at": row.observed_at, "is_live": row.is_live, "viewers": row.viewer_count, "chatters": row.chatters_count} for row in rows], login)
    return {"ok": True, "data": points, "meta": {"count": len(points), "request_id": "api"}}


@router.get("/channels/{login}/anomalies")
def anomalies(login: str, principal: Annotated[ApiPrincipal, Depends(api_principal)], db: Session = Depends(get_db)):
    login = login.lower()
    _channel_or_404(principal, login, db)
    rows = list(db.scalars(select(Spike).where(Spike.channel_login == login).order_by(Spike.peak_at.desc()).limit(100)))
    return {"ok": True, "data": [{"type": "viewer_spike", "started_at": iso(row.started_at), "peak_at": iso(row.peak_at), "ended_at": iso(row.ended_at), "baseline": row.baseline_viewers, "peak": row.peak_viewers, "amplitude": row.amplitude, "shape": row.shape, "is_instant": row.is_instant, "confidence": row.confidence, "notes": row.notes} for row in rows], "meta": {"request_id": "api"}}


@router.get("/channels/{login}/detection")
def detection(
    login: str,
    principal: Annotated[ApiPrincipal, Depends(api_principal)],
    hours: int = Query(default=168, ge=1, le=24 * 365),
    db: Session = Depends(get_db),
):
    """Explainable bot/view-farm detection report (spec §5)."""
    channel = _channel_or_404(principal, login, db)
    return {"ok": True, "data": detection_report(db, channel.login, hours=float(hours)), "meta": {"request_id": "api"}}


@router.get("/channels/{login}/chatters")
def chatters(login: str, principal: Annotated[ApiPrincipal, Depends(api_principal)], db: Session = Depends(get_db)):
    """Sampled roster plus per-account enrichment, so the caller sees the evidence."""
    channel = _channel_or_404(principal, login, db)
    return {"ok": True, "data": chatters_payload(db, channel.login), "meta": {"request_id": "api"}}


@router.get("/channels/{login}/summary")
def summary(login: str, principal: Annotated[ApiPrincipal, Depends(api_principal)], db: Session = Depends(get_db)):
    channel = _channel_or_404(principal, login, db)
    return {"ok": True, "data": {"channel": channel.login, "score": _score(db, channel.login), "snapshot": derived_metrics(channel)}, "meta": {"request_id": "api"}}


@router.get("/portfolio")
def portfolio(principal: Annotated[ApiPrincipal, Depends(api_principal)], db: Session = Depends(get_db)):
    members = list(db.scalars(select(ProfileChannel).where(ProfileChannel.profile_id == principal.profile.id)))
    data = []
    for member in members:
        channel = db.get(Channel, member.channel_login)
        if channel is not None:
            data.append({"channel": channel.login, **derived_metrics(channel), "score": _score(db, channel.login)})
    return {"ok": True, "data": data, "meta": {"count": len(data), "request_id": "api"}}


@router.post("/batch/snapshots")
def batch_snapshots(principal: Annotated[ApiPrincipal, Depends(api_principal)], payload: dict, db: Session = Depends(get_db)):
    logins = payload.get("logins") if isinstance(payload, dict) else None
    if not isinstance(logins, list) or not logins or len(logins) > 50:
        raise HTTPException(status_code=422, detail={"code": "validation_error", "message": "Передайте от 1 до 50 logins"})
    results, errors = [], []
    for item in logins:
        try:
            channel = _channel_or_404(principal, str(item), db)
            results.append({"channel": channel.login, **derived_metrics(channel)})
        except HTTPException as exc:
            errors.append({"channel": str(item), "error": exc.detail})
    return {"ok": True, "data": {"results": results, "errors": errors}, "meta": {"request_id": "api"}}
