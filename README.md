# TVS Analytics

Twitch portfolio analytics behind a personal `TVS_` license key. A user opens
the site, enters one key, and sees a dark portfolio dashboard with live
snapshots, history, explainable anomaly scores, exports, API keys and alerts.

The visual direction is intentionally close to a dense dark operations console:
muted indigo surfaces, a violet action color, compact monospace numbers and
green/amber/red data states. It is a responsive SPA served by FastAPI.

## Operations helper

For the complete Russian release and safe-update runbook, see
[`docs/USER_GUIDE.md`](docs/USER_GUIDE.md).

The same commands work on Windows and Linux through the wrappers:

```text
# Windows PowerShell (in cmd.exe use tvs.bat without .\)
.\tvs.bat doctor
.\tvs.bat up
.\tvs.bat status
.\tvs.bat update

# Linux/macOS
./tvs.sh doctor
./tvs.sh up
./tvs.sh status
./tvs.sh update
```

The root-level `tvs.bat` and `tvs.sh` wrappers are equivalent. The Python
implementation is `scripts/tvs.py`. Double-clicking `tvs.bat` opens a small
menu for local start, status, logs, backup, update and checks. It creates
backups before updates, never removes Docker volumes, and never deletes
`data/token.key`.

## Quick start (local)

```powershell
copy .env.example .env
# For real Twitch data keep TWITCH_SOURCE=gql; use demo only for a deterministic smoke test.
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/>.

For an existing database after pulling schema changes, run once:

```powershell
python -m alembic upgrade head
```

On an empty database the first admin key is generated during startup and
written to `data/bootstrap_admin.txt`. You can instead provide a valid key in
`.env`:

```env
BOOTSTRAP_ADMIN_TOKEN=TVS_<128 random characters>
```

A valid TVS key is **132 characters total**: `TVS_` followed by exactly 128
random URL-safe characters. The key can be shown again from the admin panel;
the database stores a hash for lookup and an encrypted copy for controlled
reveal.

## User flow

1. Paste a `TVS_` key on `/`.
2. The server validates it and creates an HttpOnly browser session.
3. An empty profile shows the `Добавить` button.
4. Paste one or more Twitch links/logins into the multiline field. Inputs are
   split on whitespace, normalized, deduplicated and checked against the
   profile policy.
5. The background poller starts observing allowed channels every 60 seconds.
6. Use the sidebar to inspect portfolio, history, alerts, API keys and settings.

There are no user roles in this release. An admin key is a profile token with
the `admin` kind; profile keys can be restricted to an allowlist or opened to
all public Twitch channel logins.

## API keys

Inside a profile, create a child `tvs_` key. It inherits the parent profile's
channel scope and analytics, but expires or becomes invalid when the parent
TVS key is revoked/expired. Child keys are read-only in v1.

```http
Authorization: Bearer tvs_...
GET /api/v1/channels/tumblurr/snapshot
```

Interactive documentation is available at `/docs`, `/redoc` and
`/openapi.json`.

## Data and score semantics

The first Twitch adapter uses the existing anonymous GraphQL integration. It
is isolated behind `TwitchClient`; set `TWITCH_SOURCE=demo` for local smoke
tests. When the upstream source fails, the poller keeps the last stored
observation and exposes a stale state.

The UI deliberately does not call viewers "bots":

- `total_viewers` and `chatters_count` are observed facts;
- `authorized = min(chatters, viewers)`;
- `guests = max(viewers - authorized, 0)`;
- `chat_ratio = min(chatters / viewers, 1.0)` when both are available; raw diagnostic value is returned as `raw_chat_ratio`;
- `risk_score` (0–100) describes unusual behavior, not a probability;
- `confidence` (0–1) describes data quality and sample coverage.

Every score response includes factors, warnings and an explanation. Thresholds
and product choices are documented separately from upstream limitations.

- Alert guide: [`docs/alerts.md`](docs/alerts.md)

## Background poller

The app starts a background poller for local development. Production can run
it separately:

```powershell
python -m app.jobs.run_poller
python -m app.cli poll-once
python -m app.cli detect --login <login>
python -m app.jobs.retention
```

`detect` runs the whole detection pipeline against a database and prints the
report, so the feature can be checked on real data instead of fixtures. It
takes `--db <path>` (defaults to `DATABASE_URL`), `--hours` (default 168) and
`--json` for the full payload.

Add `python -m alembic upgrade head` once on an existing database before using
it: the detection tables ship in migration `0005`.

The poller isolates channel errors, deduplicates unchanged viewer/chat pairs,
keeps stream sessions separate, and stops without pretending that a deployment
shutdown ended a Twitch stream.

Optional Telegram delivery is enabled with `TELEGRAM_BOT_TOKEN` and
`TELEGRAM_CHAT_ID`; without them, alert events remain available in the in-app
feed.

### Detection view

The SPA has a **"Детекция накрутки"** tab next to the history view. It shows
the verdict badge, the score with its confidence, every fired factor with the
raw numbers behind it, the viewer curve and the ad-vs-non-ad comparison block.

Two environment variables control the collection cost:

- `CHATTER_ROSTER_EVERY` (default `10`) — poll the chatter roster every Nth
  poll. The roster is a randomised sample of at most 100 logins, so sampling it
  more often buys no accuracy and costs an HTTP call each time.
- `CHATTER_ENRICH_HOURS` (default `6.0`) — re-enrich cached chatter accounts at
  most once every N hours per channel.

## Admin panel

The admin key provides:

- TVS/admin key creation, expiry editing, reveal, revoke and audit;
- profile allowlists and `unlimited` mode;
- active users/sessions and route-level request metrics;
- p50/p95 latency, errors, API request count, poller stats and database dialect;
- audit history for authentication and administrative mutations.

## API surface

Browser/profile:

- `POST /api/auth/redeem`
- `GET /api/auth/me`
- `POST /api/auth/logout`
- `GET /api/profile/overview`
- `POST /api/profile/channels`
- `GET /api/profile/channels/{login}/snapshot`
- `GET /api/profile/channels/{login}/history`
- `GET /api/profile/channels/{login}/anomalies`
- `GET /api/profile/channels/{login}/detection`
- `GET /api/profile/channels/{login}/chatters`
- `POST /api/profile/api-keys`
- `GET /api/profile/alerts`

Machine API v1:

- `GET /api/v1/channels/{login}/snapshot`
- `GET /api/v1/channels/{login}/history`
- `GET /api/v1/channels/{login}/anomalies`
- `GET /api/v1/channels/{login}/summary`
- `GET /api/v1/channels/{login}/detection`
- `GET /api/v1/channels/{login}/chatters`
- `GET /api/v1/portfolio`
- `POST /api/v1/batch/snapshots`

Operations:

- `GET /healthz`, `GET /health`, `GET /readyz`, `GET /metrics`
- `GET /api/admin/overview`, `/tokens`, `/profiles`, `/audit`, `/load`

The detection payload is documented in [`docs/api.md`](docs/api.md); every
detector, its threshold, its weight and its known false positives are in
[`docs/methodology.md`](docs/methodology.md).

## Configuration

See `.env.example`. Important production values:

- `DATABASE_URL` (PostgreSQL in Docker/production)
- `REDIS_URL`
- `TOKEN_ENCRYPTION_KEY` or `TOKEN_ENCRYPTION_KEY_FILE`
- `PUBLIC_BASE_URL` and `ALLOWED_ORIGINS` — for a tunnel/proxy, set the public origin (for example `https://your-domain.example`);
- `COOKIE_SECURE=1`
- `BOOTSTRAP_ADMIN_TOKEN` only for the first deployment

Secrets never belong in the repository, URLs, Referer or browser local storage.

## Tests and checks

```powershell
python -m compileall -q app src tests
node --check public/app.js
python -m pytest -q
```

The new tests use SQLite and demo Twitch data; production/load testing should
run against PostgreSQL/Redis with `TWITCH_SOURCE=gql` or a controlled fixture.

## Project layout

```text
app/
  main.py             FastAPI app, lifespan, middleware and static frontend
  config.py db.py     runtime configuration and SQLAlchemy engine
  models.py           profiles, tokens, observations, alerts and metrics
  security.py         token encryption, sessions, parser and rate limiting
  analytics.py        derived metrics, spikes and explainable score
  poller.py           change-aware background collector
  routers/            auth, profile, admin, API v1 and health routes
  detect/             pure bot/view-farm detectors, series expansion, scoring
  services/           Twitch adapter, detection reports, audit and metrics
public/               responsive SPA (HTML/CSS/JS)
scripts/tvs.py        cross-platform safe operations helper
tvs.bat / tvs.sh      Windows/Linux wrappers
show_admin_key.bat    local audited admin-key reveal helper
docs/USER_GUIDE.md    final usage, release, backup and update guide
plan/шаги.txt         combined plan
plan/функционал_и_проверка.txt  product comparison, acceptance matrix and verification status
docs/                 API and operations documentation
```

## Docker Compose

```powershell
docker compose up -d postgres redis
docker compose up --build api poller
```

The current machine does not have Docker installed, so local verification in
this workspace uses the Python development server. PostgreSQL/Redis and the
production reverse-proxy path remain configured in `docker-compose.yml`.
