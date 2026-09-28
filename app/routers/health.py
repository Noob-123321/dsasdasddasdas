"""Liveness and readiness endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from ..db import engine
from ..services.metrics import metrics

router = APIRouter(tags=["health"])


@router.get("/healthz")
@router.get("/health")
def healthz():
    return {"ok": True, "status": "ok"}


@router.get("/readyz")
def readyz():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"ok": True, "status": "ready", "database": "ok"}
    except Exception as exc:
        return {"ok": False, "status": "not_ready", "database": "error", "detail": str(exc)[:200]}


@router.get("/v1/models")
@router.get("/v1/chat/completions")
def openai_probe_not_supported():
    """Answer OpenAI-compatible probes explicitly.

    Some browser extensions and local AI tools scan localhost ports for an
    OpenAI-compatible server. TVS Analytics is not one, so we return a clear
    JSON 404 instead of an unhandled default error.
    """
    raise HTTPException(status_code=404, detail={"code": "not_supported", "message": "TVS Analytics is not an OpenAI-compatible API"})


@router.get("/metrics")
def metrics_text():
    snapshot = metrics.snapshot()
    lines = [f"tvs_requests_total {snapshot['requests']}", f"tvs_errors_total {snapshot['errors']}", f"tvs_api_requests_total {snapshot['api_requests']}", f"tvs_request_latency_p50_ms {snapshot['p50_ms']}", f"tvs_request_latency_p95_ms {snapshot['p95_ms']}"]
    return "\n".join(lines) + "\n"
