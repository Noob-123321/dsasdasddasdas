"""FastAPI dependencies for browser sessions and API keys."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .clock import utcnow
from .db import get_db
from .models import AccessToken, ApiKey, Profile
from .security import api_key_is_active, find_api_key, get_session, rate_limiter

SESSION_COOKIE = "tvs_session"


@dataclass
class BrowserPrincipal:
    session_id: int
    access_token: AccessToken
    profile: Profile | None

    @property
    def is_admin(self) -> bool:
        return self.access_token.kind == "admin"


@dataclass
class ApiPrincipal:
    api_key: ApiKey
    parent: AccessToken
    profile: Profile


def browser_principal(request: Request, db: Annotated[Session, Depends(get_db)]) -> BrowserPrincipal:
    found = get_session(db, request.cookies.get(SESSION_COOKIE))
    if found is None:
        raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "Войдите по лицензионному ключу"})
    session_row, access = found
    profile = db.get(Profile, access.profile_id) if access.profile_id else None
    return BrowserPrincipal(session_id=session_row.id, access_token=access, profile=profile)


def profile_principal(principal: Annotated[BrowserPrincipal, Depends(browser_principal)]) -> BrowserPrincipal:
    if principal.profile is None:
        raise HTTPException(status_code=403, detail={"code": "profile_required", "message": "У ключа нет профиля"})
    return principal


def admin_principal(principal: Annotated[BrowserPrincipal, Depends(browser_principal)]) -> BrowserPrincipal:
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Нужны права администратора"})
    return principal


def api_principal(request: Request, db: Annotated[Session, Depends(get_db)]) -> ApiPrincipal:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "Передайте API-ключ в Authorization: Bearer"})
    raw = header.split(" ", 1)[1].strip()
    found = find_api_key(db, raw)
    if found is None or not api_key_is_active(*found):
        raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "API-ключ недействителен"})
    key, parent = found
    allowed, retry_after = rate_limiter.allow(f"api:{key.id}", limit=300, window=60)
    if not allowed:
        raise HTTPException(status_code=429, headers={"Retry-After": str(retry_after)}, detail={"code": "rate_limited", "message": "Превышен лимит API-запросов"})
    request.state.rate_limit_limit = 300
    request.state.rate_limit_remaining = max(0, 299)
    profile = db.get(Profile, key.profile_id)
    if profile is None:
        raise HTTPException(status_code=401, detail={"code": "parent_token_revoked", "message": "Профиль ключа недоступен"})
    key.requests_used += 1
    key.last_used_at = utcnow()
    # API v1 routes are read-only; persist usage before the request completes so
    # closing the request-scoped session cannot roll the counter back.
    db.commit()
    return ApiPrincipal(api_key=key, parent=parent, profile=profile)
