"""Print the fields currently returned by the Twitch adapter."""
from __future__ import annotations

import argparse
import json

from app.config import get_settings
from app.services.twitch import TwitchClient


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("login")
    args = parser.parse_args()
    stats = TwitchClient(get_settings()).get_channel_stats(args.login)
    print(json.dumps(stats, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
