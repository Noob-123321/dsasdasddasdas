"""Measure whether viewers and chatters change independently."""
from __future__ import annotations

import argparse
import time

from app.config import get_settings
from app.services.twitch import TwitchClient


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("login")
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--interval", type=int, default=15)
    args = parser.parse_args()
    client = TwitchClient(get_settings())
    previous = None
    rows = []
    for _ in range(args.samples):
        stats = client.get_channel_stats(args.login)
        current = (stats.get("viewer_count"), stats.get("chatters_count"))
        if previous is not None:
            rows.append((current[0] != previous[0], current[1] != previous[1]))
        previous = current
        time.sleep(args.interval)
    print({"samples": len(rows), "viewer_only": sum(v and not c for v, c in rows), "chatter_only": sum(c and not v for v, c in rows), "both": sum(v and c for v, c in rows), "neither": sum(not v and not c for v, c in rows)})


if __name__ == "__main__":
    main()
