# Detection spec — calibration addendum (research + local measurements)

Companion to `DETECTION_SPEC.md`. Use it to set thresholds and to document
false-positive modes. Sources were checked 2026-09-28.

## A. Measured baselines from the LIVE local database (`data/tvb.db`)

These are real numbers from this machine. Cite them in the report so the user
knows the thresholds are not invented.

| Measurement | Value | Consequence |
|---|---|---|
| Consecutive-sample identical pairs | **59–63 %** across tumblurr / xqc / agent00 | Raw samples are useless for flatness/volatility. Always `expand_series()` first. |
| Live samples per channel | 33 (tumblurr) … 221 (agent00) over 4 days | Real coverage is thin; `confidence` must reflect it honestly. |
| Drops >15 % of median in one step | xqc 8, agent00 10, tumblurr 0 | Gives a natural scale for the "cliff" size used in ad-break inference. |
| Chatter share ≤30-day-old accounts (n=100 sampled) | tumblurr **2 %**, xqc **0 %** | Baseline for `fresh_account_cluster`. A 12 % threshold is ~6× the local baseline. |
| Chatter share with 0 followers (n=100) | tumblurr **87 %**, xqc **71 %** | ZERO FOLLOWERS IS NORMAL ON LARGE CHANNELS. This signal is nearly useless alone — it must carry a very low weight, or be dropped. |
| CommunityTab roster stability | **0 % overlap** between two polls 20 s apart (n=100) | The roster is a randomised alphabetical slice. Sample statistics only. Never treat as a population or as "active chatters". |

## B. Published reference values (Vodra, Jan–Aug 2025, n=52 314 streams)

Quantified, useful for calibrating ratio detectors. Cite as external context,
not as a claim about any specific channel.

| Signal | Organic | Suspect/botted |
|---|---|---|
| Chatter : CCV | 1:6 | 1:18 (flags near ≥1:15–1:20) |
| Extreme case documented by Streams Charts | — | 1:500 |
| CCV–follower growth correlation | r = 0.78 | r = 0.29 |
| Bot prevalence, Twitch | — | 39.6 % mean (95 % CI 34.9–44.3) |
| Bot prevalence, Kick | — | 68.7 % (the same vendor, different platform) |
| Synchronised surges with no raid | — | 500–1 000 CCV |

Useful derived observation: bot ratio is roughly **scale-invariant** (the same
bot share shows up at 300 and at 30 000 CCV), so a **fixed ratio threshold is
wrong** — a ratio must be compared against the channel's OWN history. This
directly contradicts a naive "chatters/viewers < 5 % ⇒ bots" rule and matches
the repo's existing `AGENTS.md` note that a 1 000-viewer stream with a known
guest is not suspicious by itself.

Other anchors worth encoding:
- **Tier artefacts**: organic-looking plateaus cluster at 200–300 and 1 200–1 400
  CCV, because viewbot services sell packages at round numbers. A `plateau_lock`
  that sits at a suspiciously round tier value is stronger evidence than one at
  an arbitrary number.
- **Intrastream variance**: a real stream's CCV swings roughly ±15–30 %;
  a bot-supported stream is often inside ±3 %. Use a coefficient-of-variation
  detector, not an absolute range.
- **avg vs peak**: if average and peak viewers are within 5 % across many
  streams, that is a bot signature (real streams usually show a 30–50 % gap).
  This is a cheap cross-stream check the local data CAN support once more
  streams accumulate.
- **Follower : CCV**: 1 200:1 is treated as a sponsor/brand-deal red flag.
  Directly implementable from `followers.totalCount` + median viewers.

## C. Threshold guidance

- Use SHARES and COEFFICIENTS OF VARIATION, not raw counts, wherever the
  absolute scale varies by 100× across the tracked portfolio.
- `fresh_account_cluster` ≥ 12 % of the sampled roster (≈6× the local baseline).
- `plateau_lock` CV threshold ≈ 0.03 (3 %) over ≥20 expanded minutes.
- `intrastream_variance` normal band 15–30 %; suspicious < 5 %.
- Ratio floors must be **monotone in viewer count** and must return `None`
  (not 0.0) below ~50 viewers, where the ratio carries no information.
- Every threshold that comes from this document must be a named, overridable
  constant in one place — not a magic number scattered through the detectors.

## D. Documented false-positive modes (surface these in the UI)

Ranked by how often they will actually fire:

1. **Raid** — a real, unattributable-looking spike. Twitch's own docs say a raid
   is a single spike from a known source; the anonymous client cannot see the
   source, so a raid is indistinguishable from an unexplained jump. Must be
   named in the report whenever `no_justification` fires.
2. **Co-stream / Shared Viewership** — officially combines viewer counts across
   collaborating channels, so per-channel numbers look anomalous by design.
3. **Viral clip / front-page feature** — real spike, no raid, no follower bump.
4. **Quiet category** — speedruns, watch parties, focus streams have a very low
   chatter ratio with zero botting. Comparing against the channel's own other
   streams (not a global constant) is the only defence.
5. **Lurker-heavy / mobile / TV-second-screen audiences** — legitimately low
   chat participation. This is why `chat_starvation_ratio` is a weight-carrying
   signal, never a verdict.
6. **Viewers with no Twitch account** — invisible to `users(logins:)` entirely,
   so account-age enrichment measures the *authorised* population only. The gap
   between `viewersCount` and `chatters.count` is largely these guests.
7. **Follower ≠ viewer** — a follow can happen with zero viewing. This is the
   user's own point in idea #6; the `follow_without_viewing` detector exists
   specifically to catch the decoupling.
8. **Delayed counter updates** — Twitch samples counters periodically. A
   sub-minute spike may never be real. Never score a single-sample spike above
   a small score; require persistence across ≥2 expanded minutes.
