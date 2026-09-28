# Remaining work — bot/view-farm detection (phase 2)

Everything in `DETECTION_SPEC.md` §1–§7 is implemented, wired and verified.
214 tests pass; ruff / compileall / node --check / alembic check are clean; the
UI was verified in real Chrome; the live `data/tvb.db` is byte-identical.

This file lists only what is still MISSING. Do these, then verify by running.

## 1. Documentation (the repo's own conventions require this — currently zero)

- `docs/methodology.md` has **0** mentions of detection. Add a section
  describing every detector, its threshold, its weight, and its known
  false-positive modes. Link `docs/DETECTION_SPEC.md` and
  `docs/DETECTION_CALIBRATION.md`.
- `docs/api.md` has **0** mentions. Document the four new routes:
  `GET /api/v1/channels/{login}/detection`,
  `GET /api/v1/channels/{login}/chatters`,
  `GET /api/profile/channels/{login}/detection`,
  `GET /api/profile/channels/{login}/chatters`.
  Include the response shape: `risk_score`, `confidence`, `verdict`,
  `factors[]` (each with `code`, `score`, `weight`, `observed`, `note`),
  `warnings[]`, `unavailable[]`, `points[]`, `ad_comparison`.
- `README.md`: add the CLI verb `python -m app.cli detect --login <login>`
  to the commands list, and mention the detection view + the two env vars.
- `AGENTS.md`: this file is the "stuff you will get wrong by guessing" file.
  Add a short section so the next agent does not repeat the two traps that
  cost real time:
  - `Sample.interval_seconds` is time since the previous CHANGED row, so it
    includes every second the poller was DOWN. Never use it as a hold
    duration — that bug produced a fake 1277-minute plateau and fired
    `plateau_lock`/`flatline` against an honest channel. Use `repeat_count`.
  - The CommunityTab roster is a randomised alphabetical slice (measured: 0 %
    overlap between two polls 20 s apart), never a population.
  - Amplitude alone must not convict: xqc ramped 918 → 28056 (x30) over
    114 min organically. Rise speed is the discriminator (`rise_speed()`).
- `.env.example` is missing `CHATTER_ROSTER_EVERY` and `CHATTER_ENRICH_HOURS`.
  Add both with the defaults actually used in `app/config.py`
  (10 and 6.0) and a one-line comment each. `app/config.py` already reads them.

## 2. Live-data test for the collectors

The 200+ tests all run with `TWITCH_SOURCE=demo`. Nothing proves the GQL
collectors parse a real Twitch response. Add
`tests/test_twitch_intel_parsing.py` that feeds **captured, trimmed real
response bodies** (not hand-written guesses) through the existing parsers
`parse_poll_payload`, `parse_roster`, `parse_accounts`, and asserts the
documented shape. Build the fixtures from the shapes recorded in
`docs/DETECTION_SPEC.md` §1. Mark them skipped if the fixtures are absent, so
the suite stays green either way.

Add one test that the parsers **reject** the anon-inaccessible field names
(`adBreak`, `adSchedule`, `liveBroadcastSettings`, `prerenderedViewersCount`)
so a future contributor cannot quietly reintroduce a field that Twitch
rejects — that error kills the whole batched request.

## 3. Regression test for the two data bugs already fixed

Both were found by running against real data, so lock them in:

- `tests/test_detect_series.py` already covers the `interval_seconds` fix.
  Add a sibling in `tests/test_detect_spikes.py` or `test_detect_shapes.py`
  that a stream containing a realistic poller outage (a `Sample` whose
  `interval_seconds` is ~21 h) does NOT fire `plateau_lock` or `flatline`.
- The rise-speed gate: assert that an unexplained ×30 jump that took 114
  minutes scores < 0.2 while the same amplitude in 60 s scores > 0.3. (The unit
  test exists; add the end-to-end variant through `build()` with the real
  numbers from the live database, xqc's 918 → 28056.)

## 4. Unavailable-metric plumbing must never fake a pass

`single_chatter_dominance` is implemented but the anonymous client cannot read
chat messages, so it must stay `unavailable` and must NOT score 0.0 as if it
passed. Confirm `app/detect/score.py` and `pipeline.py` treat a missing metric
as *lowering confidence*, and add a test asserting that a report built with
`chat_events=[]` lists `chat_events` in `unavailable[]` and that `confidence`
is strictly lower than the same input with events supplied.

## 5. Definition of done for this phase

- `python -m pytest -q` green (expect the new tests to raise the count above 214).
- `python -m compileall -q app src tests tools` clean.
- `ruff check app` clean.
- `node --check public/app.js` clean.
- `alembic check` clean against a COPY of the database in a scratch dir.
- `md5sum data/tvb.db` unchanged — the live database must stay byte-identical.
  Never run a migration or a test against it.
- Paste the real terminal output of each command. Do not describe it.
