# Methodology and honest boundaries

## Observed values

- `viewer_count`: Twitch's current viewer counter when the channel is live.
- `chatters_count`: members reported by the CommunityTab source.
- `authorized`: capped at total viewers.
- `guests`: total minus authorized; guests are not automatically bots.
- `chat_ratio`: authorized-style chat count divided by total viewers, capped at 100%; the uncapped diagnostic value is returned as `raw_chat_ratio`.

## History

The poller runs every 60 seconds by default. A new observation is written when
the live flag, viewer count or chatter count changes. Unchanged observations
extend the existing row through `last_seen_at` and `repeat_count`.

## Anomaly detector

The initial detector uses the larger of:

- baseline × 1.5;
- baseline + 3 × MAD.

It records the threshold, baseline sample count, shape and warnings. A single
sample surrounded by normal values is marked `is_instant`; its shape and
duration are not invented.

## Score

Risk score combines low chat ratio, a viewer spike without corresponding chat
growth, and sawtooth dynamics. Missing factors are excluded and active weights
are renormalized. Confidence is a separate quality measure based on sample
count and observed duration.

No confirmed calibration corpus exists yet, so the product does not claim to
detect bots with a probability or to reliably identify events shorter than the
upstream counter's observation window.


## Bot / view-farm detection (`app/detect/`)

The detection layer is **additive** and does not change the analytics semantics
above. It is a set of pure functions: input is an expanded per-minute viewer
timeline plus channel intel, output is an explainable `DetectionReport`. It does
not modify `app/analytics.py`, and it never calls viewers "bots" — the index
describes how **unusual** the observed behaviour is.

Design contract: `docs/DETECTION_SPEC.md`. Measured calibration and the captured
Twitch responses: `docs/DETECTION_CALIBRATION.md` and
`docs/fixtures/live_twitch_responses.md`.

### The series every detector runs on

Measured on the live database: **59–63 % of consecutive sample pairs have
identical `(viewers, chatters)`**. That is the poller's change-aware dedup, not a
flat channel. One `Sample` row means "this value held for `repeat_count` polls".

So `series.expand_series()` first rebuilds a uniform per-minute step function from
`observed_at` / `last_seen_at` / `repeat_count`. Gaps longer than
`max_gap_minutes` (default 15) become `None` and are excluded from every
statistic — nothing is interpolated across a real gap. **Computing flatness,
volatility or spike slope on the raw sample list measures the poller, not the
channel.**

### Detector inventory

Weights are each detector's share of the aggregate index. `risk_score` is the
weighted mean of the *fired* findings' scores, ×100; a detector that did not fire
contributes nothing.

#### Spikes — `app/detect/spikes.py`

| Code | Weight | Fires when | Known false positives |
|---|---|---|---|
| `no_justification` | 0.22 | viewers rise ≥ 3× with no observed cause (title/game change, follower jump, raid) | A genuine viral/raid hit looks identical; the score also decays with rise time (below) |
| `plateau_lock` | 0.16 | after a jump the series holds within ±0.5 % of one value for ≥ 20 consecutive minutes | A stream with a frozen upstream viewer counter; a channel running a static loop |
| `repeat_shape` | 0.14 | two of the channel's own recent streams have near-identical min-max normalised curves (r ≥ 0.995 or max abs delta ≤ 0.02) | The same streamer running the same scheduled format with a consistent warm-up |
| `staircase_return` | 0.06 | viewers collapse to ≤ 1 % of the pre-collapse median within one minute of stream end | A Twitch counter reset, a moderation mass-ban, or a platform glitch |

**Rise speed is the discriminator, not amplitude.** Measured: xqc ramped
918 → 28056 viewers (×30) over **114 minutes** organically. `rise_speed()` maps
rise time to a multiplier: 1.0 at ≤ 300 s, decaying to a floor of 0.15 at
≥ 1800 s. The organic ramp therefore scores 0.15 and cannot drive a verdict,
while the same amplitude inside 60 s scores ≈ 0.80. Locked in by
`tests/test_detect_regressions.py::RiseSpeedTests`.

#### Chat — `app/detect/chat.py`

| Code | Weight | Fires when | Known false positives |
|---|---|---|---|
| `silent_chat` | 0.16 | viewers ≥ 50 and the chatter count does not move for ≥ 10 min | A quiet stream, subscriber-only mode, slow moderation |
| `chat_starvation_ratio` | 0.12 | median `chatters/viewers` is below a viewer-aware floor | **Always** on large channels; the floor is an estimate curve, see below |
| `chat_collapse` | 0.10 | the ratio fell ≥ 50 % vs the window's own earlier median while viewers rose | Live chat leaving for any reason while the audience stays |
| `message_rate` | 0.10 | the chatter count barely moves while viewers are high (**frozen**), or it swings minute to minute with no matching viewer movement (**erratic**) | Moderation, a quiet stream, a stalled poller; see the calibration note below |
| `single_chatter_dominance` | 0.08 | one account writes ≥ 80 % of ≥ 10 readable messages | One dominant chatter is normal; a small message sample makes it likely |
| `passive_viewer_caveat` | 0.0 | always emitted alongside any chat finding | none (neutral disclaimer) |

The floor is **never a global constant**: below 50 viewers the ratio is
meaningless, and above it the floor rises monotonically,
`floor(v) = 0.02 + 0.07 · (1 − 50/v)`, asymptoting at 0.09. It keeps the
reference rows consistent — 300/30 (0.10) stays above `floor(300) = 0.078`,
500/1 (0.002) is far below `floor(500) = 0.083`. The floor is exposed in
`observed` so the UI can display it. A per-genre multiplier hook exists but is
**off by default**: no genre baseline has been measured for this repo.

`message_rate` is a **proxy, never counted messages**. The anonymous Twitch
client rejects every chat-message field, so the production adapter passes no
`chat_events` and the detector measures the per-minute change of the reported
chatter count instead — how fast the population of people in chat turns over.
`observed['source']` says which of the two produced the number
(`chatters_proxy` today, `chat_events` once a real source is wired in, where
the counted rate *replaces* the proxy rather than sitting beside it). The UI
labels it a proxy for the same reason.

**The thresholds are calibrated on the live DB, not guessed.** Measuring all
20 channels with data in `data/tvb.db` showed the naive rules are useless:
stale-minute share sits at **0.47–0.65 for every channel, honest ones
included**, and the median |Δ| is 0 nearly everywhere — that is the poller's
change-aware dedup, not a dead chat. A threshold anywhere near those numbers
would fire on all 20 channels. So the detector uses two signals that actually
separate: a chatter count that does not move **at all** (share ≥ 0.80, well
above the measured 0.65 ceiling), and movement unaccompanied by any viewer
movement (`UNPAIRED_CHAT_MOVE` 2 % of the chatter median against
`UNPAIRED_VIEWER_MOVE` 0.5 % of the viewer median, ≥ 50 % of minutes). On the
live DB: **0 of 20 channels fire**. Keep it that way when re-tuning.

#### Accounts — `app/detect/accounts.py`

Operates on the CommunityTab sample enriched through `users(logins:)`. This is
the highest-value family, and the only one the anonymous client fully supports.

| Code | Weight | Fires when | Known false positives |
|---|---|---|---|
| `fresh_account_cluster` | 0.18 | ≥ 12 % of the sample has account age ≤ 30 days | A channel that grows a genuinely young, international audience; a launch/giveaway |
| `clustered_creation_dates` | 0.16 | ≥ 3 sampled accounts share one `createdAt` day | A single popular streamer who recruits viewers daily |
| `zero_follower_cluster` | 0.05 | ≥ 40 % of the sample has `followers == 0` | **Very weak alone.** Measured: tumblurr 87 %, xqc 71 % — an ordinary channel is often higher than a farm, which is why the weight is 0.05 |
| `follower_burst` | 0.08 | channel `followers` rose ≥ 3× within one `stream_id` | A legitimate award, a big raid, or a follow-bot cleanup |
| `follow_without_viewing` | 0.10 | followers grew ≥ 3× while the stream's median viewers moved < 10 % | Follows ≠ views is true of every channel; a strong subscriber funnel without viewers looks the same |

Measured baselines used to set these thresholds: tumblurr 2 % fresh accounts,
xqc 0 %; 5 of 100 sampled xqc logins came back with no `createdAt` at all.

#### Shapes — `app/detect/shapes.py`

| Code | Weight | Fires when | Known false positives |
|---|---|---|---|
| `flatline` | 0.14 | < 1 % of minutes in a ≥ 30 min window have a zero delta, viewers ≥ 20 | Computed on the **expanded** series; a genuinely frozen upstream counter |
| `suspicious_smoothness` | 0.10 | ~0 second differences below the noise floor, i.e. piecewise-linear, compared against the channel's own earlier streams | Short or early streams with no history to compare against |
| `low_entropy` | 0.08 | normalised Shannon entropy of viewers rounded to the nearest 10 is < 0.25 across ≥ 5 buckets | Very stable channels (music, speedrunning, static content) are genuinely low-entropy |
| `time_of_day_independence` | 0.06 | hourly means uncorrelated (r ≤ 0.2) with the channel's other streams, needs ≥ 3 shared hours | A 24/7 channel legitimately has no diurnal curve; needs ≥ 2 streams |
| `instant_restore` | 0.06 | after a stream ends and restarts, viewers return within 2 % of the previous level | Twitch's own counter continuity, or a scheduled multi-part stream |

#### Causes — `app/detect/causes.py` (ad vs non-ad, weight 0.08)

**Ad breaks cannot be read anonymously** — `User.adBreak`, `adSchedule`,
`isAdBreak`, `liveBroadcastSettings` and `Channel.chatSettings` are all rejected
for this client-id, and one rejected field kills the entire batched request. The
comparison is therefore built from *observable proxies*, and the report says so:

1. **Viewer cliff and rebound** — a single-interval drop of ≥ 12 % of the running
   median, rebounding to ≥ 90 % within 10 min.
2. **Chatter-count dip** — chatters drop with viewers but the ratio stays flat.
3. **Title or game change** — an explicit external event, diffed per sample.
4. **Raid-ish influx** — a 10–30 min rise with a simultaneous follower jump.

`compare_ad_vs_nonad()` splits the timeline at the estimated break times and
compares viewer growth, chat ratio and follower delta inside the ad windows
against the rest. If no break is detected it reports `available: false`
explicitly rather than returning 0.

### Score, confidence and unavailable metrics

- `risk_score` = weighted mean of fired findings × 100. Verdict thresholds:
  < 30 green, 30–60 yellow, > 60 red, `null` → `nd`.
- `confidence` = coverage of data, never strength of signal:
  `(0.65 · data_factor + 0.35 · sample_factor) · available_ratio` over the
  seven metrics `series, chat, roster, intel, causes, shapes, chat_events`.
- **A metric that could not be measured lowers confidence and is listed in
  `unavailable[]`. It must never score 0.0 as if it had passed.**
  `single_chatter_dominance` is the live example: the anonymous client cannot
  read chat messages, so it stays `unavailable` and does not appear as a
  passing factor. Locked in by
  `tests/test_detect_score.py::UnavailableMetricTests`.

### Sampling honesty

The CommunityTab `viewers` list is a **randomised alphabetical slice of at most
100 logins** — measured at 0 % overlap between two polls 20 s apart. It is
never the population. `count` is the total; `len(roster)` is the sample, and the
two are never conflated. Roster polling therefore runs on a slower cadence
(`CHATTER_ROSTER_EVERY`, default every 10th poll) and account enrichment is
cached for `CHATTER_ENRICH_HOURS` (default 6 h).

No confirmed calibration corpus exists for the detection index. The index
describes unusual behaviour, not the probability that a channel is fraudulent.

## Upstream risk

The first adapter uses an undocumented Twitch GraphQL endpoint. Probe scripts
must be rerun when fields disappear or responses change. The adapter boundary
is designed so a future official Helix implementation can replace it without
changing the UI or API contract.
