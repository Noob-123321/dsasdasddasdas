# Captured live Twitch responses (ground truth for parser tests)

Captured 2026-09-28 against `gql.twitch.tv` with the anonymous public
Client-Id, channel `xqc`. Use these EXACT shapes in
`tests/test_twitch_intel_parsing.py` — they are trimmed copies of real
responses, not hand-written guesses. Anything that parses these correctly
will parse production.

## 1. `POLL_QUERY` response (`parse_poll_payload`)

```json
[
  {
    "data": {
      "user": {
        "id": "71092938",
        "login": "xqc",
        "displayName": "xQc",
        "createdAt": "2014-09-12T23:50:05.989719Z",
        "followers": { "totalCount": 12569876 },
        "lastBroadcast": { "startedAt": "2026-09-27T19:47:19.897021Z" },
        "stream": {
          "id": "320551363424",
          "type": "live",
          "title": "🤖LIVE🤖DRAMA🤖NEWS🤖GTA V🤖NOPIXEL V🤖 5+5 = 10🤖BIG DAY TODAY🤖BIG IMPORTANT🤖HUGE🤖DONT MISS🤖JP RUNNING THE STREETS🤖GRINDFATHER IS BACK",
          "viewersCount": 39648,
          "createdAt": "2026-09-27T19:47:14Z",
          "isMature": false,
          "game": { "id": "32982", "name": "Grand Theft Auto V" },
          "freeformTags": [
            { "name": "English" },
            { "name": "femboy" },
            { "name": "DropsEnabled" }
          ]
        }
      }
    },
    "extensions": {
      "durationMilliseconds": 65,
      "requestID": "01M3JGMPC7DSRBVSZ4FPZG3KTA",
      "operationName": "StreamInfo"
    }
  }
]
```

Contract to assert:
- `viewer_count == 39648`
- `followers_count == 12569876`
- `channel_created_at` parses to 2014-09-12 23:50:05 (tz-aware)
- `last_broadcast_at` parses to 2026-09-27 19:47:19
- `stream_created_at` parses to 2026-09-27 19:47:14
- `game == "Grand Theft Auto V"`, `is_live is True`, `is_mature is False`
- `freeform_tags == ["English", "femboy", "DropsEnabled"]`
- The `title` contains emoji and `🤖`; it must survive parsing unchanged
  (UTF-8 round trip). Do not strip it.

Offline case: `"stream": null` with `user` still present must yield
`is_live False` and `viewer_count None`, NOT an exception.

## 2. CommunityTab `chatters` object (`parse_roster`)

```json
{
  "count": 29150,
  "viewers": ["1flaherty", "1skully1", "ahizz1", "akhortech", "albaricss", "areski__"],
  "moderators": ["creat1vely", "fossabot", "m0xyy", "mendo"],
  "chatbots": ["fossabot", "streamelements"],
  "vips": ["arthium", "contravz", "cristianoooronaldooo"],
  "broadcasters": ["xqc"]
}
```

Contract to assert:
- `count == 29150` is the TOTAL population; `len(roster)` is the 100-sample.
  They must never be conflated — this is the trap in `DETECTION_SPEC.md` §1.
- Logins come as `{"login": "...", "__typename": "Chatter"}` objects, not
  strings. Assert the parser unwraps `.login` and lowercases it.
- `"areski__"` has a trailing double underscore: underscores and digits are
  legitimate in Twitch logins. Do not filter them.
- `staff` is absent in this capture — the parser must tolerate a missing key.

## 3. `USERS_QUERY` response (`parse_accounts`)

Real enrichment run over 100 sampled chatters of `xqc` returned 95 with a
usable `createdAt`. Aggregates measured on that sample:

| Metric | Value |
|---|---|
| accounts with `createdAt` | 95 of 100 |
| age ≤ 30 days | 0 (0.0 %) |
| age ≤ 90 days | 0 (0.0 %) |
| `followers_count == 0` | 17 (17.9 %) |
| youngest account | 397 days |

Five youngest, as `(age_days, followers_count)`:

```json
[[397, 174], [704, 83], [843, 0], [893, 0], [1360, 0]]
```

One real row, verbatim field names as the parser returns them:

```json
{
  "login": "130h_",
  "account_id": "825281278",
  "twitch_created_at": "2022-09-14T12:59:26.107271+00:00",
  "followers_count": 894,
  "last_broadcast_at": "2026-08-12T00:12:19.491441+00:00"
}
```

Contract to assert: the parser returns `login`, `account_id`,
`twitch_created_at`, `followers_count`, `last_broadcast_at`. Note there is
**no** `age_days` key — age is derived by the caller against "now". A test
that looks for `age_days` in the parser output is wrong.

## 4. Fields that MUST be rejected

`adBreak`, `adSchedule`, `isAdBreak`, `liveBroadcastSettings`, `chatSettings`,
`prerenderedViewersCount`, `peakViewersCount`, `videoAds`, `preRollAds`,
`Channel.roles`, `Stream.startedAt`, `Tag.name`.

Real error text from the live API, for the regression fixture:

```json
{"errors": [{"message": "Cannot query field \"prerenderedViewersCount\" on type \"Stream\".",
             "path": ["query", "user", "stream"]}]}
```

One of these kills the entire batched request. Add a test that a payload
containing any of them is rejected before it is sent, or at minimum a test
that the module never emits them.
