"""Audit event writer used by authentication and admin routes."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..clock import utcnow
from ..models import AuditLog


def record_audit(db: Session, *, actor: str, action: str, object_id: str | None = None, request_id: str | None = None, ip: str | None = None, details: dict | None = None) -> AuditLog:
    row = AuditLog(actor=actor[:64], action=action[:80], object_id=(object_id or None), request_id=(request_id or None), ip=(ip or None), details=details or {}, created_at=utcnow())
    db.add(row)
    return row
