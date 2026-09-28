# AGENTS.md

TVS Analytics — Twitch portfolio analytics behind a personal `TVS_` license key.
FastAPI + SQLAlchemy 2 + Alembic backend, dependency-free SPA in `public/`.
Full product docs live in `README.md`; this file is only the stuff you will get
wrong by guessing.

## Commands

Canonical check (runs everything, in order):

```powershell
python scripts/tvs.py check      # or: .\tvs.bat check   /   ./tvs.sh check
```

It is exactly: `pytest -q` → `compileall -q app src tests tools` →
`node --check public/app.js` → `ruff check app` → `alembic check`.

Individual steps:

```powershell
python -m pytest -q                          # whole suite (35 tests, ~7s)
python -m pytest -q tests/test_tvs_app.py    # one file
python -m pytest -q -k TokenTests            # one class
node --check public\app.js                   # JS syntax ONLY (see warning below)
ruff check app                               # CI lints only `app`, not tests
python -m alembic check                      # fails on model/schema drift
python -m alembic upgrade head               # after changing app/models.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000   # or: .\tvs.bat local
```

Standalone poller / maintenance: `python -m app.jobs.run_poller`,
`python -m app.cli poll-once`, `python -m app.jobs.retention`.
Other `tvs.py` verbs: `init, doctor, up, down, status, logs, backup, update,
restore-sqlite, show-admin-key, token`.

Local interpreter is Python 3.10 (`C:\Users\Artem\AppData\Local\Programs\Python\Python310\python.exe`);
`requires-python >=3.10`, ruff `target-version = "py310"`, CI runs 3.12 + node 22.

## The verification blind spot that has bitten this repo

`node --check public/app.js` only validates **syntax**. It cannot see a renamed
or missing identifier. A full green run (pytest + ruff + node --check +
alembic) once shipped a completely blank page: the i18n helper was defined as
`tr` while 347 call sites called `t()`, so every render threw
`ReferenceError: t is not defined` — and the throw happened inside
`setAppError`, masking the original failure.

**After any edit to `public/*.js` or `public/*.css`, verify in a real browser**
before reporting done. Open the page, read the console, and exercise the view you
touched. A JS problem renders as an empty `<div id="app">`, not as a test failure.

## Frontend conventions (`public/app.js`, ~1170 lines, no build step)

- One IIFE, no bundler, no npm. `public/` is served as-is; edit and reload.
- All user-facing strings go through `t('key', 'Русский fallback')`.
- `I18N = { ru: {...}, en: {...} }` — **both dictionaries must hold the same keys.**
  A key missing from `en` silently renders the Russian fallback, so drift is
  invisible until someone switches to English. Verify symmetry after adding keys:

```powershell
@'
import re, pathlib
L = pathlib.Path("public/app.js").read_text(encoding="utf-8").splitlines()
s = next(i for i,l in enumerate(L) if "const I18N = {" in l)
e = next(i for i in range(s, len(L)) if L[i].strip() == "};")
r = next(i for i in range(s, e) if L[i].strip() == "ru: {")
n = next(i for i in range(r, e) if L[i].strip() == "en: {")
k = lambda a,b: {m.group(1) for i in range(a+1,b) if (m:=re.match(r"\s{6}([a-z0-9_]+):", L[i]))}
ru, en = k(r,n), k(n,e)
used = {m.group(1) for l in L for m in re.finditer(r"(?<![A-Za-z0-9_$.])t\(\s*'([a-z0-9_]+)'", l)}
print("asymmetric:", sorted(ru ^ en) or "none", "| unresolved:", sorted(used - (ru|en)) or "none")
'@ | python -
```

- Helper locals are function-scoped. `chatPresent` lives inside `chartSvg`;
  referencing it from the sibling `detailHtml` threw at runtime while
  `node --check` stayed green. Re-declare locally instead of reaching out.
- Language choice persists in `localStorage` under `tvs_lang` (`ru` | `en`).
- Chart rule: both series must share **one** y-scale. Independent per-series
  min/max stretched each line to fill the plot, so the vertical gap between them
  carried no numeric meaning. Grid labels are printed identically on both sides.
- `K` in the UI is a compact thousands value: `15.0K` ≈ 15,000.

## Local state that is easy to destroy

- **The live database is `data/tvb.db` (~1.4 MB, 24 channels, ~2.4k samples),
  but `.env.example` says `data/tvs.db`.** Copying `.env.example` verbatim
  creates a *new empty* DB and silently orphans the real data. Keep
  `DATABASE_URL=sqlite:///./data/tvb.db` in `.env`.
- `.env` sets `TOKEN_ENCRYPTION_KEY` explicitly, so `data/token.key` is **not**
  the active key on this machine. Lose/rotate that value and every stored token
  becomes unrevealable (reveal and rotate break) — never regenerate it casually.
- `data/token.key`, `data/tvb.db`, and `data/*.bak` are persistent. Do not
  delete. `tvs.py backup` / `restore-sqlite` are the safe paths.
- Never leave a plaintext key or `__probe_key.txt` in `public/` — that directory
  is served to the internet. Remove it immediately after use.

## Two apps share this repo

- `app/` — the real product (FastAPI).
- `src/` — a separate, older standalone site (`channel`, `payments`, `render`,
  `server`, `subscriptions`, plus `twitch_gql_client.py`).
  `tests/test_site.py` puts `src/` on `sys.path` and exercises it over a
  `ThreadingHTTPServer`.

Both are in `compileall` and both must compile; a change in `src/` can break
`test_site.py` with no connection to `app/`.

## Detection traps that cost real time (do not re-derive these)

- **`Sample.interval_seconds` is NOT a hold duration.** The poller fills it with
  the time since the previous *changed* row, so it includes every second the
  poller was DOWN. Using it as a hold time turned a real 21 h outage into a fake
  1277-minute plateau and fired `plateau_lock`/`flatline` against an honest
  channel. The hold is `repeat_count * poll_interval`. `expand_series()` in
  `app/detect/series.py` already does this; the regression lives in
  `tests/test_detect_regressions.py::PollerOutageTests`, which also keeps a
  reference implementation of the OLD buggy semantics so the fixture keeps
  proving itself.
- **The CommunityTab `viewers` list is a sample, never a population.** It is a
  randomised alphabetical slice of at most 100 logins — measured: **0 % overlap**
  between two polls 20 s apart. Use it for distribution statistics (account age,
  follower counts) only. Never track individuals from it, and never conflate
  `count` (the reported total) with `len(roster)` (the slice).
- **Amplitude alone must not convict.** xqc ramped 918 → 28056 viewers (×30) over
  **114 minutes** organically. Rise speed is the discriminator: `rise_speed()` in
  `app/detect/spikes.py` keeps 1.0 at ≤ 300 s and decays to a floor of 0.15 at
  ≥ 1800 s, so the organic ramp scores 0.15 and cannot drive a verdict.
- **Ad breaks are unreadable anonymously.** `adBreak`/`adSchedule`/
  `liveBroadcastSettings`/`chatSettings`/`prerenderedViewersCount` are all
  rejected for this client-id, and ONE rejected field kills the entire batched
  request. The ad-vs-non-ad comparison is therefore inferential and says so in
  its note. `tests/test_twitch_intel_parsing.py` guards both directions: no
  query may emit a rejected field, and a real rejection must raise. The check is
  **type-qualified** — `Stream.startedAt` is rejected while
  `lastBroadcast{startedAt}` works, so a bare "no startedAt anywhere" rule would
  forbid a field the product depends on.
- **An unreadable metric must never score 0.0.** It lowers `confidence` and is
  listed in `unavailable[]`. `single_chatter_dominance` is the live case: the
  anonymous client cannot read chat messages, so it stays `unavailable` rather
  than passing silently.
- Detection is **additive**: it must not change `app/analytics.py` semantics
  (`authorized`, the `chat_ratio` clamp, `guests`, `risk_score` wording). The UI
  still never calls viewers "bots".
- `docs/methodology.md` holds the full detector inventory (threshold, weight and
  known false positives for each). Keep it in step with the `WEIGHTS` tables in
  `app/detect/*.py`.

## Tests

- `pyproject.toml` sets `testpaths = ["tests"]`, so the stray root `test_utf8.py`
  scratch file is never collected. `tests/new/` is empty.
- `tests/test_tvs_app.py` sets `DATABASE_URL`, `TWITCH_SOURCE=demo`,
  `POLLER_ENABLED=0`, `BOOTSTRAP_ADMIN_TOKEN` **before importing `app.*`**, then
  calls `init_db()`. Keep that ordering — it is why E402 exists there, and why
  `pyproject.toml` carries `[tool.ruff.lint.per-file-ignores] "tests/**" = ["E402"]`.
- It deletes and recreates `tests/_tvs_test.db` on every run, so tests never touch
  the real database.
- CI (`.github/workflows/ci.yml`) runs compileall, `ruff check app`, `pytest -q`,
  `node --check public/app.js`, and `alembic upgrade head` against
  `postgres:16` with `POLLER_ENABLED=0`. It does **not** run `alembic check`.

## Analytics semantics worth not breaking

`app/analytics.py::history_payload` computes:

- `authorized = min(chatters, viewers)`
- `guests = max(viewers - authorized, 0)`
- `chat_ratio = min(chatters / viewers, 1.0)`; `raw_chat_ratio` is unclamped

Twitch sometimes reports more chatters than viewers, so `authorized` gets capped
and then `authorized == total` and `chat_ratio == 1.0`. That is why the chart
tooltip marks such points `≥` with an explanation. `raw_chat_ratio > 1` is the
signal. Do not "fix" the clamp casually — it feeds `chat_ratio`, `guests`, and
`risk_score`, and `risk_score` describes unusual behaviour, not bot probability.
The UI deliberately never calls viewers "bots".

## Data source

Real data requires `TWITCH_SOURCE=gql` (the local `.env` already does).
`TWITCH_SOURCE=demo` is only for a deterministic smoke test — its numbers are
synthetic, and the UI shows a DEMO banner. Never report demo output as real.

## Branding and cache

- Product is **TVS — Twitch Viewers System**. New keys are `TVS_` / `tvs_`;
  a key is 132 chars (`TVS_` + 128). Legacy `TVB_` / `tvb_` keys still validate,
  and the live DB still contains them — do not rename live artifacts.
- `app/main.py` mounts `NoCacheStatic`, which adds
  `Cache-Control: no-cache, must-revalidate`. This is deliberate: Starlette's
  `StaticFiles` sends an ETag with no `Cache-Control`, and browsers then served a
  stale `app.js` / `styles.css`, making correct CSS edits look broken. If
  behaviour looks stale after an edit, hard-reload before debugging further.

## Known environment limits

Docker is **not installed** on this machine, so the Postgres/Redis Compose path
in `docker-compose.yml` is unverified locally; only CI covers it. Local work
uses the Python dev server. Telegram/webhook delivery has never been smoke
tested against a live endpoint.
