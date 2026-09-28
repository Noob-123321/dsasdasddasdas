"""Probe which GraphQL fields the anonymous client-id can read.

Read-only capability probe. Uses anonymous operations (no operationName) so
Twitch does not reject the request with "operation with name X not found".
Prints the raw response shape for every query so the bot-detection feature set
can be planned against what actually works anonymously (no OAuth, no integrity
token).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

GQL_URL = "https://gql.twitch.tv/gql"
TWITCH_CLIENT_ID = "kd1unb4b3q4t58fwlpcbzcbnm76a8fp"
COMMUNITY_TAB_HASH = "92168b4434c8f4d32df14510052131c3544b929723d5f8b69bb96c96207e483e"

# name -> raw query text (anonymous operations only)
PROBES: dict[str, str] = {
    "stream_detail": """
      query($login:String!){
        user(login:$login){
          id login displayName createdAt isPartner
          lastBroadcast{ startedAt }
          followers{totalCount}
          stream{
            id title viewersCount startedAt createdAt
            prerenderedViewersCount
            game{id name displayName}
            tags{id name}
            freeformTags{name}
            type isMature
          }
        }
      }
    """,
    "channel_roles": """
      query($login:String!){
        user(login:$login){
          channel{
            roles{broadcaster{login displayName} moderator{login displayName}}
          }
        }
      }
    """,
    "ad_break": """
      query($login:String!){
        user(login:$login){ id stream{id} adBreak{ id duration } }
      }
    """,
    "panels": """
      query($login:String!){
        user(login:$login){
          id panels{ panelType profileImageURL links{ link text } }
        }
      }
    """,
    "chat_settings": """
      query($login:String!){
        user(login:$login){
          id
          liveBroadcastSettings{ slowMode{ messageInterval chatLimit } }
          stream{ id }
        }
      }
    """,
    "game_viewers": """
      query($login:String!){
        user(login:$login){ id stream{ id game{ id name } } }
      }
    """,
    "videos_clips": """
      query($login:String!){
        user(login:$login){
          id
          videos(first:3, type:ARCHIVE){ edges{ node{ id title publishedAt viewCount } } }
        }
      }
    """,
    "viewer_account_meta": """
      query($logins:[String!]!){
        users(logins:$logins){
          id login displayName createdAt isPartner
          followers{totalCount}
          stream{ viewersCount }
        }
      }
    """,
}


def post(payload: list[dict]) -> object:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        GQL_URL,
        data=data,
        method="POST",
        headers={
            "Client-Id": TWITCH_CLIENT_ID,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    login = "tumblurr"
    for name, query in PROBES.items():
        variables: dict = {"login": login}
        if name == "viewer_account_meta":
            variables = {"logins": ["tumblurr", "streamelements", "qtpippy"]}
        try:
            body = post([{"variables": variables, "query": query}])
        except urllib.error.HTTPError as exc:
            print(f"### {name}: HTTP {exc.code} {exc.read()[:300]!r}")
            continue
        except Exception as exc:  # noqa: BLE001 - probe tool
            print(f"### {name}: FAILED {exc}")
            continue
        print(f"### {name}")
        print(json.dumps(body, ensure_ascii=False, indent=2, default=str)[:2500])
        print()


if __name__ == "__main__":
    main()
