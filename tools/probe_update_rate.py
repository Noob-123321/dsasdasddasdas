"""Probe how often Twitch changes viewer/chat counters.

This is intentionally a manual tool, not a production poller.
"""
from __future__ import annotations

import argparse
import time

from app.config import get_settings
from app.services.twitch import TwitchClient


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("login")
    parser.add_argument("--samples", type=int, default=6)
    parser.add_argument("--interval", type=int, default=15)
    args = parser.parse_args()
    client = TwitchClient(get_settings())
    for index in range(args.samples):
        stats = client.get_channel_stats(args.login)
        print(index, stats.get("viewer_count"), stats.get("chatters_count"), stats.get("is_live"))
        if index + 1 < args.samples:
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
