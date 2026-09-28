"""Authenticated profile, portfolio and API-key routes."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import ipaddress
import json
import secrets
import urllib.error
import urllib.request
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analytics import _sample_dict, derived_metrics, history_payload
from ..clock import iso, utcnow
from ..config import get_settings
from ..db import SessionLocal, get_db
from ..deps import BrowserPrincipal, profile_principal
from ..models import (
    AlertEvent,
    AlertRule,
    ApiKey,
    Channel,
    ProfileChannel,
    Sample,
    ScoreSnapshot,
    Spike,
    Webhook,
    WebhookDelivery,
)
from ..poller import Poller
from ..security import (
    create_api_key,
    decrypt_secret,
    encrypt_secret,
    normalize_login,
    parse_channel_input,
    profile_can_access,
    request_id,
)
from ..services.audit import record_audit
from ..services.detection import chatters_payload, detection_report
from ..services.reporting import csv_bytes, html_report, report_digest, simple_pdf

router = APIRouter(prefix="/api/profile", tags=["profile"])


class ChannelAddRequest(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)


class ApiKeyRequest(BaseModel):
    label: str = Field(default="API key", min_length=1, max_length=128)


class WebhookRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    secret: str = Field(min_length=16, max_length=256)
    events: list[str] = Field(default_factory=lambda: ["anomaly.detected"])
    enabled: bool = True


class AlertRuleRequest(BaseModel):
    type: str
    channels: list[str] = Field(default_factory=list)
    threshold: float = 0
    window_seconds: int = Field(default=300, ge=30, le=86400)
    cooldown_seconds: int = Field(default=600, ge=30, le=86400)
    enabled: bool = True


def _ensure_member(principal: BrowserPrincipal, login: str, db: Session) -> Channel:
    channel = db.get(Channel, login)
    if channel is None:
        raise HTTPException(status_code=404, detail={"code": "channel_not_found", "message": "Канал не найден в портфеле"})
    member = db.scalar(select(ProfileChannel).where(ProfileChannel.profile_id == principal.profile.id, ProfileChannel.channel_login == login))
    if member is None or not profile_can_access(principal.profile, login):
        raise HTTPException(status_code=404, detail={"code": "channel_not_found", "message": "Канал не найден в портфеле"})
    return channel


def _score_for(db: Session, login: str) -> dict | None:
    row = db.scalar(select(ScoreSnapshot).where(ScoreSnapshot.channel_login == login).order_by(ScoreSnapshot.computed_at.desc()).limit(1))
    if row is None:
        return None
    return {"risk_score": row.risk_score, "confidence": row.confidence, "verdict": row.verdict, "factors": row.factors or [], "warnings": row.warnings or [], "warning_codes": row.warning_codes, "explanation": row.explanation, "computed_at": iso(row.computed_at)}


@router.get("/overview")
def overview(principal: BrowserPrincipal = Depends(profile_principal), db: Session = Depends(get_db)):
    members = list(db.scalars(select(ProfileChannel).where(ProfileChannel.profile_id == principal.profile.id).order_by(ProfileChannel.added_at.asc())))
    items = []
    for member in members:
        if not profile_can_access(principal.profile, member.channel_login):
            continue
        channel = db.get(Channel, member.channel_login)
        if channel is None:
            continue
        recent_samples = list(db.scalars(select(Sample).where(Sample.channel_login == channel.login).order_by(Sample.observed_at.desc()).limit(12)))
        trend = [{"ts": iso(row.observed_at), "is_live": row.is_live, "total": row.viewer_count, "chat": row.chatters_count} for row in reversed(recent_samples)]
        item = {"login": channel.login, **derived_metrics(channel), "score": _score_for(db, channel.login), "trend": trend, "added_at": iso(member.added_at)}
        items.append(item)
    return {"ok": True, "data": {
        "profile": {"id": principal.profile.id, "label": principal.profile.label, "unlimited": principal.profile.unlimited},
        "channels": items,
        "kpis": {
            "channels": len(items),
            "total_viewers": sum((item["total_viewers"] or 0) for item in items),
            "flagged": sum(1 for item in items if (item.get("score") or {}).get("verdict") == "red"),
            "live": sum(1 for item in items if item.get("is_live")),
        },
    }}


@router.post("/channels")
def add_channels(payload: ChannelAddRequest, request: Request, principal: BrowserPrincipal = Depends(profile_principal), db: Session = Depends(get_db)):
    accepted, invalid = parse_channel_input(payload.text)
    added, duplicates, rejected = [], [], []
    for login in accepted:
        if not profile_can_access(principal.profile, login):
            rejected.append(login)
            continue
        channel = db.get(Channel, login)
        if channel is None:
            channel = Channel(login=login, display_name=login, is_active=True, track_reason="profile")
            db.add(channel)
            db.flush()
        member = db.scalar(select(ProfileChannel).where(ProfileChannel.profile_id == principal.profile.id, ProfileChannel.channel_login == login))
        if member is not None:
            duplicates.append(login)
        else:
            db.add(ProfileChannel(profile_id=principal.profile.id, channel_login=login, source="profile"))
            added.append(login)
    record_audit(db, actor=f"profile:{principal.profile.id}", action="profile.channels.add", request_id=request_id(), details={"added": added, "duplicates": duplicates, "rejected": rejected, "invalid": invalid})
    db.commit()
    # Give a newly added channel an immediate first observation. Subsequent
    # observations stay in the background poller.
    for login in added:
        try:
            Poller(SessionLocal, get_settings()).poll_channel(login)
        except Exception:
            pass
    return {"ok": True, "data": {"added": added, "duplicates": duplicates, "rejected": rejected, "invalid": invalid}}


@router.delete("/channels/{login}")
def remove_channel(login: str, request: Request, principal: BrowserPrincipal = Depends(profile_principal), db: Session = Depends(get_db)):
    login = login.lower()
    member = db.scalar(select(ProfileChannel).where(ProfileChannel.profile_id == principal.profile.id, ProfileChannel.channel_login == login))
    if member is None:
        raise HTTPException(status_code=404, detail={"code": "channel_not_found", "message": "Канал не найден"})
    db.delete(member)
    record_audit(db, actor=f"profile:{principal.profile.id}", action="profile.channels.remove", object_id=login, request_id=request_id())
    db.commit()
    return {"ok": True}


@router.get("/channels/{login}/snapshot")
def channel_snapshot(login: str, principal: BrowserPrincipal = Depends(profile_principal), db: Session = Depends(get_db)):
    channel = _ensure_member(principal, login.lower(), db)
    return {"ok": True, "data": {"channel": channel.login, **derived_metrics(channel), "score": _score_for(db, channel.login)}}


@router.get("/channels/{login}/history")
def channel_history(login: str, principal: BrowserPrincipal = Depends(profile_principal), hours: int = Query(default=24, ge=1, le=24 * 365), db: Session = Depends(get_db)):
    login = login.lower()
    _ensure_member(principal, login, db)
    since = utcnow() - dt.timedelta(hours=hours)
    rows = list(db.scalars(select(Sample).where(Sample.channel_login == login, Sample.observed_at >= since).order_by(Sample.observed_at.asc())))
    points = [{"observed_at": _sample_dict(row)["observed_at"], "last_seen_at": _sample_dict(row)["last_seen_at"], "is_live": row.is_live, "viewers": row.viewer_count, "chatters": row.chatters_count, "repeat_count": row.repeat_count} for row in rows]
    return {"ok": True, "data": {"channel": login, "points": history_payload([{"observed_at": point["observed_at"], "is_live": point["is_live"], "viewers": point["viewers"], "chatters": point["chatters"]} for point in points], login), "raw": points, "score": _score_for(db, login)}}


@router.get("/channels/{login}/anomalies")
def anomalies(login: str, principal: BrowserPrincipal = Depends(profile_principal), db: Session = Depends(get_db)):
    login = login.lower()
    _ensure_member(principal, login, db)
    rows = list(db.scalars(select(Spike).where(Spike.channel_login == login).order_by(Spike.peak_at.desc()).limit(100)))
    return {"ok": True, "data": [{"started_at": iso(row.started_at), "peak_at": iso(row.peak_at), "ended_at": iso(row.ended_at), "baseline": row.baseline_viewers, "peak": row.peak_viewers, "amplitude": row.amplitude, "shape": row.shape, "is_instant": row.is_instant, "confidence": row.confidence, "notes": row.notes} for row in rows]}


@router.get("/channels/{login}/detection")
def channel_detection(
    login: str,
    principal: BrowserPrincipal = Depends(profile_principal),
    hours: int = Query(default=168, ge=1, le=24 * 365),
    db: Session = Depends(get_db),
):
    channel = _ensure_member(principal, login.lower(), db)
    return {"ok": True, "data": detection_report(db, channel.login, hours=float(hours))}


@router.get("/channels/{login}/chatters")
def channel_chatters(login: str, principal: BrowserPrincipal = Depends(profile_principal), db: Session = Depends(get_db)):
    channel = _ensure_member(principal, login.lower(), db)
    return {"ok": True, "data": chatters_payload(db, channel.login)}


@router.get("/api-keys")
def list_api_keys(principal: BrowserPrincipal = Depends(profile_principal), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(ApiKey).where(ApiKey.profile_id == principal.profile.id, ApiKey.revoked_at.is_(None)).order_by(ApiKey.created_at.desc())))
    return {"ok": True, "data": [{"id": row.id, "label": row.label, "prefix": row.prefix, "scopes": row.scopes, "created_at": iso(row.created_at), "expires_at": iso(row.expires_at), "last_used_at": iso(row.last_used_at), "requests_used": row.requests_used, "status": "active" if not row.revoked_at else "revoked"} for row in rows]}


@router.post("/api-keys")
def create_child_api_key(payload: ApiKeyRequest, request: Request, principal: BrowserPrincipal = Depends(profile_principal), db: Session = Depends(get_db)):
    row, raw = create_api_key(db, get_settings(), profile_id=principal.profile.id, parent_token_id=principal.access_token.id, label=payload.label)
    record_audit(db, actor=f"profile:{principal.profile.id}", action="api_key.create", object_id=row.id, request_id=request_id(), details={"label": payload.label})
    db.commit()
    return {"ok": True, "data": {"id": row.id, "label": row.label, "prefix": row.prefix, "key": raw, "scopes": row.scopes, "created_at": iso(row.created_at)}}


@router.post("/api-keys/{key_id}/reveal")
def reveal_child_api_key(key_id: str, request: Request, principal: BrowserPrincipal = Depends(profile_principal), db: Session = Depends(get_db)):
    row = db.get(ApiKey, key_id)
    if row is None or row.profile_id != principal.profile.id:
        raise HTTPException(status_code=404, detail={"code": "key_not_found", "message": "API-ключ не найден"})
    try:
        raw = decrypt_secret(row.encrypted_secret, get_settings())
    except ValueError as exc:
        raise HTTPException(status_code=503, detail={"code": "secret_unavailable", "message": str(exc)}) from exc
    record_audit(db, actor=f"profile:{principal.profile.id}", action="api_key.reveal", object_id=row.id, request_id=request_id(), details={"prefix": row.prefix})
    db.commit()
    return {"ok": True, "data": {"id": row.id, "prefix": row.prefix, "key": raw, "warning": "Секрет можно скопировать, но не отправляйте его в URL."}}


@router.post("/api-keys/{key_id}/revoke")
def revoke_child_api_key(key_id: str, principal: BrowserPrincipal = Depends(profile_principal), db: Session = Depends(get_db)):
    row = db.get(ApiKey, key_id)
    if row is None or row.profile_id != principal.profile.id:
        raise HTTPException(status_code=404, detail={"code": "key_not_found", "message": "API-ключ не найден"})
    row.revoked_at = utcnow()
    record_audit(db, actor=f"profile:{principal.profile.id}", action="api_key.revoke", object_id=row.id, request_id=request_id())
    db.commit()
    return {"ok": True}


@router.get("/usage")
def usage(principal: BrowserPrincipal = Depends(profile_principal), db: Session = Depends(get_db)):
    keys = list(db.scalars(select(ApiKey).where(ApiKey.profile_id == principal.profile.id)))
    return {"ok": True, "data": {"api_keys": len([key for key in keys if not key.revoked_at]), "requests": sum(key.requests_used for key in keys), "quota": 1_000_000}}


@router.get("/channels/{login}/export")
def export_channel(login: str, principal: BrowserPrincipal = Depends(profile_principal), hours: int = Query(default=24, ge=1, le=24 * 365), db: Session = Depends(get_db)):
    login = login.lower()
    _ensure_member(principal, login, db)
    since = utcnow() - dt.timedelta(hours=hours)
    rows = list(db.scalars(select(Sample).where(Sample.channel_login == login, Sample.observed_at >= since).order_by(Sample.observed_at)))
    points = history_payload([{"observed_at": row.observed_at, "is_live": row.is_live, "viewers": row.viewer_count, "chatters": row.chatters_count} for row in rows], login)
    body = csv_bytes(points)
    return Response(content=body, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="tvs_{login}_{hours}h.csv"'})


@router.get("/channels/{login}/report")
def channel_report(login: str, principal: BrowserPrincipal = Depends(profile_principal), format: str = Query(default="html", pattern="^(html|pdf)$"), hours: int = Query(default=24, ge=1, le=24 * 365), db: Session = Depends(get_db)):
    login = login.lower()
    _ensure_member(principal, login, db)
    since = utcnow() - dt.timedelta(hours=hours)
    rows = list(db.scalars(select(Sample).where(Sample.channel_login == login, Sample.observed_at >= since)))
    points = history_payload([{"observed_at": row.observed_at, "is_live": row.is_live, "viewers": row.viewer_count, "chatters": row.chatters_count} for row in rows], login)
    score = _score_for(db, login) or {}
    peak = max((p.get("total") or 0 for p in points), default=0)
    average = round(sum((p.get("total") or 0) for p in points) / len(points), 2) if points else 0
    data = {"period": f"{since.isoformat()} — {utcnow().isoformat()}", "summary": {"Замеров": len(points), "Пик": peak, "Среднее": average}, "score": score}
    digest = report_digest(data)
    data["digest"] = digest
    if format == "html":
        return HTMLResponse(content=html_report(login, data), headers={"X-Report-SHA256": digest})
    lines = [f"TVS Analytics report: {login}", f"Period: {data['period']}", f"Samples: {len(points)}", f"Peak: {data['summary']['Пик']}", f"SHA-256: {digest}", "", "Score factors:"]
    lines.extend(f"- {factor.get('code')}: {factor.get('note')}" for factor in score.get("factors", []))
    return Response(content=simple_pdf(login, lines), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="tvs_{login}_report.pdf"', "X-Report-SHA256": digest})


@router.get("/alerts")
def list_alerts(principal: BrowserPrincipal = Depends(profile_principal), db: Session = Depends(get_db)):
    rules = list(db.scalars(select(AlertRule).where(AlertRule.profile_id == principal.profile.id).order_by(AlertRule.created_at.desc())))
    events = list(db.scalars(select(AlertEvent).where(AlertEvent.profile_id == principal.profile.id).order_by(AlertEvent.created_at.desc()).limit(50)))
    return {"ok": True, "data": {
        "rules": [{"id": row.id, "type": row.type, "channels": row.channels or [], "threshold": row.threshold, "window_seconds": row.window_seconds, "cooldown_seconds": row.cooldown_seconds, "enabled": row.enabled, "created_at": iso(row.created_at)} for row in rules],
        "events": [{"id": row.id, "rule_id": row.rule_id, "type": row.type, "channel_login": row.channel_login, "severity": row.severity, "payload": row.payload, "created_at": iso(row.created_at), "read_at": iso(row.read_at)} for row in events],
    }}


@router.post("/alerts")
def create_alert(payload: AlertRuleRequest, request: Request, principal: BrowserPrincipal = Depends(profile_principal), db: Session = Depends(get_db)):
    allowed_types = {"viewer_spike", "ratio_collapse", "score_threshold", "stream_offline", "stale_data"}
    if payload.type not in allowed_types:
        raise HTTPException(status_code=422, detail={"code": "validation_error", "message": "Неизвестный тип правила"})
    channels = []
    for item in payload.channels:
        try:
            login = normalize_login(item)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "validation_error", "message": str(exc)}) from exc
        if profile_can_access(principal.profile, login):
            channels.append(login)
    row = AlertRule(id=f"rul_{secrets.token_hex(8)}", profile_id=principal.profile.id, type=payload.type, channels=channels, threshold=payload.threshold, window_seconds=payload.window_seconds, cooldown_seconds=payload.cooldown_seconds, enabled=payload.enabled)
    db.add(row)
    record_audit(db, actor=f"profile:{principal.profile.id}", action="alert.create", object_id=row.id, request_id=request_id(), details={"type": row.type})
    db.commit()
    return {"ok": True, "data": {"id": row.id, "type": row.type, "channels": channels, "threshold": row.threshold, "window_seconds": row.window_seconds, "cooldown_seconds": row.cooldown_seconds, "enabled": row.enabled, "created_at": iso(row.created_at)}}


@router.delete("/alerts/{rule_id}")
def delete_alert(rule_id: str, principal: BrowserPrincipal = Depends(profile_principal), db: Session = Depends(get_db)):
    row = db.get(AlertRule, rule_id)
    if row is None or row.profile_id != principal.profile.id:
        raise HTTPException(status_code=404, detail={"code": "rule_not_found", "message": "Правило не найдено"})
    db.delete(row)
    db.commit()
    return {"ok": True}


def _validate_webhook_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise HTTPException(status_code=422, detail={"code": "validation_error", "message": "Webhook URL должен быть HTTPS"})
    host = parsed.hostname.lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        raise HTTPException(status_code=422, detail={"code": "webhook_private_host", "message": "Приватные адреса запрещены"})
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address and (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast):
        raise HTTPException(status_code=422, detail={"code": "webhook_private_host", "message": "Приватные адреса запрещены"})
    return value


@router.get("/webhooks")
def list_webhooks(principal: BrowserPrincipal = Depends(profile_principal), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(Webhook).where(Webhook.profile_id == principal.profile.id).order_by(Webhook.created_at.desc())))
    return {"ok": True, "data": [{"id": row.id, "url": row.url, "events": row.events or [], "enabled": row.enabled, "created_at": iso(row.created_at)} for row in rows]}


@router.post("/webhooks")
def create_webhook(payload: WebhookRequest, request: Request, principal: BrowserPrincipal = Depends(profile_principal), db: Session = Depends(get_db)):
    _validate_webhook_url(payload.url)
    row = Webhook(id=f"wh_{secrets.token_hex(8)}", profile_id=principal.profile.id, url=payload.url, secret_encrypted=encrypt_secret(payload.secret, get_settings()), events=payload.events, enabled=payload.enabled)
    db.add(row)
    record_audit(db, actor=f"profile:{principal.profile.id}", action="webhook.create", object_id=row.id, request_id=request_id(), details={"url": row.url, "events": row.events})
    db.commit()
    return {"ok": True, "data": {"id": row.id, "url": row.url, "events": row.events, "enabled": row.enabled, "created_at": iso(row.created_at), "secret_set": True}}


@router.delete("/webhooks/{webhook_id}")
def delete_webhook(webhook_id: str, principal: BrowserPrincipal = Depends(profile_principal), db: Session = Depends(get_db)):
    row = db.get(Webhook, webhook_id)
    if row is None or row.profile_id != principal.profile.id:
        raise HTTPException(status_code=404, detail={"code": "webhook_not_found", "message": "Webhook не найден"})
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.post("/webhooks/{webhook_id}/test")
def test_webhook(webhook_id: str, principal: BrowserPrincipal = Depends(profile_principal), db: Session = Depends(get_db)):
    row = db.get(Webhook, webhook_id)
    if row is None or row.profile_id != principal.profile.id:
        raise HTTPException(status_code=404, detail={"code": "webhook_not_found", "message": "Webhook не найден"})
    event = {"id": f"evt_test_{secrets.token_hex(6)}", "type": "test", "created_at": iso(utcnow()), "data": {"message": "TVS Analytics test event"}}
    raw = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(utcnow().timestamp()))
    signature = hmac.new(decrypt_secret(row.secret_encrypted, get_settings()).encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    delivery = WebhookDelivery(webhook_id=row.id, event_id=event["id"], status="pending", attempts=1)
    db.add(delivery)
    try:
        request_obj = urllib.request.Request(row.url, data=raw, method="POST", headers={"Content-Type": "application/json", "X-TVS-Event": "test", "X-TVS-Timestamp": timestamp, "X-TVS-Signature": signature})
        with urllib.request.urlopen(request_obj, timeout=8) as response:
            delivery.status = "delivered"
            delivery.response_code = response.status
    except (urllib.error.URLError, TimeoutError) as exc:
        delivery.status = "failed"
        delivery.error = str(exc)[:1000]
    delivery.updated_at = utcnow()
    db.commit()
    return {"ok": delivery.status == "delivered", "data": {"status": delivery.status, "response_code": delivery.response_code, "error": delivery.error, "event": event}}
