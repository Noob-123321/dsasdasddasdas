"""Parsers against CAPTURED live Twitch bodies (spec section 6, phase 2 §2).

Every fixture under ``tests/fixtures/`` is a trimmed copy of a real response from
``gql.twitch.tv`` taken on 2026-09-28 with the anonymous client-id; the shapes and
the numbers are recorded in ``docs/fixtures/live_twitch_responses.md``. The other
200+ tests run on ``TWITCH_SOURCE=demo`` and therefore never prove that the GQL
collectors understand a production response -- these do.

The whole class is skipped when the fixtures are absent, so a checkout without
them stays green.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import unittest

from app.clock import as_utc
from app.services import twitch_intel
from app.services.twitch_intel import TwitchUnavailable, parse_accounts, parse_poll_payload, parse_roster

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

#: ``(type, field)`` pairs the anonymous client-id rejects. One of them kills the
#: WHOLE batched request, so none may ever be queried again. The type matters:
#: ``Stream.startedAt`` does not exist, but ``lastBroadcast{startedAt}`` does.
FORBIDDEN_FIELDS = (
    ("User", "adBreak"),
    ("User", "adBreaks"),
    ("User", "adSchedule"),
    ("User", "isAdBreak"),
    ("User", "liveBroadcastSettings"),
    ("Channel", "chatSettings"),
    ("Channel", "roles"),
    ("Stream", "prerenderedViewersCount"),
    ("Stream", "peakViewersCount"),
    ("Stream", "videoAds"),
    ("Stream", "preRollAds"),
    ("Stream", "startedAt"),
    ("Stream", "tags"),
)

#: Selection sets of the only parent types we query, so a field can be checked
#: against the type that actually rejects it instead of the whole document.
PARENT_SELECTIONS = {"Stream": "stream"}


def _selection(query: str, field: str) -> str:
    """The selection set inside the first balanced ``field{...}`` of ``query``."""
    start = query.find(field + "{")
    if start < 0:
        return ""
    index = start + len(field)
    depth = 0
    begin = index
    while index < len(query):
        if query[index] == "{":
            depth += 1
        elif query[index] == "}":
            depth -= 1
            if depth == 0:
                return query[begin + 1:index]
        index += 1
    return query[begin:]


def _mentions(text: str, field: str) -> bool:
    """True when ``field`` appears as a selection token (``freeformTags`` != ``tags``)."""
    return re.search(rf"(?<![\w$]){re.escape(field)}\s*(?:\{{|,|\s|$)", text) is not None


def _load(name: str):
    path = FIXTURES / name
    if not path.exists():
        raise unittest.SkipTest(f"fixture {name} is absent; see docs/fixtures/live_twitch_responses.md")
    return json.loads(path.read_text(encoding="utf-8"))


class PollPayloadTests(unittest.TestCase):
    """``parse_poll_payload`` over the real StreamInfo response for xqc."""

    def setUp(self):
        self.body = _load("poll_query_response.json")
        self.parsed = parse_poll_payload(self.body)

    def test_counts_follow_the_capture(self):
        self.assertEqual(self.parsed["viewer_count"], 39648)
        self.assertEqual(self.parsed["followers_count"], 12569876)
        self.assertEqual(self.parsed["channel_id"], "71092938")
        self.assertEqual(self.parsed["stream_id"], "320551363424")

    def test_stream_flags_and_game(self):
        self.assertIs(self.parsed["is_live"], True)
        self.assertIs(self.parsed["is_mature"], False)
        self.assertEqual(self.parsed["game"], "Grand Theft Auto V")
        self.assertEqual(self.parsed["freeform_tags"], ["English", "femboy", "DropsEnabled"])

    def test_timestamps_parse_to_aware_datetimes(self):
        # The capture carries fractional seconds and the parser keeps them:
        # truncating them would move a stream's real start by up to a second
        # whenever a report lines it up against the poll samples.
        self.assertEqual(as_utc(self.parsed["channel_created_at"]), dt.datetime(2014, 9, 12, 23, 50, 5, 989719))
        self.assertEqual(as_utc(self.parsed["last_broadcast_at"]), dt.datetime(2026, 9, 27, 19, 47, 19, 897021))
        self.assertEqual(as_utc(self.parsed["stream_created_at"]), dt.datetime(2026, 9, 27, 19, 47, 14))

    def test_emoji_title_survives_unchanged(self):
        title = self.parsed["title"]
        self.assertIn("🤖", title)
        self.assertIn("GRINDFATHER IS BACK", title)
        self.assertEqual(title, self.body[0]["data"]["user"]["stream"]["title"])
        # UTF-8 round trip: the same title must survive a dump/load cycle.
        self.assertEqual(json.loads(json.dumps(title, ensure_ascii=False)), title)

    def test_single_element_batch_has_no_chatters_instead_of_raising(self):
        self.assertEqual(self.parsed["chatters_count"], None)
        self.assertEqual(self.parsed["chatters_roster"], [])
        self.assertIsNotNone(self.parsed["chatters_error"])

    def test_offline_channel_is_not_an_error(self):
        offline = json.loads(json.dumps(self.body))
        offline[0]["data"]["user"]["stream"] = None
        parsed = parse_poll_payload(offline)

        self.assertIs(parsed["is_live"], False)
        self.assertIsNone(parsed["viewer_count"])
        self.assertIsNone(parsed["chatters_count"])
        self.assertEqual(parsed["game"], None)
        # The channel-level fields survive an offline stream.
        self.assertEqual(parsed["followers_count"], 12569876)


class RosterTests(unittest.TestCase):
    """``parse_roster`` over the real CommunityTab ``chatters`` object."""

    def setUp(self):
        self.chatters = _load("roster_chatters.json")
        self.parsed = parse_roster(self.chatters)

    def test_count_is_the_population_and_sampled_is_the_slice(self):
        self.assertEqual(self.parsed["count"], 29150)
        self.assertEqual(self.parsed["sampled"], 6)
        self.assertEqual(len(self.parsed["roster"]), 6)
        # The trap in DETECTION_SPEC.md §1: the two numbers are never conflated.
        self.assertNotEqual(self.parsed["count"], self.parsed["sampled"])

    def test_login_objects_are_unwrapped_and_lowercased(self):
        payload = {
            "count": 2,
            "viewers": [{"login": "MixedCase", "__typename": "Chatter"}, {"login": "lower", "__typename": "Chatter"}],
        }
        parsed = parse_roster(payload)
        self.assertEqual(parsed["roster"], ["mixedcase", "lower"])

    def test_underscores_and_digits_are_legitimate_logins(self):
        self.assertIn("areski__", self.parsed["roster"])
        self.assertIn("1flaherty", self.parsed["roster"])
        self.assertIn("m0xyy", self.parsed["roles"]["moderators"])

    def test_missing_staff_key_is_tolerated(self):
        self.assertNotIn("staff", self.chatters)  # absent in the real capture
        self.assertNotIn("staff", self.parsed["roles"])
        self.assertIn("moderators", self.parsed["roles"])
        self.assertIn("chatbots", self.parsed["roles"])
        self.assertEqual(self.parsed["roles"]["broadcasters"], ["xqc"])

    def test_empty_roster_degrades_instead_of_raising(self):
        parsed = parse_roster(None)
        self.assertEqual(parsed["count"], None)
        self.assertEqual(parsed["sampled"], 0)
        self.assertEqual(parsed["roster"], [])
        self.assertEqual(parsed["roles"], {})


class AccountsTests(unittest.TestCase):
    """``parse_accounts`` over a real ``users(logins:)`` response."""

    def setUp(self):
        self.users = _load("users_query_response.json")["data"]["users"]
        self.parsed = parse_accounts(self.users)
        self.by_login = {row["login"]: row for row in self.parsed}

    def test_returns_exactly_the_documented_keys(self):
        self.assertEqual(
            sorted(self.parsed[0].keys()),
            ["account_id", "followers_count", "last_broadcast_at", "login", "twitch_created_at"],
        )

    def test_verbatim_real_row_round_trips(self):
        row = self.by_login["130h_"]
        self.assertEqual(row["account_id"], "825281278")
        self.assertEqual(row["twitch_created_at"], dt.datetime(2022, 9, 14, 12, 59, 26, 107271))
        self.assertEqual(row["followers_count"], 894)
        self.assertEqual(row["last_broadcast_at"], dt.datetime(2026, 8, 12, 0, 12, 19, 491441))

    def test_parser_does_not_derive_age(self):
        # Age is derived by the caller against "now"; a parser that returned
        # age_days would silently freeze the answer to the day it was written.
        for row in self.parsed:
            self.assertNotIn("age_days", row)

    def test_offset_timestamps_normalise_to_naive_utc(self):
        row = self.by_login["130h_"]
        self.assertIsNone(row["twitch_created_at"].tzinfo)
        self.assertIsNone(row["last_broadcast_at"].tzinfo)

    def test_rows_without_usable_fields_stay_as_nulls(self):
        row = self.by_login["sampler095"]
        self.assertIsNone(row["twitch_created_at"])
        self.assertIsNone(row["followers_count"])
        self.assertEqual(row["account_id"], "900000095")

    def test_entries_without_a_login_are_skipped(self):
        self.assertEqual(parse_accounts([{"id": "1"}, None, "nope"]), [])


class RejectedFieldTests(unittest.TestCase):
    """The anonymous client-id rejects these fields; one kills the whole batch."""

    def test_queries_never_emit_a_rejected_field(self):
        for name, query in (("POLL_QUERY", twitch_intel.POLL_QUERY), ("USERS_QUERY", twitch_intel.USERS_QUERY)):
            for parent, field in FORBIDDEN_FIELDS:
                with self.subTest(query=name, type=parent, field=field):
                    self.assertFalse(_mentions(query, field), f"{name} queries the rejected field {field}")
                    if parent == "Stream":
                        # `Stream.startedAt` is rejected while
                        # `lastBroadcast{startedAt}` is verified working, so the
                        # check has to look inside the stream selection only.
                        stream = _selection(query, "stream")
                        self.assertNotEqual(stream, "", "POLL_QUERY no longer selects a stream")
                        self.assertFalse(_mentions(stream, field))

    def test_working_fields_are_still_queried(self):
        # The guard above must not drift into a query that stops working.
        for query in (twitch_intel.POLL_QUERY, twitch_intel.USERS_QUERY):
            self.assertIn("createdAt", query)
            self.assertIn("followers", query)
        self.assertIn("lastBroadcast{startedAt}", twitch_intel.POLL_QUERY)
        self.assertIn("freeformTags{name}", twitch_intel.POLL_QUERY)
        self.assertIn("createdAt", _selection(twitch_intel.POLL_QUERY, "stream"))

    def test_a_rejected_field_fails_the_request_loudly(self):
        body = _load("graphql_field_error.json")
        self.assertIn("prerenderedViewersCount", body["errors"][0]["message"])
        with self.assertRaises(TwitchUnavailable):
            parse_poll_payload([body])
        with self.assertRaises(TwitchUnavailable):
            parse_poll_payload([{"errors": body["errors"], "data": {"user": {"stream": None}}}])

    def test_empty_batch_is_unavailable_not_an_exception(self):
        with self.assertRaises(TwitchUnavailable):
            parse_poll_payload([])
        with self.assertRaises(TwitchUnavailable):
            parse_poll_payload({"data": {}})


if __name__ == "__main__":
    unittest.main()
