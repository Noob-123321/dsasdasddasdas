"""FastAPI application entry point."""
from __future__ import annotations

import logging
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from .config import DATA_DIR, get_settings
from .db import SessionLocal, init_db
from .models import AccessToken
from .poller import Poller
from .routers import admin, auth, health, profile, v1
from .security import create_access_token
from .services.audit import record_audit
from .services.metrics import metrics

log = logging.getLogger("tvs")
ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"


def bootstrap_admin() -> None:
    settings = get_settings()
    with SessionLocal() as db:
        exists = db.scalar(select(AccessToken).where(AccessToken.kind == "admin", AccessToken.revoked_at.is_(None)).limit(1))
        if exists is not None:
            return
        raw = settings.admin_bootstrap_token
        source = "BOOTSTRAP_ADMIN_TOKEN"
        if not raw:
            row, raw = create_access_token(db, settings, kind="admin", label="Bootstrap admin")
            source = "generated"
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            (DATA_DIR / "bootstrap_admin.txt").write_text(raw + "\n", encoding="utf-8")
        else:
            row, raw = create_access_token(db, settings, kind="admin", label="Bootstrap admin", raw=raw)
        record_audit(db, actor="bootstrap", action="admin.bootstrap", object_id=row.id, details={"source": source})
        db.commit()
        if settings.app_env != "production":
            log.warning("Админский ключ создан (%s); сохраните его в защищённом хранилище", source)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    bootstrap_admin()
    settings = get_settings()
    app.state.poller = None
    if settings.poller_enabled:
        poller = Poller(SessionLocal, settings)
        app.state.poller = poller
        poller.start_background()
    yield
    if app.state.poller:
        app.state.poller.stop()


app = FastAPI(title="TVS Analytics API", version="1.0.0", description="Twitch Viewers System — portfolio analytics with explainable risk scores.", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=list(get_settings().allowed_origins), allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Content-Type", "Authorization", "X-Request-ID"])
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(admin.router)
app.include_router(v1.router)


@app.middleware("http")
async def request_middleware(request: Request, call_next):
    started = time.perf_counter()
    request_id = request.headers.get("x-request-id") or f"req_{secrets.token_hex(8)}"
    request.state.request_id = request_id
    if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
        origin = (request.headers.get("origin") or "").rstrip("/")
        if origin:
            settings = get_settings()
            allowed = set(settings.allowed_origins)
            if settings.public_base_url:
                allowed.add(settings.public_base_url.rstrip("/"))
            # A reverse proxy can expose the public hostname through Host
            # while the application itself is reached on localhost. Accept
            # same-host browser requests, while still rejecting unrelated
            # origins. Forwarded host is trusted only for configured proxies.
            client_host = request.client.host if request.client else ""
            trusted_proxy = client_host in settings.trusted_proxies
            forwarded_host = request.headers.get("x-forwarded-host") if trusted_proxy else None
            request_hosts = [request.headers.get("host"), forwarded_host]
            for host in request_hosts:
                if not host:
                    continue
                allowed.update({f"http://{host}".rstrip("/"), f"https://{host}".rstrip("/")})
            if origin not in allowed:
                response = JSONResponse(status_code=403, content={"ok": False, "error": {"code": "origin_forbidden", "message": "Запрос с чужого origin"}, "meta": {"request_id": request_id}})
                response.headers["X-Request-ID"] = request_id
                return response
    try:
        response = await call_next(request)
    except Exception:
        metrics.observe(request.url.path, 500, (time.perf_counter() - started) * 1000, request.url.path.startswith("/api/v1"))
        raise
    duration = (time.perf_counter() - started) * 1000
    metrics.observe(request.url.path, response.status_code, duration, request.url.path.startswith("/api/v1"))
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    csp = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.url.path in {"/docs", "/redoc"}:
        csp = "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https://fastapi.tiangolo.com; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    response.headers["Content-Security-Policy"] = csp
    if hasattr(request.state, "rate_limit_limit"):
        response.headers["X-RateLimit-Limit"] = str(request.state.rate_limit_limit)
        response.headers["X-RateLimit-Remaining"] = str(request.state.rate_limit_remaining)
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict):
        error = {"code": detail.get("code", "error"), "message": detail.get("message", str(detail))}
    else:
        error = {"code": "error", "message": str(detail)}
    return JSONResponse(status_code=exc.status_code, content={"ok": False, "error": error, "meta": {"request_id": getattr(request.state, "request_id", "req_unknown")}}, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"ok": False, "error": {"code": "validation_error", "message": "Проверьте входные данные", "details": exc.errors()}, "meta": {"request_id": getattr(request.state, "request_id", "req_unknown")}})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.exception("Unhandled request error request_id=%s", getattr(request.state, "request_id", "unknown"))
    return JSONResponse(status_code=500, content={"ok": False, "error": {"code": "internal_error", "message": "Внутренняя ошибка сервера"}, "meta": {"request_id": getattr(request.state, "request_id", "req_unknown")}})


@app.get("/", include_in_schema=False)
def index():
    path = PUBLIC / "index.html"
    return FileResponse(path) if path.exists() else JSONResponse({"ok": False, "error": {"code": "frontend_missing", "message": "Frontend не собран"}})


@app.get("/dashboard", include_in_schema=False)
@app.get("/admin", include_in_schema=False)
@app.get("/history", include_in_schema=False)
@app.get("/detection", include_in_schema=False)
@app.get("/api-docs", include_in_schema=False)
def spa():
    return FileResponse(PUBLIC / "index.html")


@app.get("/api/config", tags=["meta"])
def config():
    settings = get_settings()
    return {"ok": True, "data": {"app": "TVS Analytics", "version": "1.0.0", "environment": settings.app_env, "twitch_source": settings.twitch_source, "poll_interval_seconds": settings.poll_interval_seconds}}


if PUBLIC.exists():
    class NoCacheStatic(StaticFiles):
        """Serve frontend assets with revalidation so edits show up on reload.

        Starlette's StaticFiles sends an ETag but no Cache-Control, so browsers
        may keep a stale copy of app.js/styles.css and run old code. These files
        are small and always changing during development, so ask for a
        conditional revalidation instead of a blind cache hit.
        """

        def file_response(self, *args, **kwargs):
            response = super().file_response(*args, **kwargs)
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
            return response

    app.mount("/", NoCacheStatic(directory=PUBLIC, html=True), name="frontend")
