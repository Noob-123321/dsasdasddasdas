"""Smoke and security tests for the TVS Analytics (Twitch Viewers System) app."""
from __future__ import annotations

import os
import re
import unittest
from pathlib import Path

# Configure the app before importing its modules.
_TEST_DB = Path(__file__).parent / "_tvs_test.db"
if _TEST_DB.exists():
    _TEST_DB.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB.as_posix()}"
os.environ["TWITCH_SOURCE"] = "demo"
os.environ["POLLER_ENABLED"] = "0"
os.environ["BOOTSTRAP_ADMIN_TOKEN"] = "TVS_" + "A" * 128

from fastapi.testclient import TestClient

from app.analytics import RISK_WEIGHTS, derived_metrics, detect_spikes, score_rows
from app.db import SessionLocal, init_db
from app.main import app
from app.poller import Poller
from app.security import generate_tvs_token, normalize_login, parse_channel_input

init_db()

_SPA = Path(__file__).resolve().parent.parent / "public" / "app.js"


def _spa_catalog() -> dict[str, set[str]]:
    """Parse the SPA's I18N dictionaries so tests can check key symmetry."""
    lines = _SPA.read_text(encoding="utf-8").splitlines()
    start = next(index for index, line in enumerate(lines) if "const I18N = {" in line)
    end = next(index for index in range(start, len(lines)) if lines[index].strip() == "};")
    ru = next(index for index in range(start, end) if lines[index].strip() == "ru: {")
    en = next(index for index in range(ru, end) if lines[index].strip() == "en: {")

    def keys(first: int, last: int) -> set[str]:
        found = set()
        for line in lines[first + 1:last]:
            match = re.match(r"\s{6}([a-z0-9_]+):", line)
            if match:
                found.add(match.group(1))
        return found

    return {"ru": keys(ru, en), "en": keys(en, end)}


class TokenTests(unittest.TestCase):
    def test_tvs_format(self):
        token = generate_tvs_token()
        self.assertTrue(token.startswith("TVS_"))
        self.assertEqual(len(token), 132)

    def test_parser_accepts_links_and_bare_logins(self):
        accepted, invalid = parse_channel_input("https://twitch.tv/Tumblurr twitch.tv/pesh nope!")
        self.assertEqual(accepted, ["tumblurr", "pesh"])
        self.assertEqual(invalid, ["nope!"])
        self.assertEqual(normalize_login("https://www.twitch.tv/tumblurr?sr=a"), "tumblurr")

    def test_reserved_twitch_path_rejected(self):
        with self.assertRaises(ValueError):
            normalize_login("https://twitch.tv/directory")


class AnalyticsTests(unittest.TestCase):
    def test_derived_values(self):
        class Channel:
            latest_viewers = 100
            latest_chatters = 40
            latest_is_live = True
            latest_title = "Demo"
            latest_game = "Chat"
            latest_observed_at = None

        values = derived_metrics(Channel())
        self.assertEqual(values["guests"], 60)
        self.assertAlmostEqual(values["chat_ratio"], 0.4)
        self.assertAlmostEqual(values["raw_chat_ratio"], 0.4)

        class CappedChannel:
            latest_viewers = 100
            latest_chatters = 120
            latest_is_live = True
            latest_title = "Demo"
            latest_game = "Chat"
            latest_observed_at = None

        capped = derived_metrics(CappedChannel())
        self.assertEqual(capped["chat_ratio"], 1.0)
        self.assertEqual(capped["raw_chat_ratio"], 1.2)
        self.assertEqual(capped["authorized"], 100)

    def test_spike_and_explanation(self):
        rows = [{"observed_at": i, "last_seen_at": i + 1, "is_live": True, "viewers": 100, "chatters": 20} for i in range(8)]
        rows += [{"observed_at": i, "last_seen_at": i + 1, "is_live": True, "viewers": 500, "chatters": 20} for i in range(8, 10)]
        rows += [{"observed_at": i, "last_seen_at": i + 1, "is_live": True, "viewers": 100, "chatters": 20} for i in range(10, 18)]
        spikes = detect_spikes(rows)
        self.assertTrue(spikes)
        result = score_rows(rows, spikes)
        self.assertIn("не вероятность накрутки", result["explanation"])

    def test_score_strings_are_translatable(self):
        """Every generated score string must carry a language-neutral code.

        The score is computed once and stored, so the browser cannot translate
        the Russian text later. Without these codes the English UI falls back
        to Russian prose, which is the bug this guards against.
        """
        rows = [{"observed_at": i, "last_seen_at": i + 1, "is_live": True, "viewers": 100, "chatters": 3} for i in range(8)]
        rows += [{"observed_at": i, "last_seen_at": i + 1, "is_live": True, "viewers": 900, "chatters": 3} for i in range(8, 11)]
        rows += [{"observed_at": i, "last_seen_at": i + 1, "is_live": True, "viewers": 100, "chatters": 3} for i in range(11, 20)]
        result = score_rows(rows, detect_spikes(rows))

        self.assertEqual(result["explanation_code"], "explain_score")
        self.assertTrue(result["factors"], "expected at least one factor")
        for factor in result["factors"]:
            self.assertIn(factor["code"], RISK_WEIGHTS)
            self.assertTrue(factor["note_code"], f"{factor['code']} has no note_code")
            self.assertIsInstance(factor["note_args"], dict)
        # Every emitted code must be renderable in both UI languages.
        catalog = _spa_catalog()
        for code in [factor["note_code"] for factor in result["factors"]] + [item["code"] for item in result["warning_codes"]]:
            self.assertIn(code, catalog["ru"], f"missing ru translation for {code}")
            self.assertIn(code, catalog["en"], f"missing en translation for {code}")
        self.assertEqual(len(result["warnings"]), len(result["warning_codes"]))

    def test_spa_translations_are_symmetric(self):
        """A key present in only one language silently renders the other one."""
        catalog = _spa_catalog()
        self.assertEqual(catalog["ru"] ^ catalog["en"], set())

    def test_every_factor_code_has_both_labels(self):
        """The UI prints factor codes, so both languages need a label."""
        catalog = _spa_catalog()
        for code in RISK_WEIGHTS:
            self.assertIn(f"factor_{code}", catalog["ru"], f"missing ru label for {code}")
            self.assertIn(f"factor_{code}", catalog["en"], f"missing en label for {code}")


class AdminMaintenanceTests(unittest.TestCase):
    def test_spa_routes_render_without_path_parameter(self):
        with TestClient(app) as client:
            for path in ("/dashboard", "/history", "/admin", "/api-docs"):
                response = client.get(path)
                self.assertEqual(response.status_code, 200, path)
                self.assertIn("TVS Analytics", response.text)

    def test_admin_can_clear_expiry(self):
        with TestClient(app) as client:
            admin = "TVS_" + "A" * 128
            self.assertEqual(client.post("/api/auth/redeem", json={"token": admin}).status_code, 200)
            created = client.post("/api/admin/tokens", json={"kind": "profile", "label": "clear-expiry", "expires_at": "2099-01-01T00:00:00Z"})
            self.assertEqual(created.status_code, 200)
            token_id = created.json()["data"]["id"]
            response = client.patch(f"/api/admin/tokens/{token_id}", json={"expires_at": None})
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.json()["data"]["expires_at"])

    def test_revoked_tokens_are_hidden_and_can_be_rotated(self):
        with TestClient(app) as client:
            admin = "TVS_" + "A" * 128
            response = client.post("/api/auth/redeem", json={"token": admin})
            self.assertEqual(response.status_code, 200)
            response = client.post("/api/admin/tokens", json={"kind": "profile", "label": "rotation-test"})
            self.assertEqual(response.status_code, 200)
            token_id = response.json()["data"]["id"]
            response = client.patch(f"/api/admin/tokens/{token_id}", json={"revoked": True})
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(token_id, [row["id"] for row in client.get("/api/admin/tokens").json()["data"]])
            self.assertIn(token_id, [row["id"] for row in client.get("/api/admin/tokens?include_revoked=true").json()["data"]])
            response = client.post(f"/api/admin/tokens/{token_id}/rotate")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["data"]["key"].startswith("TVS_"))


class FlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()
        admin = "TVS_" + "A" * 128
        response = cls.client.post("/api/auth/redeem", json={"token": admin})
        assert response.status_code == 200, response.text
        response = cls.client.post("/api/admin/tokens", json={"kind": "profile", "label": "Test profile", "unlimited": True})
        assert response.status_code == 200, response.text
        cls.profile_token = response.json()["data"]["key"]
        response = cls.client.post("/api/auth/redeem", json={"token": cls.profile_token})
        assert response.status_code == 200, response.text
        response = cls.client.post("/api/profile/channels", json={"text": "https://twitch.tv/tumblurr twitch.tv/pesh"})
        assert response.status_code == 200, response.text
        assert response.json()["data"]["added"] == ["tumblurr", "pesh"]

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def test_poller_and_overview(self):
        poller = Poller(SessionLocal)
        self.assertGreaterEqual(poller.poll_once(), 2)
        self.assertGreaterEqual(poller.poll_once(), 2)
        self.assertEqual(poller.stats["errors"], 0)
        response = self.client.get("/api/profile/overview")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]["channels"]), 2)
        self.assertTrue(all(item["trend"] for item in response.json()["data"]["channels"]))

    def test_child_api_usage_is_persisted(self):
        created = self.client.post("/api/profile/api-keys", json={"label": "usage-test"})
        self.assertEqual(created.status_code, 200)
        api_key = created.json()["data"]["key"]
        before = self.client.get("/api/profile/usage").json()["data"]["requests"]
        with TestClient(app) as api_client:
            response = api_client.get("/api/v1/portfolio", headers={"Authorization": f"Bearer {api_key}"})
        self.assertEqual(response.status_code, 200)
        after = self.client.get("/api/profile/usage").json()["data"]["requests"]
        self.assertGreaterEqual(after, before + 1)

    def test_child_api_key_cannot_escape_parent_scope(self):
        response = self.client.post("/api/profile/api-keys", json={"label": "integration"})
        self.assertEqual(response.status_code, 200)
        api_key = response.json()["data"]["key"]
        with TestClient(app) as api_client:
            response = api_client.get("/api/v1/channels/tumblurr/snapshot", headers={"Authorization": f"Bearer {api_key}"})
            self.assertEqual(response.status_code, 200)
            response = api_client.get("/api/v1/channels/does-not-exist/snapshot", headers={"Authorization": f"Bearer {api_key}"})
            self.assertEqual(response.status_code, 404)

    def test_webhook_secret_is_not_echoed(self):
        response = self.client.post("/api/profile/webhooks", json={"url": "https://example.com/hook", "secret": "s" * 24, "events": ["anomaly.detected"]})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("secret", response.json()["data"])
        self.assertTrue(response.json()["data"]["secret_set"])

    def test_alert_rules(self):
        response = self.client.post("/api/profile/alerts", json={"type": "viewer_spike", "threshold": 2})
        self.assertEqual(response.status_code, 200)
        response = self.client.get("/api/profile/alerts")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]["rules"]), 1)


if __name__ == "__main__":
    unittest.main()
