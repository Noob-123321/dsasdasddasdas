"""Administrative token, policy, audit and load routes."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..clock import as_utc, iso, utcnow
from ..config import get_settings
from ..db import get_db
from ..deps import BrowserPrincipal, admin_principal
from ..models import AccessToken, AccountSession, ApiKey, AuditLog, Channel, Profile, ProfileChannel
from ..security import client_ip, create_access_token, decrypt_secret, normalize_login, request_id
from ..services.audit import record_audit
from ..services.metrics import metrics

router = APIRouter(prefix="/api/admin", tags=["admin"])


class TokenCreate(BaseModel):
    kind: Literal["profile", "admin"]
    label: str = Field(min_length=1, max_length=128)
    expires_at: str | None = None
    unlimited: bool = False
    allowed_channels: list[str] = Field(default_factory=list, max_length=10000)


class TokenPatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=128)
    expires_at: str | None = None
    revoked: bool | None = None
    unlimited: bool | None = None
    allowed_channels: list[str] | None = Field(default=None, max_length=10000)


class PolicyPatch(BaseModel):
    unlimited: bool | None = None
    allowed_channels: list[str] | None = Field(default=None, max_length=10000)


def _parse_expiry(value: str | None) -> dt.datetime | None:
    if value is None or not str(value).strip():
        return None
    parsed = as_utc(value)
    if parsed is None:
        raise HTTPException(status_code=422, detail={"code": "validation_error", "message": "Некорректная дата срока"})
    return parsed


def _token_payload(row: AccessToken, db: Session) -> dict:
    profile = db.get(Profile, row.profile_id) if row.profile_id else None
    return {
        "id": row.id,
        "kind": row.kind,
        "label": row.label,
        "prefix": row.prefix,
        "profile_id": row.profile_id,
        "profile_label": profile.label if profile else None,
        "unlimited": profile.unlimited if profile else None,
        "allowed_channels": profile.allowed_channels if profile else [],
        "expires_at": iso(row.expires_at),
        "revoked_at": iso(row.revoked_at),
        "created_at": iso(row.created_at),
        "last_used_at": iso(row.last_used_at),
        "status": "revoked" if row.revoked_at else "active",
    }


@router.get("/overview")
def overview(principal: BrowserPrincipal = Depends(admin_principal), db: Session = Depends(get_db)):
    token_count = db.scalar(select(func.count()).select_from(AccessToken)) or 0
    profile_count = db.scalar(select(func.count()).select_from(Profile)) or 0
    active_sessions = db.scalar(select(func.count()).select_from(AccountSession).where(AccountSession.revoked_at.is_(None))) or 0
    channel_count = db.scalar(select(func.count()).select_from(Channel).where(Channel.is_active.is_(True))) or 0
    recent = list(db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(12)))
    return {"ok": True, "data": {"tokens": token_count, "profiles": profile_count, "active_sessions": active_sessions, "active_channels": channel_count, "recent_audit": [{"id": row.id, "actor": row.actor, "action": row.action, "object_id": row.object_id, "created_at": iso(row.created_at)} for row in recent], "load": metrics.snapshot()}}


@router.get("/tokens")
def list_tokens(principal: BrowserPrincipal = Depends(admin_principal), db: Session = Depends(get_db), include_revoked: bool = False):
    query = select(AccessToken).order_by(AccessToken.created_at.desc())
    if not include_revoked:
        query = query.where(AccessToken.revoked_at.is_(None))
    rows = list(db.scalars(query))
    return {"ok": True, "data": [_token_payload(row, db) for row in rows]}


@router.post("/tokens")
def create_token(payload: TokenCreate, request: Request, principal: BrowserPrincipal = Depends(admin_principal), db: Session = Depends(get_db)):
    expiry = _parse_expiry(payload.expires_at)
    profile = None
    if payload.kind == "profile":
        try:
            allowed = sorted(set(normalize_login(item) for item in payload.allowed_channels))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "validation_error", "message": str(exc)}) from exc
        profile = Profile(label=payload.label, unlimited=payload.unlimited, allowed_channels=allowed)
        db.add(profile)
        db.flush()
    row, raw = create_access_token(db, get_settings(), kind=payload.kind, label=payload.label, profile_id=profile.id if profile else None, expires_at=expiry, created_by=principal.access_token.id)
    record_audit(db, actor=f"admin:{principal.access_token.id}", action="admin.token.create", object_id=row.id, request_id=request_id(), ip=client_ip(request), details={"kind": payload.kind, "label": payload.label, "unlimited": payload.unlimited})
    db.commit()
    return {"ok": True, "data": {**_token_payload(row, db), "key": raw}}


@router.patch("/tokens/{token_id}")
def patch_token(token_id: str, payload: TokenPatch, request: Request, principal: BrowserPrincipal = Depends(admin_principal), db: Session = Depends(get_db)):
    row = db.get(AccessToken, token_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "token_not_found", "message": "Ключ не найден"})
    before = _token_payload(row, db)
    if payload.label is not None:
        row.label = payload.label.strip()[:128]
    if "expires_at" in payload.model_fields_set:
        row.expires_at = _parse_expiry(payload.expires_at)
    if payload.revoked is not None:
        row.revoked_at = utcnow() if payload.revoked else None
    if row.profile_id and (payload.unlimited is not None or payload.allowed_channels is not None):
        profile = db.get(Profile, row.profile_id)
        if profile is not None:
            if payload.unlimited is not None:
                profile.unlimited = payload.unlimited
            if payload.allowed_channels is not None:
                try:
                    profile.allowed_channels = sorted(set(normalize_login(item) for item in payload.allowed_channels))
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail={"code": "validation_error", "message": str(exc)}) from exc
    record_audit(db, actor=f"admin:{principal.access_token.id}", action="admin.token.update", object_id=row.id, request_id=request_id(), ip=client_ip(request), details={"before": before, "after": _token_payload(row, db)})
    db.commit()
    return {"ok": True, "data": _token_payload(row, db)}


@router.post("/tokens/{token_id}/reveal")
def reveal_token(token_id: str, request: Request, principal: BrowserPrincipal = Depends(admin_principal), db: Session = Depends(get_db)):
    row = db.get(AccessToken, token_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "token_not_found", "message": "Ключ не найден"})
    try:
        raw = decrypt_secret(row.encrypted_secret, get_settings())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": "secret_rotation_required", "message": "Этот секрет создан до обновления encryption key. Его нельзя восстановить — выпустите замену."}) from exc
    record_audit(db, actor=f"admin:{principal.access_token.id}", action="admin.token.reveal", object_id=row.id, request_id=request_id(), ip=client_ip(request), details={"prefix": row.prefix})
    db.commit()
    return {"ok": True, "data": {"id": row.id, "prefix": row.prefix, "key": raw, "warning": "Секрет показан для копирования. Не отправляйте его в URL или логи."}}


@router.post("/tokens/{token_id}/rotate")
def rotate_token(token_id: str, request: Request, principal: BrowserPrincipal = Depends(admin_principal), db: Session = Depends(get_db)):
    row = db.get(AccessToken, token_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "token_not_found", "message": "Ключ не найден"})
    if row.id == principal.access_token.id:
        raise HTTPException(status_code=400, detail={"code": "current_token", "message": "Нельзя перевыпустить ключ текущей админ-сессии"})
    new_row, raw = create_access_token(db, get_settings(), kind=row.kind, label=row.label, profile_id=row.profile_id, expires_at=row.expires_at, created_by=principal.access_token.id)
    row.revoked_at = utcnow()
    record_audit(db, actor=f"admin:{principal.access_token.id}", action="admin.token.rotate", object_id=row.id, request_id=request_id(), ip=client_ip(request), details={"replacement_id": new_row.id, "label": row.label})
    db.commit()
    return {"ok": True, "data": {**_token_payload(new_row, db), "key": raw, "warning": "Старый ключ отозван. Сохраните новый секрет."}}


@router.get("/profiles")
def list_profiles(principal: BrowserPrincipal = Depends(admin_principal), db: Session = Depends(get_db)):
    profiles = list(db.scalars(select(Profile).order_by(Profile.created_at.desc())))
    result = []
    for profile in profiles:
        members = list(db.scalars(select(ProfileChannel).where(ProfileChannel.profile_id == profile.id)))
        result.append({"id": profile.id, "label": profile.label, "unlimited": profile.unlimited, "allowed_channels": profile.allowed_channels or [], "channels": [member.channel_login for member in members], "last_seen_at": iso(profile.last_seen_at), "created_at": iso(profile.created_at)})
    return {"ok": True, "data": result}


@router.patch("/profiles/{profile_id}/policy")
def patch_policy(profile_id: int, payload: PolicyPatch, request: Request, principal: BrowserPrincipal = Depends(admin_principal), db: Session = Depends(get_db)):
    profile = db.get(Profile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail={"code": "profile_not_found", "message": "Профиль не найден"})
    if payload.unlimited is not None:
        profile.unlimited = payload.unlimited
    if payload.allowed_channels is not None:
        try:
            profile.allowed_channels = sorted(set(normalize_login(item) for item in payload.allowed_channels))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "validation_error", "message": str(exc)}) from exc
    record_audit(db, actor=f"admin:{principal.access_token.id}", action="admin.profile.policy", object_id=str(profile.id), request_id=request_id(), ip=client_ip(request), details={"unlimited": profile.unlimited, "allowed_channels": profile.allowed_channels})
    db.commit()
    return {"ok": True, "data": {"id": profile.id, "unlimited": profile.unlimited, "allowed_channels": profile.allowed_channels or []}}


@router.get("/audit")
def audit(principal: BrowserPrincipal = Depends(admin_principal), db: Session = Depends(get_db), limit: int = 100):
    rows = list(db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(min(limit, 500))))
    return {"ok": True, "data": [{"id": row.id, "actor": row.actor, "action": row.action, "object_id": row.object_id, "request_id": row.request_id, "ip": row.ip, "details": row.details, "created_at": iso(row.created_at)} for row in rows]}


@router.get("/load")
def load(request: Request, principal: BrowserPrincipal = Depends(admin_principal), db: Session = Depends(get_db)):
    from ..models import AccountSession
    active_sessions = db.scalar(select(func.count()).select_from(AccountSession).where(AccountSession.revoked_at.is_(None))) or 0
    active_profiles = db.scalar(select(func.count()).select_from(Profile).where(Profile.last_seen_at.is_not(None))) or 0
    channels = db.scalar(select(func.count()).select_from(Channel).where(Channel.is_active.is_(True))) or 0
    poller = getattr(request.app.state, "poller", None)
    poller_stats = dict(poller.stats) if poller else {}
    return {"ok": True, "data": {"application": metrics.snapshot(), "active_sessions": active_sessions, "active_profiles": active_profiles, "active_channels": channels, "api_keys": db.scalar(select(func.count()).select_from(ApiKey).where(ApiKey.revoked_at.is_(None))) or 0, "poller": poller_stats, "database": {"dialect": db.bind.dialect.name if db.bind else "unknown"}}}
