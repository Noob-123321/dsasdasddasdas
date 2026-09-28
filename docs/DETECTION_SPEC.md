# Bot / view-farm detection — design spec (authoritative)

This file is the contract. Implement against it. Where the existing repo wins,
follow the repo; where this spec adds a rule, the rule wins.

## 0. Ground rules

- Extend the existing TVS product in place. Do NOT fork, rename, or restructure.
  New code lives in `app/detect/` and `app/services/twitch_intel.py`.
- **Do not change** `app/analytics.py` semantics documented in `AGENTS.md`
  (`authorized = min(chatters, viewers)`, the `chat_ratio` clamp, `guests`,
  `risk_score` wording). Detection is an ADDITIVE layer.
- Python 3.10 target, `ruff` line-length 120, lint select `E,F,I`.
- No new third-party dependencies. stdlib + what `requirements.txt` already has.
- Never break the canonical check:
  `pytest -q` → `compileall -q app src tests tools` → `node --check public/app.js`
  → `ruff check app` → `alembic check`.
- All user-facing strings in `public/app.js` go through `t('key', 'Русский fallback')`
  and BOTH `I18N.ru` and `I18N.en` must contain the key.
- Every detector MUST be explainable: return the numbers that produced it.

## 1. What the anonymous Twitch GQL client can actually read (VERIFIED 2026-09-28)

This is measured, not assumed. Do not code against fields that are not here.

WORKS anonymously (Client-Id `kd1unb4b3q4t58fwlpcbzcbnm76a8fp`, no OAuth):

| Field | Query | Note |
|---|---|---|
| viewers, title, game, stream id/createdAt, isMature, freeformTags | `user(login:){stream{...}}` | `Stream.startedAt` does NOT exist; use `stream.createdAt` |
| channel `createdAt`, `followers.totalCount`, `lastBroadcast.startedAt` | `user(login:)` | follower count = idea #6 |
| up to 100 named `viewers` + `moderators`/`vips`/`broadcasters`/`chatbots` + `count` | CommunityTab persisted query `92168b44...` | **the single richest source** |
| per-account `createdAt` + `followers.totalCount` for a LIST of logins | `users(logins:[String!]!){id login createdAt followers{totalCount}}` | batches of 100 verified up to 200 |

DOES NOT WORK anonymously (verified rejected): `Channel.roles`,
`User.adBreak`/`adBreaks`/`adSchedule`/`isAdBreak`, `Stream.videoAds`/`preRollAds`,
`User.liveBroadcastSettings`, `Channel.chatSettings`,
`Stream.prerenderedViewersCount`, `Stream.peakViewersCount`,
`Stream.tags.name`, `Channel.panels.panelType`, GraphQL introspection (disabled).

Consequences the design must respect:

- **Ad breaks cannot be read directly.** Idea #8 (compare ad vs non-ad) must be
  implemented INFERENTIALLY — see §3.6. Do not invent an `adBreak` field.
- The CommunityTab `viewers` list is a **randomised alphabetical slice of 100**,
  verified: two polls 20 s apart had **0 % overlap**. It is a sample, not the
  population. Never treat it as "all chatters". It is great for *distribution*
  statistics (account age, follower count) and useless for tracking individuals
  or measuring "chatters active right now".
- `users(logins:)` is the only way to score individual accounts. Cost: one HTTP
  call per 100 chatters. Cache it hard (see §4).

## 2. The single most important data caveat (VERIFIED)

Measured on the live DB (`data/tvb.db`, 3276 samples): **59–63 % of consecutive
sample pairs have IDENTICAL (viewers, chatters)**. This is the poller's
change-aware dedup (`app/poller.py:112-126`), not real flatness. One `Sample` row
means "this value held for `repeat_count` polls", i.e. for
`repeat_count * poll_interval` seconds.

Therefore:

- **NEVER** compute flatness, volatility, autocorrelation, or spike slope on
  the raw sample list. You will measure the poller, not the channel.
- Every detector MUST first call `expand_series()` (§3.1) to rebuild a
  per-minute timeline, and MUST document that it operates on the expanded series.

## 3. The detector package `app/detect/`

Pure functions, no DB, no network. Input = expanded series + intel dict.
Every detector returns a `Finding` with `code`, `score` 0..1, `weight`,
`observed` (dict of the raw numbers), and a Russian `note`.

```python
@dataclass
class Finding:
    code: str
    score: float          # 0..1, how strongly this signal fired
    weight: float
    observed: dict        # the numbers that produced it
    note: str             # Russian, human readable
    explanation: str = "" # longer optional detail
```

### 3.1 `series.py` — expand_series
`expand_series(samples) -> list[Point]` rebuilds a uniform per-minute timeline
from `Sample` rows using `observed_at`, `last_seen_at`, `repeat_count`,
`interval_seconds`. `Point = (ts, viewers, chatters)`.
- Values are held flat across the span a sample covers (step function).
- Gaps longer than `max_gap_minutes` (default 15) become `None` and are
  excluded from statistics — never interpolate across a real gap.
- Export `median`, `mad`, `quantile` helpers here too.

### 3.2 `spikes.py` — резкие скачки онлайна
Detect step jumps on the expanded series. For each jump report
`amplitude` (ratio vs the pre-jump median), `rise_seconds` (how fast), and
whether it is `instant` (≤1 min). Keep the repo's `median_mad` philosophy but
fix the known bug in `app/analytics.py::detect_spikes`: `values[start]` /
`values[peak]` are indexed as dicts. Write a correct implementation here; do not
edit the old function.
Extra rules on top of the repo's:
- `no_justification` — jump amplitude ≥3× with no observed cause. Cause hints
  are collected by `causes.py`; if the jump is unexplained, this fires.
- `plateau_lock` — after a jump the series stays within ±0.5 % of one value for
  ≥20 consecutive minutes while viewers > 0. Directly from idea #1
  ("500–502 в течение часа").
- `repeat_shape` — two or more of the channel's own recent streams have
  near-identical normalised curves (see `shapes.py`). From idea #1.
- `staircase_return` — viewers collapse to ~0 within one sample of stream end.

### 3.3 `chat.py` — мёртвый чат при большом онлайне
- `silent_chat` — viewers ≥ 50 and chatters did not move for ≥ 10 min.
- `chat_starvation_ratio` — median `chatters/viewers` below an age/genre-aware
  floor. **Never use a single global constant**: the repo's own `AGENTS.md`
  gives the reference table (30/5 ok, 300/30-60 ok, 500/1 suspicious). Implement
  a monotone floor: below 50 viewers the ratio is meaningless, and the floor
  rises with viewer count. Expose the floor in `observed` so the UI can show it.
- `chat_collapse` — ratio fell ≥50 % vs the channel's own earlier median in this
  stream, while viewers rose. From idea #10.
- `single_chatter_dominance` — one account is the only one posting. **Requires
  chat messages, which the anonymous client cannot read.** Implement the
  detector against a `chat_events` input that the current adapter supplies as
  empty, mark it `unavailable`, and do NOT let it silently score 0.0 as if it
  passed. The poller must be able to feed it later.
- `passive_viewer_caveat` — always emit when a chat-related finding fires, as a
  neutral (weight 0) finding carrying the standard disclaimer.

### 3.4 `accounts.py` — проверка подписок и фолловеров (idea #6)
Operates on the CommunityTab roster + `users(logins:)` enrichment. This is the
highest-value detector and it is the one idea in the user's list that the
anonymous client fully supports.
- `fresh_account_cluster` — ≥3 sampled chatters with account age ≤30 days.
  Measured baseline: tumblurr 2 %, xqc 0 %. So the threshold must be a share,
  not a raw count. Use a share ≥ 12 % of the sample.
- `clustered_creation_dates` — ≥3 sampled chatters sharing the same
  `createdAt` day. A farm buys accounts in batches.
- `zero_follower_cluster` — ≥40 % of sampled chatters with `followers==0`.
  Measured: tumblurr 87 %, xqc 71 %. A "normal" channel is much lower, so this
  is a weak signal alone and must carry a LOW weight.
- `follower_burst` — channel `followers.totalCount` rose ≥3× between two
  observations of the same stream. Needs the follower count stored per sample.
- `follow_without_viewing` — followers grew ≥3× while the stream's median
  viewers stayed flat. The user's key point: followers ≠ viewers.

### 3.5 `shapes.py` — неестественное поведение онлайна (idea #9)
- `flatline` — on the EXPANDED series, the fraction of zero-delta minutes
  < 1 % for ≥30 min while viewers ≥ 20. (Raw samples always look flat; the
  expansion is what makes this meaningful.)
- `suspicious_smoothness` — count of second differences below a noise floor is
  ~0, i.e. the curve is piecewise-linear with no jitter. Compare the
  distribution of `Δ²` against the channel's own earlier streams.
- `low_entropy` — Shannon entropy of the rounded-to-nearest-10 viewers value is
  abnormally low (a real audience wanders; a farm sits on a constant).
- `time_of_day_independence` — hourly mean viewers are uncorrelated with the
  diurnal curve of the channel's other streams (needs ≥2 streams).
- `instant_restore` — after a stream ends and restarts, viewers return to the
  previous value within one sample.

### 3.6 `causes.py` — «ВАЖНАЯ ИДЕЯ»: ad vs non-ad comparison (idea #8)
Ad breaks are NOT readable anonymously (§1). So compare against proxies that
ARE observable, and be honest that they are proxies.

Observable proxies for "a mid-roll ad break just ran":
1. **Viewer cliff + rebound.** A single-interval drop of ≥12 % of the running
   median followed by a rebound to ≥90 % of the pre-drop median within 10 min.
   Measured in the live DB: xqc had 8 such drops >15 % of median.
2. **Chatter-count dip.** `chatters` drops with viewers but the ratio stays flat
   → viewers left for a fixed reason (the ad), not because interest fell.
3. **Title / game change.** `stream.title` or `game` changing mid-stream is an
   explicit external event. Store per-sample and diff it.
4. **Raid-ish influx.** A slow rise over 10–30 min with a simultaneous
   `followers` jump.

Produce `AdBreakEstimate` objects. Then the headline comparison the user asked
for: **`compare_ad_vs_nonad(stream)`** — split the stream timeline at the
estimated break times, and compare viewer growth, chat ratio, and follower
delta between the "ad windows" and the rest. If growth is materially higher
around a break, the traffic is ad-driven, not organic. Report both sides with
numbers. If no break is detected, say so explicitly rather than returning 0.

### 3.7 `score.py`
Aggregate `Finding`s into a 0–100 `DetectionReport`:
- `risk_score` = weighted mean of fired findings' `score`, ×100.
- `confidence` = f(sample count, observed minutes, fraction of metrics that had
  data). A detector whose input was missing LOWERS confidence, it does not
  score 0. The repo's own rule: `risk_score` describes unusual behaviour, not
  bot probability. Keep that wording in the UI.
- `verdict` = green/yellow/red on the repo's thresholds (<30 / 30–60 / >60).
- `factors` = the fired findings verbatim, for the explainability UI.
- Warnings must include "оценка описывает необычность поведения, а не вероятность
  ботов" and every unavailable metric.

## 4. Poller / persistence changes

- Add a new model `ChatterSnapshot` (channel_login, observed_at, count, and a
  JSON `roster` of the sampled logins + `roles` breakdown) and `ChannelIntel`
  (per-channel rolling: followers, channel_created_at, game, title, last_stream_id).
- Add `followers_count` and `chatters_roster` to `Sample`? **No** — instead put
  the volatile stuff on the new tables to avoid touching the migrated schema of
  the live `data/tvb.db`. Add a new Alembic migration (0003) and run
  `alembic check`.
- Poll the roster on a SLOWER cadence than viewers (default every 10th poll) —
  it is a sample, not the population, so more frequent polling buys nothing and
  costs an HTTP call. Make it configurable.
- Enrich chatters via `users(logins:)` at most once every N hours per channel
  (default 6 h) and cache results in a `ChatterAccount` table keyed by login.
  Repeated enrichment of the same logins is pure waste.
- Respect rate limits: one batched GQL request per channel per poll; batch the
  `users(logins:)` lookups in 100s; never loop per-login.

## 5. API + UI

- `GET /api/v1/channels/{login}/detection` and the profile-scoped twin.
  Returns the full `DetectionReport` (score, confidence, verdict, factors,
  warnings, series metadata, and the ad-vs-non-ad comparison).
- `GET /api/v1/channels/{login}/chatters` — the sampled roster + per-account
  enrichment (age, followers) so the user can see the evidence.
- `public/app.js`: a "Детекция накрутки" tab next to the existing history view.
  Render: verdict badge, score+confidence, the factor list with each factor's
  `observed` numbers, the viewer curve (reuse the existing chart conventions:
  ONE shared y-scale for both series), and the ad-vs-non-ad comparison block.
- All new strings via `t('key', 'fallback')`, ru+en symmetric.

## 6. Tests (must exist and pass)

- `tests/test_detect_series.py` — expansion correctness: repeat_count honoured,
  gap handling, no interpolation across gaps.
- `tests/test_detect_spikes.py` — synthetic jump detected; `plateau_lock` fires
  on a synthetic flat-after-jump series; no crash on <5 samples.
- `tests/test_detect_chat.py` — the reference table from `AGENTS.md` as a
  table-driven test: 30/5 ok, 300/30-60 ok, 500/1 suspicious, 1000/0-2 flagged.
- `tests/test_detect_accounts.py` — synthetic roster with 20 % fresh accounts
  fires; a healthy roster does not.
- `tests/test_detect_shapes.py` — synthetic flatline fires, natural noise does not.
- `tests/test_detect_causes.py` — synthetic ad-break pattern detected; comparison
  returns both sides; no-break case is explicit.
- Regression: the existing 35 tests must still pass unchanged.

## 7. Definition of done

- `python -m pytest -q` green, including the new tests.
- `python -m compileall -q app src tests tools` clean.
- `ruff check app` clean.
- `node --check public/app.js` clean AND the UI verified in a real browser.
- `python -m alembic check` clean (after `alembic upgrade head`).
- A CLI that runs the whole pipeline against the LIVE `data/tvb.db` and prints a
  report for a given channel, so the feature is proven on real data, not fixtures.
- Written summary of what each detector does and its known false-positive modes.
