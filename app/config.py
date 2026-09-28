"""Configuration for the FastAPI application and background workers."""
from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_dotenv(path: Path = ROOT_DIR / ".env") -> None:
    """Load a small .env file without adding a runtime dependency."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _derivable_key(value: str) -> bytes:
    """Accept a Fernet key or derive a stable 32-byte key for development."""
    try:
        if len(base64.urlsafe_b64decode(value.encode("ascii"))) == 32:
            return value.encode("ascii")
    except Exception:
        pass
    return base64.urlsafe_b64encode(hashlib.sha256(value.encode("utf-8")).digest())


def _load_encryption_key() -> bytes:
    configured = os.getenv("TOKEN_ENCRYPTION_KEY", "").strip()
    if configured:
        return _derivable_key(configured)
    key_path = Path(os.getenv("TOKEN_ENCRYPTION_KEY_FILE", str(DATA_DIR / "token.key")))
    if key_path.exists():
        return _derivable_key(key_path.read_text(encoding="utf-8").strip())
    if _flag("APP_ENV_PRODUCTION", False) or os.getenv("APP_ENV", "").strip().lower() == "production":
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is required in production")
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = base64.urlsafe_b64encode(os.urandom(32))
    key_path.write_text(key.decode("ascii"), encoding="utf-8")
    try:
        key_path.chmod(0o600)
    except OSError:
        pass
    return key


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str
    redis_url: str
    public_base_url: str
    allowed_origins: tuple[str, ...]
    trusted_proxies: tuple[str, ...]
    token_encryption_key: bytes
    poll_interval_seconds: float
    poll_batch: int
    poller_enabled: bool
    twitch_source: str
    twitch_timeout_seconds: float
    chatter_roster_every: int
    chatter_enrich_hours: float
    session_days: int
    cookie_secure: bool
    max_json_bytes: int
    admin_bootstrap_token: str
    telegram_bot_token: str
    telegram_chat_id: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv()
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    origins = tuple(
        item.strip().rstrip("/")
        for item in os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",")
        if item.strip()
    )
    proxies = tuple(item.strip() for item in os.getenv("TRUSTED_PROXIES", "").split(",") if item.strip())
    return Settings(
        app_env=app_env,
        database_url=os.getenv("DATABASE_URL", f"sqlite:///{(DATA_DIR / 'tvs.db').as_posix()}"),
        redis_url=os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "").rstrip("/"),
        allowed_origins=origins,
        trusted_proxies=proxies,
        token_encryption_key=_load_encryption_key(),
        poll_interval_seconds=_float("POLL_INTERVAL_SECONDS", 60.0),
        poll_batch=_int("POLL_BATCH", 200),
        poller_enabled=_flag("POLLER_ENABLED", True),
        twitch_source=os.getenv("TWITCH_SOURCE", "gql").strip().lower(),
        twitch_timeout_seconds=_float("TWITCH_TIMEOUT_SECONDS", 15.0),
        chatter_roster_every=_int("CHATTER_ROSTER_EVERY", 10),
        chatter_enrich_hours=_float("CHATTER_ENRICH_HOURS", 6.0),
        session_days=_int("SESSION_DAYS", 30),
        cookie_secure=_flag("COOKIE_SECURE", app_env == "production"),
        max_json_bytes=_int("MAX_JSON_BYTES", 128 * 1024),
        admin_bootstrap_token=os.getenv("BOOTSTRAP_ADMIN_TOKEN", "").strip(),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
    )


def reset_settings_cache() -> None:
    get_settings.cache_clear()
