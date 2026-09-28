# UI polish + messages-per-minute detector (phase 3)

User-reported issues with screenshots, plus one new detector. Five items, all
independent. The repo is working; 246 tests pass. Fix these without breaking
anything.

## Item 1 — duplicated time in the history header

`public/app.js`, `detailHtml()` (line ~1325). The panel-head `<small>` renders:

```
24 часа · последние сохранённые наблюдения
```

and the chart below it (`chartPanel`, ~line 1495) renders its own subtitle
`последние сохранённые наблюдения` again. The user sees the same wording twice
in one card, and the date range `27.09.2026, 19:11 → 28.09.2026, 02:05` sits
under a label that already claims "last observations".

Fix: keep the range selector (`24 часа` / `7 дней` / `30 дней`) and the
explanatory sentence, but make the small caption state the ACTUAL data range
and remove the duplicated phrase. The card should read, in effect:
`24 часа · 27.09.2026, 19:11 → 28.09.2026, 02:05`. Derive the range from
`state.history` (first and last timestamps). If the history is empty, omit the
range rather than printing "нет данных". Apply the same fix to the detection
chart caption at ~line 1495 if it repeats the same words.

## Item 2 — untranslated text

The screenshot of "Недоступные метрики" shows raw metric codes as headings:
`roster`, `chat_events`. Those are internal identifiers and must never reach
the UI. They are rendered in `app/detect/pipeline.py` via
`detection_unavailable` markup in `public/app.js` (~line 1496):
`<strong>${esc(item.metric)}</strong>`.

Add i18n keys for every metric name the pipeline can emit
(`series`, `chat`, `roster`, `intel`, `causes`, `shapes`, `chat_events`, and any
`missing_table_*` code), in BOTH `I18N.ru` and `I18N.en`, and render
`t('metric_' + key, humanFallback)` instead of the raw code. The Russian
fallback must be a human phrase, e.g. `roster` → «Выборка чаттеров»,
`chat_events` → «Сообщения чата». Keep `esc()` on the result. Verify symmetry
with the repo's own check from AGENTS.md (ru and en must hold the same keys).

While you are there: check the whole detection view for any other raw
identifier leaking into the UI and translate it the same way.

## Item 3 — small grey text is too small

User asks to increase it by 1–2px. Bump these in `public/styles.css`:
- `.panel-head small` — currently `font: 10px var(--mono)` → **11px**
- `.list-row small` — currently `font: 10px var(--mono)` → **11px**
- `.helper` — currently `font-size: 11px` → **12px**
- `.head-note` — currently `font: 11px var(--mono)` → **12px**

Keep the colour variables as they are; only the size changes. Do not touch
unrelated rules. If any of these are used in a tight table where 12px would
wrap badly, say so in your report rather than silently reverting.

## Item 4 — TwitchTracker-style event markers (vertical bars)

The viewer chart should show WHEN things happened, not just the curve — this
is what twitchtracker.com's viewer-history graph is famous for.

Add an event layer to the chart in `public/app.js` (`chartSvg` and/or the
detection chart, plus the CSS in `public/styles.css`):
- A thin **vertical bar** spanning the plot height at each event timestamp.
- Events to support (render from the detection report / available data):
  - a detected **spike/jump** (`no_justification`, or any finding whose
    `observed.peak_ts` exists),
  - a **title or game change**,
  - a detected **ad-break proxy** (`viewer_cliff` from the ad comparison),
  - **stream start / stream end** (live transitions in the series).
- Colour-code them subtly (e.g. amber for ad proxy, red for spike, muted for
  stream boundary) and add a legend entry for each.
- Add a tooltip on hover for the bar showing what it is and the exact time.
- A title-change marker is the highest-value one: the user asked for it first
  and it is fully explainable ("смена названия 20:15").

Draw them BEHIND the series lines so the data stays readable. If there are more
than ~25 events in the window, thin them out and say so in the report rather
than rendering an unreadable picket fence.

Data source: the detection report already returns findings with
`observed.peak_ts` / `observed.start_ts` / `observed.end_ts`, and
`ad_comparison.breaks[]` carries estimated break times. Use those; do not
invent a new endpoint. If the event list is empty, render the chart exactly as
it is today.

## Item 5 — messages-per-minute metric, AND wire it into the score

This is a real detector, not a cosmetic change.

**Data reality first.** The anonymous Twitch GraphQL client CANNOT read chat
messages. Verify this yourself before designing around it
(`gql.twitch.tv` with the public client-id rejects any chat-message field; see
`docs/DETECTION_SPEC.md` §1 and the REJECTED list in
`docs/fixtures/live_twitch_responses.md`). So true "messages per minute" from
Twitch is NOT available anonymously.

What IS available and is the closest honest proxy: **chatters count change per
minute** — i.e. `Δ(chatters)` over the expanded per-minute series, which
measures how fast the population of people in chat is turning over. Implement
it that way and LABEL it honestly in the UI as a proxy, never as real messages.

Implementation:
1. New detector in `app/detect/chat.py` (follow the existing `Finding`
   pattern exactly): code `message_rate`, weight added to `WEIGHTS`.
   It reports, on the expanded series:
   - `messages_per_minute` — the median absolute per-minute change in the
     chatter count,
   - `chatter_turnover` — sum of positive per-minute changes (people joining
     chat) and negative ones separately,
   - `stale_minutes` — minutes where the chatter count did not move at all.
2. A bot/inauthenticity signal inside it: when viewers are high but the chatter
   count is **frozen or barely moving**, that is evidence of passive/fake
   viewers. When it moves *erratically* (large swings minute to minute with no
   corresponding viewer movement) that is also suspicious. Score on the
   combination, and expose the numbers in `observed`.
3. Add it to the report and to the factor list. Because the underlying input is
   a proxy, the finding must state that in its `explanation`.
4. Surface it in the UI: a KPI/row in the detection view showing
   `messages_per_minute` and `stale_minutes`, plus a factor row like the others.
   Add all new i18n keys to ru AND en.
5. If a real chat-message source is ever wired in later, the detector should
   accept a `chat_events` input and prefer it over the proxy. Do not build
   that path now; just make sure the function signature does not preclude it.

Tests: extend `tests/test_detect_chat.py`. A frozen chatter count on a
high-viewer series must fire; a busy, naturally varying chat must not. Assert
the observed numbers, not just the verdict.

## Constraints

- Python 3.10, ruff line-length 120, lint `E,F,I`.
- No new third-party dependencies.
- `node --check public/app.js` is syntax-only. **After ANY edit to
  `public/app.js` or `public/styles.css`, verify in a real browser** and read
  the console — AGENTS.md explains why this is mandatory. A JS error renders a
  blank page, not a test failure. Headless Chrome over CDP is acceptable; the
  repo has a precedent for it.
- All UI strings go through `t('key', 'Русский fallback')`, and `I18N.ru` /
  `I18N.en` must contain every key.
- `app/detect/pipeline.py` / `score.py` must treat an unavailable metric as
  LOWERING confidence, never as a silent 0.0 pass.
- NEVER touch `data/tvb.db` or anything in `data/`. Test against copies in a
  scratch dir.

## Definition of done — run these and paste the real output

- `python -m pytest -q` green (must be > 246 tests; add the new ones)
- `python -m compileall -q app src tests tools` clean
- `ruff check app` clean
- `node --check public/app.js` clean
- `alembic check` clean against a scratch copy
- browser screenshot of the fixed history header, the translated
  "Недоступные метрики" block, and a chart WITH event bars
- ru/en i18n symmetry check from AGENTS.md
