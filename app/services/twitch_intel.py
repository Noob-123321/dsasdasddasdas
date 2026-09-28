"""Anonymous Twitch GQL access for channel intel and chatter rosters.

Verified by probing the public client-id (no OAuth, no integrity token) on
2026-09-28 -- see ``docs/DETECTION_SPEC.md`` §1 for the measured table. Only
fields confirmed to work anonymously are queried here:

* ``user(login:){createdAt followers{totalCount} lastBroadcast{startedAt}}``
* ``user(login:){stream{id type title viewersCount createdAt isMature game freeformTags}}``
* the CommunityTab persisted query, whose ``chatters`` object carries ``count``
  plus ``viewers``/``moderators``/``vips``/``broadcasters``/``chatbots``/``staff``
* ``users(logins:[String!]!){id login createdAt followers{totalCount}}``

``adBreak``/``adSchedule``/``ChatSettings``/introspection are rejected for this
client-id, so nothing here may depend on them.

The CommunityTab ``viewers`` list is a randomised alphabetical slice of at most
100 logins and must never be treated as the channel's population; it supports
distribution statistics (account age, follower counts) only.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import random
import urllib.error
import urllib.request
from typing import Any

from ..clock import as_utc
from ..config import Settings

GQL_URL = "https://gql.twitch.tv/gql"
TWITCH_CLIENT_ID = "kd1unb4b3q4t58fwlpcbzcbnm76a8fp"
COMMUNITY_TAB_HASH = "92168b4434c8f4d32df14510052131c3544b929723d5f8b69bb96c96207e483e"
ACCOUNT_BATCH_SIZE = 100

POLL_QUERY = """
query StreamInfo($login:String!){
  user(login:$login){
    id login displayName createdAt
    followers{totalCount}
    lastBroadcast{startedAt}
    stream{
      id type title viewersCount createdAt isMature
      game{id name}
      freeformTags{name}
    }
  }
}
"""

USERS_QUERY = """
query Accounts($logins:[String!]!){
  users(logins:$logins){
    id login createdAt followers{totalCount} lastBroadcast{startedAt}
    stream{id viewersCount}
  }
}
"""

NETWORK_ERRORS = (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError)


class TwitchUnavailable(RuntimeError):
    pass


def post_gql(payload: list[dict], timeout: float) -> Any:
    """POST a batched GraphQL payload with the anonymous client-id."""
    request = urllib.request.Request(
        GQL_URL,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Client-Id": TWITCH_CLIENT_ID, "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _logins(entries: Any) -> list[str]:
    result = []
    for entry in entries or []:
        if isinstance(entry, str):
            result.append(entry.lower())
        elif isinstance(entry, dict) and entry.get("login"):
            result.append(str(entry["login"]).lower())
    return result


def parse_roster(chatters: Any) -> dict:
    """Split a CommunityTab ``chatters`` object into the sample and the roles."""
    chatters = chatters or {}
    roles = {
        "broadcasters": _logins(chatters.get("broadcasters")),
        "moderators": _logins(chatters.get("moderators")),
        "vips": _logins(chatters.get("vips")),
        "chatbots": _logins(chatters.get("chatbots")),
        "staff": _logins(chatters.get("staff")),
    }
    roster = _logins(chatters.get("viewers"))
    return {
        "count": chatters.get("count"),
        "sampled": len(roster),
        "roster": roster,
        "roles": {name: entries for name, entries in roles.items() if entries},
    }


def parse_poll_payload(body: Any) -> dict:
    """Turn the batched StreamInfo + CommunityTab response into one flat dict."""
    if not isinstance(body, list) or not body:
        raise TwitchUnavailable("Twitch вернул неожиданный ответ")
    first = body[0] or {}
    user = ((first.get("data") or {}).get("user") or {})
    stream = user.get("stream") or {}
    if first.get("errors") and not stream:
        raise TwitchUnavailable(str(first["errors"]))
    chatters = {}
    if len(body) > 1:
        second = body[1] or {}
        chatters = ((second.get("data") or {}).get("user") or {}).get("channel", {}).get("chatters") or {}
    roster = parse_roster(chatters)
    is_live = stream.get("type") == "live"
    game = stream.get("game")
    tags = stream.get("freeformTags") or []
    return {
        "channel_id": user.get("id"),
        "channel_created_at": user.get("createdAt"),
        "followers_count": ((user.get("followers") or {}).get("totalCount")),
        "last_broadcast_at": ((user.get("lastBroadcast") or {}).get("startedAt")),
        "is_live": is_live,
        "stream_id": stream.get("id"),
        "stream_created_at": stream.get("createdAt"),
        "title": stream.get("title"),
        "game": game.get("name") if isinstance(game, dict) else game,
        "is_mature": stream.get("isMature"),
        "freeform_tags": [item.get("name") for item in tags if isinstance(item, dict) and item.get("name")],
        "viewer_count": stream.get("viewersCount") if is_live else None,
        "chatters_count": roster["count"] if is_live else None,
        "chatters_sampled": roster["sampled"] if is_live else 0,
        "chatters_roster": roster["roster"] if is_live else [],
        "chatters_roles": roster["roles"] if is_live else {},
        "chatters_error": None if chatters else "CommunityTab не вернул chatters",
    }


def parse_accounts(users: Any) -> list[dict]:
    """Normalise the ``users(logins:)`` response into cache rows."""
    result = []
    for item in users or []:
        if not isinstance(item, dict) or not item.get("login"):
            continue
        result.append(
            {
                "login": str(item["login"]).lower(),
                "account_id": str(item["id"]) if item.get("id") is not None else None,
                "twitch_created_at": as_utc(item.get("createdAt")),
                "followers_count": (item.get("followers") or {}).get("totalCount"),
                "last_broadcast_at": as_utc((item.get("lastBroadcast") or {}).get("startedAt")),
            }
        )
    return result


def demo_poll(login: str, moment: dt.datetime | None = None) -> dict:
    """Deterministic synthetic payload for ``TWITCH_SOURCE=demo``.

    The values are invented and only exist so the UI and tests exercise the
    intel/roster code paths without touching the network. Never present them as
    real Twitch observations.
    """
    moment = moment or dt.datetime(2026, 1, 1, 12, 0, 0)
    seed = int(hashlib.sha256(login.encode("utf-8")).hexdigest()[:8], 16)
    rnd = random.Random(seed + int(moment.timestamp()) // 60)
    baseline = 800 + seed % 15000
    viewers = max(1, baseline + rnd.randint(-baseline // 5, baseline // 5))
    roster = [f"demo_viewer_{seed % 1000}_{index}" for index in range(20)]
    return {
        "channel_id": f"demo_{seed}",
        "channel_created_at": "2020-01-01T00:00:00Z",
        "followers_count": 1000 + seed % 5000,
        "last_broadcast_at": moment.isoformat(),
        "is_live": True,
        "stream_id": f"demo_stream_{seed}",
        "stream_created_at": (moment - dt.timedelta(hours=2)).isoformat(),
        "title": f"Demo stream · {login}",
        "game": "Just Chatting",
        "is_mature": False,
        "freeform_tags": ["English"],
        "viewer_count": viewers,
        "chatters_count": max(1, int(viewers * (0.18 + ((seed % 50) / 1000)))),
        "chatters_roster": roster,
        "chatters_roles": {"moderators": roster[:1], "vips": roster[1:3]},
        "chatters_error": None,
    }


def demo_accounts(logins: list[str], moment: dt.datetime | None = None) -> list[dict]:
    """Deterministic enrichment for demo mode (synthetic, never real)."""
    moment = moment or dt.datetime(2026, 1, 1, 12, 0, 0)
    result = []
    for login in logins:
        seed = int(hashlib.sha256(login.encode("utf-8")).hexdigest()[:8], 16)
        age_days = seed % 1500
        result.append(
            {
                "login": login.lower(),
                "account_id": f"demo_acc_{seed}",
                "twitch_created_at": moment - dt.timedelta(days=age_days),
                "followers_count": (seed // 7) % 200,
                "last_broadcast_at": None,
            }
        )
    return result


class TwitchIntel:
    """Network gateway for the detection data sources."""

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def demo(self) -> bool:
        return self.settings.twitch_source == "demo"

    def poll_channel(self, login: str) -> dict:
        """One batched request per channel per poll: intel + chatter roster."""
        payload = [
            {"operationName": "StreamInfo", "variables": {"login": login}, "query": POLL_QUERY},
            {
                "operationName": "CommunityTab",
                "variables": {"login": login},
                "extensions": {"persistedQuery": {"version": 1, "sha256Hash": COMMUNITY_TAB_HASH}},
            },
        ]
        return parse_poll_payload(post_gql(payload, self.settings.twitch_timeout_seconds))

    def fetch_accounts(self, logins: list[str]) -> list[dict]:
        """Enrich logins in batches of 100; never loops per login."""
        unique = sorted({login.lower() for login in logins if login})
        result: list[dict] = []
        for start in range(0, len(unique), ACCOUNT_BATCH_SIZE):
            batch = unique[start:start + ACCOUNT_BATCH_SIZE]
            body = post_gql([{"operationName": "Accounts", "variables": {"logins": batch}, "query": USERS_QUERY}], self.settings.twitch_timeout_seconds)
            first = body[0] if isinstance(body, list) and body else {}
            if isinstance(first, dict) and first.get("errors"):
                raise TwitchUnavailable(str(first["errors"]))
            users = ((first.get("data") or {}).get("users")) or []
            if not users:
                raise TwitchUnavailable("Twitch не вернул данные аккаунтов")
            result.extend(parse_accounts(users))
        return result
