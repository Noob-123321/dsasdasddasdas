# Operations runbook

## Deploy

1. Set `APP_ENV=production`, a strong `TOKEN_ENCRYPTION_KEY`, PostgreSQL URL,
   Redis URL and `PUBLIC_BASE_URL`.
2. Run `tvs doctor` and review `.env` without printing secrets.
3. Run `tvs backup` before the first deployment update.
4. Run `tvs up`; the Compose API has its internal poller disabled and the
   dedicated `poller` service owns collection.
5. Check `/healthz`, `/readyz` and `/metrics`.
6. Verify an admin can redeem the bootstrap key and a profile can add a test
   channel.

The full Windows/Linux commands and restore procedure are in
[`docs/USER_GUIDE.md`](USER_GUIDE.md).

## Rollback

Stop the API and poller, restore the previous image, run the matching Alembic
revision, then start the old API/poller pair. Keep a database backup before a
schema migration.

## Twitch outage

The poller catches per-channel failures and applies backoff. The UI should
continue showing the last snapshot with a stale badge. Inspect the admin load
page for upstream error rate and `last_success_at`.

## Key compromise

Revoke the TVS key in the admin panel. Revoke child `tvs_` keys if they were
not linked to the revoked parent. Review the audit log for reveal/copy events.
A parent revoke invalidates the browser session and child API access on the
next request.

## Database/Redis outage

Stop only the affected worker first. Do not delete raw samples to recover disk
space. Restore PostgreSQL from the latest dump, verify `/readyz`, then restart
poller aggregation. Redis outage may reduce rate-limit performance; fail closed
for public mutations until it returns.

## Backups

Use `tvs backup` for a timestamped SQLite or PostgreSQL backup and test a
restore regularly. Keep the token encryption key in a separate secret manager;
a database dump without the key cannot reveal administrator-created secrets.
