#!/usr/bin/env python3
"""TVS Analytics safe operations helper for Windows and Linux.

The helper intentionally uses only the Python standard library. It never prints
secret values, never removes Docker volumes, and never deletes data/token.key.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
ENV_FILE = ROOT / ".env"
BACKUP_DIR = ROOT / "backups"
COMPOSE_FILE = ROOT / "docker-compose.yml"
HEALTH_URL = "http://127.0.0.1:8000/readyz"


class CommandError(RuntimeError):
    pass


def say(message: str) -> None:
    print(f"[tvs] {message}")


def fail(message: str) -> int:
    print(f"[tvs] ERROR: {message}", file=sys.stderr)
    return 1


def read_env_file(path: Path = ENV_FILE) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def env_value(name: str, env: dict[str, str] | None = None) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    return (env or read_env_file()).get(name)


def run_command(command: list[str], *, capture: bool = True, check: bool = True) -> subprocess.CompletedProcess[str]:
    printable = " ".join(command)
    say(f"$ {printable}")
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=capture,
        check=False,
    )
    if capture and result.stdout:
        print(result.stdout.rstrip())
    if capture and result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    if check and result.returncode != 0:
        raise CommandError(f"command failed ({result.returncode}): {printable}")
    return result


def docker_compose() -> list[str] | None:
    docker = shutil.which("docker")
    if docker:
        probe = subprocess.run(
            [docker, "compose", "version"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if probe.returncode == 0:
            return [docker, "compose"]
    legacy = shutil.which("docker-compose")
    if legacy:
        return [legacy]
    return None


def require_compose() -> list[str]:
    compose = docker_compose()
    if compose is None:
        raise CommandError("Docker Compose не найден. Установите Docker Desktop/Engine или используйте команду local.")
    return compose


def compose(command: list[str], *, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return run_command(require_compose() + command, check=check, capture=capture)


def health(url: str = HEALTH_URL) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            body = response.read(300).decode("utf-8", errors="replace")
            return 200 <= response.status < 300, body
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, str(exc)


def wait_for_health(url: str = HEALTH_URL, seconds: int = 45) -> None:
    deadline = time.monotonic() + seconds
    last = ""
    while time.monotonic() < deadline:
        ok, detail = health(url)
        if ok:
            say(f"health OK: {url}")
            return
        last = detail
        time.sleep(1)
    raise CommandError(f"health check failed: {url}: {last}")


def ensure_env() -> None:
    if ENV_FILE.exists():
        return
    say("Creating .env from .env.example")
    shutil.copy2(ROOT / ".env.example", ENV_FILE)


def require_env_file() -> None:
    if not ENV_FILE.exists():
        raise CommandError(".env is missing; run `tvs init` and review it before starting services")


def cmd_init(_: argparse.Namespace) -> int:
    ensure_env()
    say("Initialization complete. Review .env before production use.")
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    say(f"Project: {ROOT}")
    say(f"Python: {sys.version.split()[0]}")
    required = [ROOT / ".env.example", ROOT / "requirements.txt", ROOT / "docker-compose.yml", ROOT / "app" / "main.py"]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    if missing:
        say("Missing required files: " + ", ".join(missing))
    else:
        say("Required project files: OK")

    if not ENV_FILE.exists():
        say("WARNING: .env is absent; run `tvs init`")
    env = read_env_file()
    app_env = (env_value("APP_ENV", env) or "development").lower()
    source = (env_value("TWITCH_SOURCE", env) or "gql").lower()
    say(f"APP_ENV={app_env}; TWITCH_SOURCE={source}")
    if not docker_compose():
        say("WARNING: Docker Compose is unavailable; local mode is available")
    if app_env == "production":
        required_values = {
            "PUBLIC_BASE_URL": env_value("PUBLIC_BASE_URL", env),
            "COOKIE_SECURE": env_value("COOKIE_SECURE", env),
            "TOKEN_ENCRYPTION_KEY": env_value("TOKEN_ENCRYPTION_KEY", env),
        }
        if not required_values["PUBLIC_BASE_URL"]:
            say("ERROR: PUBLIC_BASE_URL is required in production")
        if str(required_values["COOKIE_SECURE"]).lower() not in {"1", "true", "yes", "on"}:
            say("ERROR: COOKIE_SECURE must be 1 in production")
        if not required_values["TOKEN_ENCRYPTION_KEY"] and not env_value("TOKEN_ENCRYPTION_KEY_FILE", env):
            say("ERROR: set TOKEN_ENCRYPTION_KEY or TOKEN_ENCRYPTION_KEY_FILE")
    if (env_value("DATABASE_URL", env) or "").startswith("sqlite") and not (ROOT / "data" / "token.key").exists() and not env_value("TOKEN_ENCRYPTION_KEY", env):
        say("WARNING: local token.key does not exist yet; it will be created on first startup")
    say("Doctor finished")
    return 0


def cmd_local(_: argparse.Namespace) -> int:
    ensure_env()
    say("Applying local database migrations")
    run_command([sys.executable, "-m", "alembic", "upgrade", "head"])
    say("Starting Uvicorn on http://127.0.0.1:8000")
    return run_command([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"], check=False).returncode


def cmd_up(_: argparse.Namespace) -> int:
    require_env_file()
    require_compose()
    compose(["up", "-d", "--build"])
    wait_for_health()
    say("TVS Analytics is up")
    return 0


def cmd_down(_: argparse.Namespace) -> int:
    compose(["down"])
    say("Containers stopped; named database volumes were preserved")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    if docker_compose():
        compose(["ps"], check=False)
    ok, detail = health(args.url)
    say(f"health {args.url}: {'OK' if ok else 'NOT READY'}")
    if not ok:
        say(detail[:300])
    return 0 if ok else 1


def cmd_logs(_: argparse.Namespace) -> int:
    return compose(["logs", "-f", "--tail=200"], check=False, capture=False).returncode


def backup_sqlite(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)


def sqlite_path_from_url(value: str) -> Path | None:
    if not value.startswith("sqlite"):
        return None
    raw = value.removeprefix("sqlite:///")
    if raw == ":memory:" or not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def cmd_backup(_: argparse.Namespace) -> int:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target_dir = BACKUP_DIR / stamp
    target_dir.mkdir(parents=True, exist_ok=False)
    env = read_env_file()
    database_url = env_value("DATABASE_URL", env) or ""
    sqlite_path = sqlite_path_from_url(database_url)
    if sqlite_path and sqlite_path.exists():
        destination = target_dir / "tvs.db"
        backup_sqlite(sqlite_path, destination)
        say(f"SQLite backup: {destination}")
        key = ROOT / "data" / "token.key"
        if key.exists():
            key_destination = target_dir / "token.key"
            shutil.copy2(key, key_destination)
            say(f"Encryption key copy: {key_destination} (protect this backup)")
    else:
        pg_user = env.get("POSTGRES_USER", "tvs")
        pg_db = env.get("POSTGRES_DB", "tvs")
        sql_file = target_dir / "tvs.sql"
        say("PostgreSQL backup via Docker Compose")
        with sql_file.open("w", encoding="utf-8") as handle:
            result = subprocess.run(
                require_compose() + ["exec", "-T", "postgres", "pg_dump", "-U", pg_user, "-d", pg_db, "--clean", "--if-exists", "--no-owner", "--no-privileges"],
                cwd=ROOT,
                stdout=handle,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)
            raise CommandError("pg_dump failed")
        say(f"PostgreSQL backup: {sql_file}")
    say("Keep .env/secret-manager values separately; never commit backups")
    return 0


def git_pull() -> None:
    if not (ROOT / ".git").exists() or shutil.which("git") is None:
        say("No Git checkout detected; source update skipped. Install/copy the new release files manually, then rerun update.")
        return
    run_command(["git", "pull", "--ff-only"])


def cmd_update(_: argparse.Namespace) -> int:
    require_env_file()
    require_compose()
    say("1/4 Creating a backup")
    cmd_backup(argparse.Namespace())
    say("2/4 Updating source when Git is available")
    git_pull()
    say("3/4 Building images and applying migrations")
    compose(["build", "--pull", "api", "poller"])
    compose(["run", "--rm", "api", "python", "-m", "alembic", "upgrade", "head"])
    compose(["up", "-d", "--remove-orphans"])
    say("4/4 Checking health")
    wait_for_health()
    say("Update complete. If health failed, use the backup and the previous image; do not delete volumes.")
    return 0


def cmd_check(_: argparse.Namespace) -> int:
    commands = [
        [sys.executable, "-m", "pytest", "-q"],
        [sys.executable, "-m", "compileall", "-q", "app", "src", "tests", "tools"],
    ]
    if shutil.which("node"):
        commands.append(["node", "--check", "public/app.js"])
    else:
        say("WARNING: node not found; skipped JS syntax check")
    if shutil.which("ruff"):
        commands.append(["ruff", "check", "app"])
    else:
        say("WARNING: ruff not found; skipped lint")
    commands.append([sys.executable, "-m", "alembic", "check"])
    failed = False
    for command in commands:
        try:
            run_command(command)
        except CommandError:
            failed = True
    return 1 if failed else 0


def cmd_restore_sqlite(args: argparse.Namespace) -> int:
    if not args.yes:
        raise CommandError("Restore is destructive; rerun with --yes after stopping the server")
    server_ok, _ = health()
    if server_ok:
        raise CommandError("local server is still healthy; stop it before restoring SQLite")
    source = Path(args.backup).resolve()
    configured = sqlite_path_from_url(env_value("DATABASE_URL") or "")
    destination = configured or (ROOT / "data" / "tvs.db")
    if not source.exists() or source.suffix not in {".db", ".sqlite", ".sqlite3"}:
        raise CommandError("backup must be an existing SQLite .db/.sqlite/.sqlite3 file")
    if not destination.exists():
        raise CommandError(f"destination not found: {destination}")
    current = BACKUP_DIR / f"pre-restore-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    backup_sqlite(destination, current)
    backup_sqlite(source, destination)
    say(f"Previous database saved as {current}")
    say("SQLite restore complete. Start the server and run the health check")
    return 0


def cmd_show_admin_key(args: argparse.Namespace) -> int:
    if not args.yes:
        try:
            answer = input("Type SHOW to reveal the main admin TVS key: ").strip()
        except EOFError:
            raise CommandError("interactive confirmation is unavailable; rerun with --yes only on a trusted machine")
        if answer != "SHOW":
            say("Cancelled; no secret was printed")
            return 0
    try:
        from sqlalchemy import select
        from app.config import get_settings
        from app.db import SessionLocal
        from app.models import AccessToken
        from app.security import decrypt_secret, token_is_active
        from app.services.audit import record_audit
    except ImportError as exc:
        raise CommandError(f"application dependencies are unavailable: {exc}") from exc
    try:
        with SessionLocal() as db:
            rows = list(db.scalars(select(AccessToken).where(AccessToken.kind == "admin").order_by(AccessToken.created_at.asc())))
            active = [row for row in rows if token_is_active(row)]
            if not active:
                raise CommandError("active main admin key not found")
            row = active[0]
            try:
                raw = decrypt_secret(row.encrypted_secret, get_settings())
            except ValueError as exc:
                raise CommandError("main admin secret cannot be decrypted with the current TOKEN_ENCRYPTION_KEY; use the audited rotate flow") from exc
            record_audit(db, actor="local-cli", action="admin.token.reveal", object_id=row.id, details={"prefix": row.prefix, "surface": "bat"})
            db.commit()
    except CommandError:
        raise
    except Exception as exc:
        compose = docker_compose()
        if compose:
            say("Local database is unavailable; trying the Docker API container")
            return run_command(compose + ["exec", "-T", "api", "python", "scripts/tvs.py", "show-admin-key", "--yes"], check=False).returncode
        raise CommandError(f"could not read admin key from the configured database: {exc}") from exc
    say("WARNING: keep this key private; the reveal was recorded in the audit log")
    print(f"MAIN_ADMIN_KEY={raw}")
    return 0


def cmd_token(args: argparse.Namespace) -> int:
    if args.kind == "admin":
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        print("TVS_" + "".join(secrets.choice(alphabet) for _ in range(128)))
    else:
        print(base64.urlsafe_b64encode(os.urandom(32)).decode("ascii"))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Safe TVS Analytics operations")
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create .env from .env.example").set_defaults(func=cmd_init)
    sub.add_parser("doctor", help="check local configuration").set_defaults(func=cmd_doctor)
    sub.add_parser("local", help="run migrations and Uvicorn in the foreground").set_defaults(func=cmd_local)
    sub.add_parser("up", help="build/start Docker Compose services").set_defaults(func=cmd_up)
    sub.add_parser("down", help="stop containers without deleting volumes").set_defaults(func=cmd_down)
    p_status = sub.add_parser("status", help="show container and health status")
    p_status.add_argument("--url", default=HEALTH_URL)
    p_status.set_defaults(func=cmd_status)
    sub.add_parser("logs", help="follow container logs").set_defaults(func=cmd_logs)
    sub.add_parser("backup", help="create a timestamped database backup").set_defaults(func=cmd_backup)
    sub.add_parser("update", help="backup, update source, build, migrate and health-check").set_defaults(func=cmd_update)
    sub.add_parser("check", help="run automated project checks").set_defaults(func=cmd_check)
    p_restore = sub.add_parser("restore-sqlite", help="explicit local SQLite restore")
    p_restore.add_argument("backup")
    p_restore.add_argument("--yes", action="store_true")
    p_restore.set_defaults(func=cmd_restore_sqlite)
    p_admin_key = sub.add_parser("show-admin-key", help="reveal the active main admin key after confirmation")
    p_admin_key.add_argument("--yes", action="store_true", help="skip interactive SHOW confirmation")
    p_admin_key.set_defaults(func=cmd_show_admin_key)
    p_token = sub.add_parser("token", help="generate a secret without printing env values")
    p_token.add_argument("kind", choices=("admin", "fernet"), nargs="?", default="fernet")
    p_token.set_defaults(func=cmd_token)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        say("Interrupted")
        return 130
    except (CommandError, OSError, ValueError) as exc:
        return fail(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
