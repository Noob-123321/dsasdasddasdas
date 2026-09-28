"""Best-effort Telegram and signed webhook delivery for alert events."""
from __future__ import annotations

import hashlib
import hmac
import json
import urllib.error
import urllib.request

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clock import iso, utcnow
from ..config import Settings
from ..models import AlertEvent, Webhook, WebhookDelivery
from ..security import decrypt_secret


def send_telegram(text: str, settings: Settings) -> tuple[bool, str | None]:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return False, "Telegram не настроен"
    payload = json.dumps({"chat_id": settings.telegram_chat_id, "text": text, "disable_web_page_preview": True}, ensure_ascii=False).encode("utf-8")
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        request = urllib.request.Request(url, data=payload, method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=6) as response:
            return 200 <= response.status < 300, None if 200 <= response.status < 300 else f"HTTP {response.status}"
    except (urllib.error.URLError, TimeoutError) as exc:
        return False, str(exc)[:500]


def deliver_event(db: Session, event: AlertEvent, settings: Settings) -> None:
    """Attempt configured deliveries without blocking the poller forever."""
    message = event.payload.get("explanation") or f"TVS Analytics: {event.type}"
    telegram_ok, telegram_error = send_telegram(message, settings)
    if telegram_error:
        # The in-app event remains the source of truth; a missing Telegram
        # configuration is not an application error.
        pass
    db.flush()
    raw = json.dumps({"id": event.id, "type": event.type, "created_at": iso(event.created_at or utcnow()), "channel": event.channel_login, "data": event.payload}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(utcnow().timestamp()))
    webhooks = db.scalars(select(Webhook).where(Webhook.profile_id == event.profile_id, Webhook.enabled.is_(True)))
    for webhook in webhooks:
        if event.type not in (webhook.events or []) and "anomaly.detected" not in (webhook.events or []):
            continue
        delivery = WebhookDelivery(webhook_id=webhook.id, event_id=event.id, status="pending", attempts=1)
        db.add(delivery)
        try:
            secret = decrypt_secret(webhook.secret_encrypted, settings)
            signature = hmac.new(secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
            request = urllib.request.Request(webhook.url, data=raw, method="POST", headers={"Content-Type": "application/json", "X-TVS-Event": event.type, "X-TVS-Timestamp": timestamp, "X-TVS-Signature": signature})
            with urllib.request.urlopen(request, timeout=6) as response:
                delivery.status = "delivered" if 200 <= response.status < 300 else "failed"
                delivery.response_code = response.status
        except (urllib.error.URLError, TimeoutError) as exc:
            delivery.status = "failed"
            delivery.error = str(exc)[:1000]
        delivery.updated_at = utcnow()
