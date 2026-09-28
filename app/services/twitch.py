"""Twitch data adapter with a deterministic demo mode for local development.

The anonymous GraphQL surface itself lives in :mod:`app.services.twitch_intel`;
this module is the poller-facing adapter and keeps the demo branch so the whole
pipeline can run without a network.
"""
from __future__ import annotations

from typing import Any

from ..clock import utcnow
from ..config import Settings
from .twitch_intel import (
    NETWORK_ERRORS,
    TwitchIntel,
    TwitchUnavailable,
    demo_accounts,
    demo_poll,
)

__all__ = ["TwitchClient", "TwitchUnavailable"]


class TwitchClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.intel = TwitchIntel(settings)

    def get_channel_stats(self, login: str) -> dict[str, Any]:
        if self.settings.twitch_source == "demo":
            return demo_poll(login, utcnow())
        try:
            return self.intel.poll_channel(login)
        except NETWORK_ERRORS as exc:
            raise TwitchUnavailable(f"Twitch недоступен: {exc}") from exc

    def get_accounts(self, logins: list[str]) -> list[dict]:
        """Per-account ``users(logins:)`` enrichment, batched in the gateway."""
        if self.settings.twitch_source == "demo":
            return demo_accounts(logins, utcnow())
        try:
            return self.intel.fetch_accounts(logins)
        except NETWORK_ERRORS as exc:
            raise TwitchUnavailable(f"Twitch недоступен: {exc}") from exc
