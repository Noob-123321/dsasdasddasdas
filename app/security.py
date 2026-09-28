"""Token, session, encryption and input-safety helpers."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta
from typing import Deque
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .clock import utcnow
from .config import Settings
from .models import AccessToken, AccountSession, ApiKey, Profile

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
API_ALPHABET = ALPHABET + "-_"
LOGIN_RE = re.compile(r"^[a-z0-9_]{1,25}$")
RESERVED_PATHS = {
    "directory", "settings", "downloads", "jobs", "p", "search", "videos",
    "subscriptions", "friends", "drops", "store", "turbo", "following",
}


def random_secret(length: int = 128, alphabet: str = ALPHABET) -> str:
    return "".join(secrets.choice(alphabet) for _ in range(length))


# Access keys are branded TVS (Twitch Viewers System). Legacy TVB_ keys keep
# working so existing deployments survive the rename without re-issuing secrets.
ACCESS_PREFIX = "TVS_"
LEGACY_ACCESS_PREFIX = "TVB_"
ACCESS_PREFIXES = (ACCESS_PREFIX, LEGACY_ACCESS_PREFIX)
API_PREFIX = "tvs_"
LEGACY_API_PREFIX = "tvb_"
API_PREFIXES = (API_PREFIX, LEGACY_API_PREFIX)
ACCESS_LENGTH = 132


def is_access_token(raw: str) -> bool:
    return isinstance(raw, str) and len(raw) == ACCESS_LENGTH and raw.startswith(ACCESS_PREFIXES)


def generate_tvs_token() -> str:
    return ACCESS_PREFIX + random_secret(128, ALPHABET)


# Backward-compatible alias for external callers/tests.
generate_tvb_token = generate_tvs_token


def generate_api_token() -> str:
    return API_PREFIX + random_secret(128, API_ALPHABET)


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def encrypt_secret(raw: str, settings: Settings) -> str:
    return Fernet(settings.token_encryption_key).encrypt(raw.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str, settings: Settings) -> str:
    try:
        return Fernet(settings.token_encryption_key).decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Не удалось расшифровать секрет") from exc


def create_access_token(
    db: Session,
    settings: Settings,
    *,
    kind: str,
    label: str,
    profile_id: int | None = None,
    expires_at=None,
    created_by: str | None = None,
    raw: str | None = None,
) -> tuple[AccessToken, str]:
    if kind not in {"profile", "admin"}:
        raise ValueError("kind должен быть profile или admin")
    raw = raw or generate_tvs_token()
    if not is_access_token(raw):
        raise ValueError("TVS-ключ должен быть TVS_ + 128 символов")
    row = AccessToken(
        id=f"tok_{secrets.token_hex(8)}",
        profile_id=profile_id,
        kind=kind,
        label=label.strip()[:128] or "Ключ",
        prefix=raw[:12],
        lookup_hash=token_hash(raw),
        encrypted_secret=encrypt_secret(raw, settings),
        expires_at=expires_at,
        created_by=created_by,
    )
    db.add(row)
    db.flush()
    return row, raw


def create_api_key(
    db: Session,
    settings: Settings,
    *,
    profile_id: int,
    parent_token_id: str,
    label: str,
) -> tuple[ApiKey, str]:
    raw = generate_api_token()
    row = ApiKey(
        id=f"key_{secrets.token_hex(8)}",
        profile_id=profile_id,
        parent_token_id=parent_token_id,
        label=label.strip()[:128] or "API key",
        prefix=raw[:12],
        lookup_hash=token_hash(raw),
        encrypted_secret=encrypt_secret(raw, settings),
        scopes=["read"],
    )
    db.add(row)
    db.flush()
    return row, raw


def token_is_active(row: AccessToken | None, now=None) -> bool:
    if row is None or row.revoked_at is not None:
        return False
    moment = now or utcnow()
    return row.expires_at is None or row.expires_at > moment


def api_key_is_active(row: ApiKey | None, parent: AccessToken | None, now=None) -> bool:
    if row is None or parent is None or row.revoked_at is not None:
        return False
    if row.expires_at is not None and (now or utcnow()) >= row.expires_at:
        return False
    return token_is_active(parent, now=now)


def find_access_token(db: Session, raw: str) -> AccessToken | None:
    if not isinstance(raw, str):
        return None
    return db.scalar(select(AccessToken).where(AccessToken.lookup_hash == token_hash(raw.strip())))


def find_api_key(db: Session, raw: str) -> tuple[ApiKey, AccessToken] | None:
    if not isinstance(raw, str):
        return None
    key = db.scalar(select(ApiKey).where(ApiKey.lookup_hash == token_hash(raw.strip())))
    if key is None:
        return None
    parent = db.get(AccessToken, key.parent_token_id)
    if parent is None:
        return None
    return key, parent


def create_session(db: Session, access_token: AccessToken, request: Request | None = None, days: int = 30) -> str:
    raw = secrets.token_urlsafe(40)
    # 40 random bytes gives the session substantially more than 128 bits.
    row = AccountSession(
        token_id=access_token.id,
        token_hash=token_hash(raw),
        expires_at=utcnow() + timedelta(days=days),
        ip=client_ip(request) if request else None,
        user_agent=(request.headers.get("user-agent", "")[:256] if request else None),
    )
    db.add(row)
    db.flush()
    return raw


def get_session(db: Session, raw: str | None) -> tuple[AccountSession, AccessToken] | None:
    if not raw:
        return None
    row = db.scalar(select(AccountSession).where(AccountSession.token_hash == token_hash(raw)))
    if row is None or row.revoked_at is not None or row.expires_at <= utcnow():
        return None
    access = db.get(AccessToken, row.token_id)
    if access is None or not token_is_active(access):
        return None
    return row, access


def revoke_session(db: Session, raw: str | None) -> None:
    if not raw:
        return
    row = db.scalar(select(AccountSession).where(AccountSession.token_hash == token_hash(raw)))
    if row is not None and row.revoked_at is None:
        row.revoked_at = utcnow()


def client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    peer = request.client.host if request.client else ""
    # Do not trust X-Forwarded-For by default. The production proxy must be
    # explicitly configured in TRUSTED_PROXIES before this branch is enabled.
    return peer or None


def normalize_login(raw: str) -> str:
    value = str(raw or "").strip().lower()
    value = re.sub(r"^@", "", value)
    if value.startswith(("www.twitch.tv/", "twitch.tv/")):
        value = "https://" + value
    if value.startswith(("https://", "http://")):
        parsed = urlparse(value)
        host = (parsed.netloc or "").lower()
        if host not in {"twitch.tv", "www.twitch.tv", "m.twitch.tv"}:
            raise ValueError("Поддерживаются только ссылки на twitch.tv")
        parts = [part for part in parsed.path.split("/") if part]
        if not parts or parts[0].lower() in RESERVED_PATHS:
            raise ValueError("Это не ссылка на канал Twitch")
        value = parts[0]
    if not LOGIN_RE.fullmatch(value):
        raise ValueError("Логин Twitch должен содержать 1–25 символов a-z, 0-9 или _")
    return value


def parse_channel_input(text: str) -> tuple[list[str], list[str]]:
    accepted: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for part in str(text or "").split():
        try:
            login = normalize_login(part)
        except ValueError:
            invalid.append(part)
            continue
        if login not in seen:
            seen.add(login)
            accepted.append(login)
    return accepted, invalid


def profile_can_access(profile: Profile | None, login: str) -> bool:
    if profile is None:
        return True
    if profile.unlimited:
        return True
    return login in (profile.allowed_channels or [])


class MemoryRateLimiter:
    """Small process-local limiter; Redis can replace this in production."""

    def __init__(self) -> None:
        self._hits: dict[str, Deque[float]] = defaultdict(deque)
        self._lock = __import__("threading").Lock()

    def allow(self, key: str, limit: int = 60, window: int = 60) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= window:
                hits.popleft()
            if len(hits) >= limit:
                return False, max(1, int(window - (now - hits[0])))
            hits.append(now)
            return True, 0


rate_limiter = MemoryRateLimiter()


def request_id() -> str:
    return f"req_{secrets.token_hex(8)}"


def mask_secret(raw: str) -> str:
    if len(raw) <= 16:
        return raw[:4] + "…"
    return raw[:12] + "…" + raw[-4:]


def constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode(), right.encode())
