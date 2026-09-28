"""Tests for :mod:`app.detect.accounts` (spec §3.4).

The fixtures are synthetic rosters: the CommunityTab roster is a <=100-login
sample, so these tests assert *shares of the enriched sample*, never "the channel
has N bots".
"""
from __future__ import annotations

import datetime as dt
import unittest

from app.detect.accounts import WEIGHTS, account_findings

NOW = dt.datetime(2026, 9, 28, 12, 0, 0)

OBSERVED_KEYS = {
    "fresh_account_cluster": {
        "fresh",
        "sampled",
        "share",
        "threshold_share",
        "max_age_days",
        "ages_days",
    },
    "clustered_creation_dates": {"day", "count", "sampled", "share", "days"},
    "zero_follower_cluster": {"zero_followers", "sampled", "share", "threshold_share"},
    "follower_burst": {
        "stream_id",
        "first_followers",
        "last_followers",
        "ratio",
        "first_ts",
        "last_ts",
    },
    "follow_without_viewing": {
        "followers_ratio",
        "viewers_ratio",
        "first_viewers",
        "last_viewers",
        "stream_id",
    },
}


def account(age_days: float | None = None, followers: int | None = None, account_id: str = "1") -> dict:
    """Enrichment row as ``users(logins:)`` returns it; ``age_days`` is relative to NOW."""
    return {
        "created_at": None if age_days is None else NOW - dt.timedelta(days=age_days),
        "followers": followers,
        "id": account_id,
    }


def roster_accounts(
    ages: list[float | None], followers: list[int | None], *, spread_days: float = 0.0
) -> tuple[list[str], dict]:
    """Roster + enrichment built from two parallel lists (one entry per chatter).

    ``spread_days`` staggers the creation timestamps so a roster does not
    accidentally share one calendar day (which is its own finding).
    """
    logins = [f"viewer{index}" for index in range(len(ages))]
    accounts = {
        login: account(age_days=None if age is None else age + index * spread_days,
                       followers=count, account_id=f"id{index}")
        for index, (login, age, count) in enumerate(zip(logins, ages, followers))
    }
    return logins, accounts


def healthy_roster(size: int = 12) -> tuple[list[str], dict]:
    """Old accounts with plenty of followers, each created on its own day."""
    return roster_accounts(
        [1800.0] * size, [500 + index for index in range(size)], spread_days=1.0
    )


def history_point(minutes_ago: float, followers: int, *, stream_id: str = "s1", viewers=None) -> dict:
    return {
        "observed_at": NOW - dt.timedelta(minutes=minutes_ago),
        "followers": followers,
        "stream_id": stream_id,
        "viewers_median": viewers,
    }


def by_code(findings: list) -> dict:
    return {finding.code: finding for finding in findings}


class GuardTests(unittest.TestCase):
    """The roster is a sample: too little enrichment means "cannot say anything"."""

    def test_no_enrichment_returns_nothing(self):
        self.assertEqual(account_findings(["a", "b", "c"], {}, now=NOW), [])

    def test_fewer_than_three_enriched_accounts_returns_nothing(self):
        logins, accounts = roster_accounts([5.0, 5.0], [0, 0])
        self.assertEqual(account_findings(logins, accounts, now=NOW), [])

    def test_unknown_logins_are_not_counted_as_zero(self):
        logins, accounts = roster_accounts([10.0] * 6, [0] * 6)
        for login in logins[3:]:
            del accounts[login]
        findings = account_findings(logins, accounts, now=NOW)
        fresh = by_code(findings)["fresh_account_cluster"]
        self.assertEqual(fresh.observed["sampled"], 3)
        self.assertEqual(fresh.observed["fresh"], 3)

    def test_history_without_enrichment_still_returns_nothing(self):
        _, accounts = roster_accounts([5.0, 5.0], [0, 0])
        history = [history_point(10, 100, viewers=500.0), history_point(1, 400, viewers=500.0)]
        self.assertEqual(account_findings(["a", "b"], accounts, follower_history=history, now=NOW), [])

    def test_roster_is_deduplicated_and_case_insensitive(self):
        logins = ["ViewerA", "viewera", "VIEWERA", "b", "c"]
        accounts = {name: account(age_days=5.0, followers=0) for name in ["viewera", "b", "c"]}
        findings = account_findings(logins, accounts, now=NOW)
        self.assertEqual(by_code(findings)["fresh_account_cluster"].observed["sampled"], 3)


class FreshAccountClusterTests(unittest.TestCase):
    def test_twenty_percent_fresh_fires(self):
        # 20 sampled chatters, 4 of them created 5-8 days ago (each on its own day,
        # so the creation-date cluster cannot fire here).
        ages = [5.0] * 4 + [1000.0] * 16
        logins, accounts = roster_accounts(ages, [500] * 20, spread_days=1.0)
        findings = account_findings(logins, accounts, now=NOW)
        self.assertEqual([finding.code for finding in findings], ["fresh_account_cluster"])
        finding = findings[0]
        self.assertEqual(finding.weight, 0.18)
        self.assertEqual(finding.observed["fresh"], 4)
        self.assertEqual(finding.observed["sampled"], 20)
        self.assertEqual(finding.observed["share"], 0.2)
        self.assertEqual(finding.observed["threshold_share"], 0.12)
        self.assertEqual(finding.observed["max_age_days"], 30.0)
        self.assertEqual(len(finding.observed["ages_days"]), 4)
        self.assertTrue(all(age <= 30 for age in finding.observed["ages_days"]))
        self.assertAlmostEqual(finding.score, 0.2 / 0.24, places=4)
        self.assertIn("4 из 20", finding.note)

    def test_share_and_count_thresholds(self):
        cases = [
            ("4 of 20 = 20%", 4, 20, True),
            ("3 of 25 = 12%", 3, 25, True),
            ("3 of 30 = 10%", 3, 30, False),
            ("2 of 10 = 20% but only two accounts", 2, 10, False),
            ("0 of 20", 0, 20, False),
        ]
        for label, fresh, total, expected in cases:
            with self.subTest(label):
                ages = [5.0] * fresh + [1000.0] * (total - fresh)
                logins, accounts = roster_accounts(ages, [500] * total)
                findings = by_code(account_findings(logins, accounts, now=NOW))
                self.assertEqual("fresh_account_cluster" in findings, expected)

    def test_boundary_age_of_30_days_counts_and_31_does_not(self):
        logins, accounts = roster_accounts([30.0, 30.0, 30.0, 30.0], [0, 0, 0, 0])
        self.assertIn("fresh_account_cluster", by_code(account_findings(logins, accounts, now=NOW)))
        logins, accounts = roster_accounts([31.0] * 4, [0, 0, 0, 0])
        self.assertNotIn(
            "fresh_account_cluster", by_code(account_findings(logins, accounts, now=NOW))
        )

    def test_default_now_uses_the_wall_clock(self):
        # created_at is built from the same clock, so this is stable in any timezone.
        real_now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        logins = [f"viewer{index}" for index in range(4)]
        accounts = {
            login: {"created_at": real_now - dt.timedelta(days=1), "followers": 0, "id": login}
            for login in logins
        }
        findings = by_code(account_findings(logins, accounts))
        self.assertIn("fresh_account_cluster", findings)

    def test_missing_created_at_lowers_the_sample_not_the_share(self):
        # 3 fresh of 3 aged accounts, 3 more enriched accounts without a created_at.
        logins, accounts = roster_accounts([5.0] * 3, [0] * 3)
        for index, login in enumerate(["unknown1", "unknown2", "unknown3"]):
            logins.append(login)
            accounts[login] = {"created_at": None, "followers": None, "id": f"x{index}"}
        findings = by_code(account_findings(logins, accounts, now=NOW))
        self.assertEqual(findings["fresh_account_cluster"].observed["sampled"], 3)
        self.assertEqual(findings["fresh_account_cluster"].observed["share"], 1.0)


class ClusteredCreationDatesTests(unittest.TestCase):
    def test_three_accounts_on_one_day_fires(self):
        logins = ["a", "b", "c", "d", "e", "f"]
        same_day = dt.datetime(2020, 5, 5, 10, 0, 0)
        accounts = {
            "a": {"created_at": same_day, "followers": 10, "id": "a"},
            "b": {"created_at": same_day.replace(hour=23), "followers": 10, "id": "b"},
            "c": {"created_at": same_day.replace(hour=1), "followers": 10, "id": "c"},
            "d": {"created_at": dt.datetime(2020, 5, 6), "followers": 10, "id": "d"},
            "e": {"created_at": dt.datetime(2020, 5, 7), "followers": 10, "id": "e"},
            "f": {"created_at": dt.datetime(2020, 5, 8), "followers": 10, "id": "f"},
        }
        findings = by_code(account_findings(logins, accounts, now=NOW))
        finding = findings["clustered_creation_dates"]
        self.assertEqual(finding.weight, 0.16)
        self.assertEqual(finding.observed["day"], "2020-05-05")
        self.assertEqual(finding.observed["count"], 3)
        self.assertEqual(finding.observed["sampled"], 6)
        self.assertEqual(finding.observed["share"], 0.5)
        self.assertEqual(finding.observed["days"], 4)
        self.assertAlmostEqual(finding.score, 0.5, places=4)

    def test_two_accounts_on_one_day_does_not_fire(self):
        cases = [("two on one day", 2, 4), ("one per day", 1, 5), ("zero cluster", 0, 5)]
        for label, same_day_count, total in cases:
            with self.subTest(label):
                logins = [f"viewer{index}" for index in range(total)]
                accounts = {}
                for index, login in enumerate(logins):
                    if index < same_day_count:
                        created = dt.datetime(2020, 5, 5, index, 0, 0)
                    else:
                        created = dt.datetime(2020, 6, 1 + index)
                    accounts[login] = {"created_at": created, "followers": 10, "id": login}
                findings = by_code(account_findings(logins, accounts, now=NOW))
                self.assertNotIn("clustered_creation_dates", findings)


class ZeroFollowerClusterTests(unittest.TestCase):
    def test_forty_five_percent_zero_followers_fires_the_low_weight_finding(self):
        ages = [1000.0] * 20
        followers = [0] * 9 + [120] * 11
        logins, accounts = roster_accounts(ages, followers)
        findings = by_code(account_findings(logins, accounts, now=NOW))
        finding = findings["zero_follower_cluster"]
        self.assertEqual(finding.weight, 0.05)
        self.assertEqual(finding.observed["zero_followers"], 9)
        self.assertEqual(finding.observed["sampled"], 20)
        self.assertEqual(finding.observed["share"], 0.45)
        self.assertEqual(finding.observed["threshold_share"], 0.4)
        self.assertAlmostEqual(finding.score, 0.45 / 0.8, places=4)

    def test_share_threshold(self):
        cases = [("8 of 20 = 40%", 8, 20, True), ("7 of 20 = 35%", 7, 20, False), ("0 of 20", 0, 20, False)]
        for label, zero, total, expected in cases:
            with self.subTest(label):
                logins, accounts = roster_accounts([1000.0] * total, [0] * zero + [50] * (total - zero))
                findings = by_code(account_findings(logins, accounts, now=NOW))
                self.assertEqual("zero_follower_cluster" in findings, expected)

    def test_unknown_followers_are_excluded_from_the_sample(self):
        logins, accounts = roster_accounts([1000.0] * 8, [0] * 4 + [0] * 4)
        for login in logins[4:]:
            accounts[login]["followers"] = None
        findings = by_code(account_findings(logins, accounts, now=NOW))
        finding = findings["zero_follower_cluster"]
        self.assertEqual(finding.observed["sampled"], 4)
        self.assertEqual(finding.observed["share"], 1.0)


class FollowerHistoryTests(unittest.TestCase):
    def test_burst_inside_one_stream_fires_both_findings_when_viewers_are_flat(self):
        logins, accounts = healthy_roster()
        history = [
            history_point(30, 100, viewers=500.0),
            history_point(20, 250, viewers=505.0),
            history_point(10, 400, viewers=495.0),
        ]
        findings = by_code(account_findings(logins, accounts, follower_history=history, now=NOW))
        burst = findings["follower_burst"]
        self.assertEqual(burst.weight, 0.08)
        self.assertEqual(burst.observed["stream_id"], "s1")
        self.assertEqual(burst.observed["first_followers"], 100)
        self.assertEqual(burst.observed["last_followers"], 400)
        self.assertEqual(burst.observed["ratio"], 4.0)
        self.assertEqual(burst.observed["first_ts"], "2026-09-28T11:30:00")
        self.assertEqual(burst.observed["last_ts"], "2026-09-28T11:50:00")

        growth = findings["follow_without_viewing"]
        self.assertEqual(growth.weight, 0.10)
        self.assertEqual(growth.observed["followers_ratio"], 4.0)
        self.assertEqual(growth.observed["first_viewers"], 500.0)
        self.assertEqual(growth.observed["last_viewers"], 495.0)
        self.assertEqual(growth.observed["viewers_ratio"], 0.99)

    def test_no_follow_without_viewing_when_viewers_grew_too(self):
        logins, accounts = healthy_roster()
        history = [
            history_point(30, 100, viewers=500.0),
            history_point(20, 250, viewers=900.0),
            history_point(10, 400, viewers=1500.0),
        ]
        findings = by_code(account_findings(logins, accounts, follower_history=history, now=NOW))
        self.assertIn("follower_burst", findings)
        self.assertNotIn("follow_without_viewing", findings)

    def test_flat_viewer_boundary(self):
        cases = [
            ("+9% is flat", 500.0, 545.0, True),
            ("+11% is not flat", 500.0, 555.0, False),
            ("-9% is flat", 500.0, 455.0, True),
            ("no viewer intel at all", None, None, True),
        ]
        logins, accounts = healthy_roster()
        for label, first_viewers, last_viewers, expected in cases:
            with self.subTest(label):
                history = [
                    history_point(30, 100, viewers=first_viewers),
                    history_point(10, 400, viewers=last_viewers),
                ]
                findings = by_code(account_findings(logins, accounts, follower_history=history, now=NOW))
                self.assertEqual("follow_without_viewing" in findings, expected)

    def test_one_null_viewer_edge_is_not_claimed_as_flat(self):
        logins, accounts = healthy_roster()
        history = [history_point(30, 100, viewers=None), history_point(10, 400, viewers=500.0)]
        findings = by_code(account_findings(logins, accounts, follower_history=history, now=NOW))
        self.assertIn("follower_burst", findings)
        self.assertNotIn("follow_without_viewing", findings)

    def test_growth_below_three_x_does_not_fire(self):
        logins, accounts = healthy_roster()
        history = [history_point(30, 300, viewers=500.0), history_point(10, 400, viewers=500.0)]
        self.assertEqual(account_findings(logins, accounts, follower_history=history, now=NOW), [])

    def test_growth_across_two_streams_does_not_fire(self):
        logins, accounts = healthy_roster()
        history = [
            history_point(60, 100, stream_id="s1", viewers=500.0),
            history_point(30, 400, stream_id="s2", viewers=500.0),
        ]
        self.assertEqual(account_findings(logins, accounts, follower_history=history, now=NOW), [])

    def test_single_observation_does_not_fire(self):
        logins, accounts = healthy_roster()
        history = [history_point(30, 100, viewers=500.0)]
        self.assertEqual(account_findings(logins, accounts, follower_history=history, now=NOW), [])

    def test_stream_without_id_is_ignored(self):
        logins, accounts = healthy_roster()
        history = [
            history_point(30, 100, stream_id=None, viewers=500.0),
            history_point(10, 400, stream_id=None, viewers=500.0),
        ]
        self.assertEqual(account_findings(logins, accounts, follower_history=history, now=NOW), [])

    def test_history_is_ordered_defensively(self):
        logins, accounts = healthy_roster()
        history = [history_point(10, 400, viewers=495.0), history_point(30, 100, viewers=500.0)]
        burst = by_code(account_findings(logins, accounts, follower_history=history, now=NOW))[
            "follower_burst"
        ]
        self.assertEqual(burst.observed["first_followers"], 100)
        self.assertEqual(burst.observed["last_followers"], 400)

    def test_strongest_burst_wins(self):
        logins, accounts = healthy_roster()
        history = [
            history_point(60, 100, stream_id="small", viewers=500.0),
            history_point(50, 400, stream_id="small", viewers=500.0),
            history_point(30, 50, stream_id="big", viewers=500.0),
            history_point(10, 500, stream_id="big", viewers=500.0),
        ]
        burst = by_code(account_findings(logins, accounts, follower_history=history, now=NOW))[
            "follower_burst"
        ]
        self.assertEqual(burst.observed["stream_id"], "big")
        self.assertEqual(burst.observed["ratio"], 10.0)


class HealthyChannelTests(unittest.TestCase):
    """A channel with old, well-followed accounts must stay quiet."""

    def test_healthy_roster_fires_nothing(self):
        logins, accounts = healthy_roster(12)
        self.assertEqual(account_findings(logins, accounts, now=NOW), [])

    def test_healthy_roster_with_flat_history_fires_nothing(self):
        logins, accounts = healthy_roster(12)
        history = [
            history_point(30, 10000, viewers=1200.0),
            history_point(10, 10050, viewers=1190.0),
        ]
        self.assertEqual(account_findings(logins, accounts, follower_history=history, now=NOW), [])


class FindingContractTests(unittest.TestCase):
    def all_fired(self):
        """A roster that trips every roster finding plus a flat-viewer follower burst."""
        logins = [f"fresh{index}" for index in range(6)] + [f"old{index}" for index in range(6)]
        created = dt.datetime(2026, 9, 25, 9, 0, 0)
        accounts = {
            login: {"created_at": created, "followers": 0, "id": login}
            for login in logins[:6]
        }
        accounts.update(
            {
                login: {"created_at": dt.datetime(2019, 1, 1 + index), "followers": 500 + index, "id": login}
                for index, login in enumerate(logins[6:])
            }
        )
        history = [
            history_point(30, 100, viewers=500.0),
            history_point(10, 400, viewers=505.0),
        ]
        return account_findings(logins, accounts, follower_history=history, now=NOW)

    def test_every_code_fires_with_the_specified_weight(self):
        fired = by_code(self.all_fired())
        self.assertEqual(
            set(fired),
            set(WEIGHTS),
        )
        for code, finding in fired.items():
            self.assertEqual(finding.weight, WEIGHTS[code])
            self.assertEqual(finding.code, code)

    def test_weights_match_the_spec(self):
        self.assertEqual(
            WEIGHTS,
            {
                "fresh_account_cluster": 0.18,
                "clustered_creation_dates": 0.16,
                "zero_follower_cluster": 0.05,
                "follower_burst": 0.08,
                "follow_without_viewing": 0.10,
            },
        )

    def test_findings_carry_the_documented_evidence(self):
        for finding in self.all_fired():
            with self.subTest(finding.code):
                self.assertEqual(set(finding.observed), OBSERVED_KEYS[finding.code])
                self.assertGreater(finding.score, 0.0)
                self.assertLessEqual(finding.score, 1.0)
                self.assertEqual(finding.note_code, f"note_{finding.code}")
                self.assertEqual(set(finding.note_args), set(finding.observed))
                self.assertTrue(finding.note)

    def test_context_never_changes_the_verdict(self):
        logins, accounts = healthy_roster()
        baseline = account_findings(logins, accounts, now=NOW)
        with_context = account_findings(
            logins, accounts, viewer_median=1234.5, observed_minutes=90.0, now=NOW
        )
        self.assertEqual(baseline, with_context)

        fresh_logins, fresh_accounts = roster_accounts(
            [5.0] * 4 + [1000.0] * 16, [500] * 20, spread_days=1.0
        )
        fired = account_findings(
            fresh_logins, fresh_accounts, viewer_median=1234.5, observed_minutes=90.0, now=NOW
        )
        self.assertEqual([finding.code for finding in fired], ["fresh_account_cluster"])
        self.assertIn("наблюдение 90 мин", fired[0].explanation)


if __name__ == "__main__":
    unittest.main()
