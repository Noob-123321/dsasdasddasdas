"""Token redemption and browser session routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..clock import iso, utcnow
from ..config import get_settings
from ..db import get_db
from ..deps import SESSION_COOKIE, BrowserPrincipal
from ..models import Profile
from ..security import (
    client_ip,
    create_session,
    find_access_token,
    get_session,
    is_access_token,
    rate_limiter,
    request_id,
    revoke_session,
    token_is_active,
)
from ..services.audit import record_audit

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RedeemRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)


def principal_payload(principal: BrowserPrincipal) -> dict:
    access = principal.access_token
    profile = principal.profile
    return {
        "id": access.id,
        "label": access.label,
        "kind": access.kind,
        "prefix": access.prefix,
        "expires_at": iso(access.expires_at),
        "is_admin": principal.is_admin,
        "profile": None if profile is None else {
            "id": profile.id,
            "label": profile.label,
            "unlimited": profile.unlimited,
            "allowed_channels": profile.allowed_channels or [],
            "created_at": iso(profile.created_at),
        },
    }


@router.post("/redeem")
def redeem(payload: RedeemRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    settings = get_settings()
    raw = payload.token.strip()
    allowed, retry_after = rate_limiter.allow(f"redeem:{client_ip(request)}", limit=12, window=60)
    if not allowed:
        raise HTTPException(status_code=429, headers={"Retry-After": str(retry_after)}, detail={"code": "rate_limited", "message": "Слишком много попыток входа"})
    if not is_access_token(raw):
        raise HTTPException(status_code=401, detail={"code": "invalid_token", "message": "Ключ не найден или больше не действует"})
    access = find_access_token(db, raw)
    if not token_is_active(access):
        raise HTTPException(status_code=401, detail={"code": "invalid_token", "message": "Ключ не найден или больше не действует"})
    access.last_used_at = utcnow()
    access.last_used_ip = client_ip(request)
    if access.profile_id:
        profile = db.get(Profile, access.profile_id)
        if profile is not None:
            profile.last_seen_at = access.last_used_at
    raw_session = create_session(db, access, request=request, days=settings.session_days)
    record_audit(db, actor=f"{access.kind}:{access.id}", action="auth.redeem", object_id=access.id, request_id=request_id(), ip=client_ip(request), details={"kind": access.kind})
    db.commit()
    response.set_cookie(SESSION_COOKIE, raw_session, max_age=settings.session_days * 86400, httponly=True, secure=settings.cookie_secure, samesite="lax", path="/")
    return {"ok": True, "user": principal_payload(BrowserPrincipal(0, access, db.get(Profile, access.profile_id) if access.profile_id else None))}


@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    found = get_session(db, request.cookies.get(SESSION_COOKIE))
    if found is None:
        return {"ok": True, "user": None}
    session_row, access = found
    profile = db.get(Profile, access.profile_id) if access.profile_id else None
    return {"ok": True, "user": principal_payload(BrowserPrincipal(session_row.id, access, profile))}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    raw = request.cookies.get(SESSION_COOKIE)
    revoke_session(db, raw)
    record_audit(db, actor="session", action="auth.logout", ip=client_ip(request), request_id=request_id())
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}
