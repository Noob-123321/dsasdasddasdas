# TVS Analytics API

The interactive contract is generated at `/docs`, `/redoc` and
`/openapi.json`.

## Authentication

Browser sessions use an HttpOnly cookie obtained from:

```http
POST /api/auth/redeem
Content-Type: application/json

{"token":"TVS_..."}
```

Machine integrations use a child key:

```http
Authorization: Bearer tvs_...
```

A child key inherits the parent profile's channel scope and is invalid when
its parent is expired or revoked. Keep secrets out of URLs, query strings,
Referer headers and browser storage.

## Response envelope

Success:

```json
{
  "ok": true,
  "data": {},
  "meta": {"request_id": "req_..."}
}
```

Error:

```json
{
  "ok": false,
  "error": {"code": "channel_not_found", "message": "Канал не найден"},
  "meta": {"request_id": "req_..."}
}
```

## Endpoints

- `GET /api/v1/channels/{login}/snapshot`
- `GET /api/v1/channels/{login}/history?hours=24`
- `GET /api/v1/channels/{login}/anomalies`
- `GET /api/v1/channels/{login}/summary`
- `GET /api/v1/portfolio`
- `POST /api/v1/batch/snapshots` with up to 50 logins

The v1 implementation is read-only. Profile UI routes are intentionally
separate from the machine API so an API key cannot silently change a profile.

## Detection routes

The bot / view-farm detection layer (design: `docs/DETECTION_SPEC.md`,
method: `docs/methodology.md`) adds four read-only routes — the machine API and
the profile twin of each:

- `GET /api/v1/channels/{login}/detection?hours=168`
- `GET /api/v1/channels/{login}/chatters`
- `GET /api/profile/channels/{login}/detection?hours=168`
- `GET /api/profile/channels/{login}/chatters`

Both twins return the same payload and the same authorisation rules as the rest
of their group; a channel outside the principal's scope is `404 channel_not_found`.
`hours` accepts 1..8760 and defaults to 168 (7 days).

### Detection report

```json
{
  "channel": "xqc",
  "title": "🤖LIVE🤖DRAMA…",
  "game": "Grand Theft Auto V",
  "is_live": true,
  "generated_at": "2026-09-28T12:00:00Z",
  "window_hours": 168.0,
  "risk_score": 49.0,
  "confidence": 0.429,
  "verdict": "yellow",
  "factors": [
    {
      "code": "no_justification",
      "score": 0.83,
      "weight": 0.22,
      "observed": {
        "amplitude": 1084.0,
        "baseline_viewers": 13.0,
        "peak_viewers": 14092,
        "peak_ts": "2026-09-26T20:02:00",
        "rise_seconds": 600,
        "is_instant": false,
        "sudden": false,
        "hints": []
      },
      "note": "онлайн вырос в 1084.00 раза … за 600 с",
      "note_code": "note_no_justification",
      "note_args": {"amplitude": 1084.0, "rise_seconds": 600},
      "explanation": "Ни смена названия или категории, ни скачок фолловеров, ни рейд не совпали с окном скачка."
    }
  ],
  "warnings": [
    "оценка описывает необычность поведения, а не вероятность ботов.",
    "roster: выборка чаттеров ещё не собрана",
    "chat_events: анонимный клиент не читает сообщения чата"
  ],
  "warning_codes": [
    {"code": "detect_not_probability", "args": {}},
    {"code": "unavailable_roster", "args": {"detail": "выборка чаттеров ещё не собрана"}}
  ],
  "unavailable": [
    {"metric": "roster", "code": "unavailable_roster", "detail": "выборка чаттеров ещё не собрана"},
    {"metric": "chat_events", "code": "unavailable_chat_events", "detail": "анонимный клиент не читает сообщения чата"}
  ],
  "confidence_parts": {
    "data_factor": 1.0,
    "sample_factor": 1.0,
    "available_ratio": 0.429,
    "metrics_present": ["series", "chat", "shapes"],
    "metrics_missing": ["roster", "intel", "causes", "chat_events"]
  },
  "series": {
    "expanded_points": 5691,
    "live_points": 384,
    "gap_points": 5307,
    "samples_used": 194,
    "observed_minutes": 384.0,
    "from": "2026-09-23T21:44:00Z",
    "to": "2026-09-27T20:34:00Z",
    "minute_seconds": 60
  },
  "points": [
    {"ts": "2026-09-23T21:44:00Z", "total": 13, "chatters": 4}
  ],
  "ad_vs_nonad": {
    "available": true,
    "reason": "",
    "verdict": "inconclusive",
    "growth_ratio": null,
    "ad_window": {"minutes": 125, "viewer_growth_ratio": 0.7989, "chat_ratio_median": 0.9729, "followers_per_hour": null, "points": 122},
    "rest_window": {"minutes": 5566, "viewer_growth_ratio": 0.0, "chat_ratio_median": 0.9378, "followers_per_hour": null, "points": 262},
    "breaks": [{"ts": "2026-09-25T20:06:00", "kind": "viewer_cliff", "confidence": 0.8404}],
    "note": "Прокси-сравнение реклама/не-реклама: …"
  },
  "explanation": "Детекция сопоставляет формы кривой, поведение чата и выборку аккаунтов с собственными наблюдениями канала.",
  "explanation_code": "detect_explain"
}
```

Field contract:

- `risk_score` — 0..100 weighted mean of the fired factors, or `null` when there
  are no live observations. `verdict` is `green` (< 30), `yellow` (30–60),
  `red` (> 60) or `nd`.
- `confidence` — data coverage, **not** signal strength. A metric the client
  cannot read is listed in `unavailable[]` and lowers `confidence`; it never
  scores 0.0 as though it had passed.
- `factors[]` — the fired signals verbatim. Each carries `code`, `score` (0..1),
  `weight`, the `observed` numbers that produced it, and a Russian `note` with a
  language-neutral `note_code`/`note_args` pair, as does `warnings[]` via
  `warning_codes[]`.
- `points[]` — the expanded per-minute timeline. `total`/`chatters` are `null`
  inside a real gap; the UI must not interpolate across one.
- `ad_vs_nonad` — an **inferential** comparison. Ad breaks are not readable
  anonymously, so it is built from observable proxies (viewer cliff + rebound,
  chatter dip, title/game change, raid-ish influx) and says so in `note`. When no
  break is detected, `available` is `false` with a `reason` instead of zeros.

`risk_score` describes how unusual the observed behaviour is. It is not the
probability that a channel is fraudulent, and the UI never calls viewers bots.

### Chatter roster

```json
{
  "channel": "xqc",
  "sample": {
    "observed_at": "2026-09-28T10:00:00Z",
    "stream_id": "320551363424",
    "count": 29150,
    "sampled": 100,
    "roles": {"moderators": ["fossabot"], "vips": ["arthium"]},
    "roster": ["1flaherty", "areski__"],
    "enriched_at": "2026-09-28T10:00:00Z"
  },
  "accounts": [
    {
      "login": "130h_",
      "account_id": "825281278",
      "created_at": "2022-09-14T12:59:26Z",
      "account_age_days": 378,
      "followers": 894,
      "last_broadcast_at": "2026-08-12T00:12:19Z",
      "enriched_at": "2026-09-28T10:00:00Z",
      "source": "gql"
    }
  ],
  "enrichment": {
    "sample_size": 100,
    "enriched": 95,
    "oldest_enriched_at": "2026-09-28T10:00:00Z",
    "newest_enriched_at": "2026-09-28T10:00:00Z",
    "missing": []
  },
  "note": "CommunityTab отдаёт случайную алфавитную выборку логинов, а не полный список чаттеров."
}
```

`count` is the reported total and `sampled`/`len(roster)` is the slice — the two
are never conflated. The roster is a **randomised alphabetical slice of at most
100 logins** (measured: 0 % overlap between two polls 20 s apart), so it supports
distribution statistics such as account age and follower counts, never
per-individual tracking. `sample` is `null` when no snapshot has been collected
yet. `enrichment.enriched` counts the accounts the `users(logins:)` batch
actually returned; on a real run 95 of 100 came back with a usable `createdAt`.

## Score payload

```json
{
  "risk_score": 63.0,
  "verdict": "red",
  "confidence": 0.42,
  "factors": [
    {
      "code": "low_ratio",
      "value": 0.014,
      "score": 0.86,
      "weight": 0.4,
      "note_code": "note_low_ratio",
      "note_args": {"ratio": "1.4%"},
      "note": "медиана доли чаттеров 1.4%"
    }
  ],
  "warning_codes": [{"code": "warn_low_confidence"}],
  "warnings": ["данных мало, оценка предварительная"],
  "explanation": "Индекс описывает необычность наблюдаемого поведения, ..."
}
```

This is an explainable observation score, not a probability that a channel is
fraudulent. A caller should make the final decision.

`note` and `warnings` are Russian text. Every generated string also carries a
language-neutral `note_code`/`warning_codes` entry with the arguments needed to
render it in another language; `webhooks` and the browser UI do exactly that.
Cached snapshots written before those fields existed return `null` for
`warning_codes`, which means the text is not translatable for that record.

## Limits and operations

Rate-limit and quota headers are added as the production limiter is enabled.
Operational endpoints are `/healthz`, `/health`, `/readyz` and `/metrics`.
