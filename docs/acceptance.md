# Release acceptance checklist

## User journey

- [ ] Landing accepts a `TVS_` + 128-character key.
- [ ] Invalid, expired and revoked keys do not reveal profile details.
- [ ] Valid key creates an HttpOnly session and opens an empty portfolio.
- [ ] Add modal accepts multiple whitespace-separated Twitch links.
- [ ] Invalid/duplicate/restricted links have explicit partial-success states.
- [ ] Portfolio shows live, authorized, guests, ratio, score and freshness.
- [ ] Channel detail shows history, anomalies and score explanation.
- [ ] CSV and HTML/PDF report endpoints return a period and digest.
- [ ] Child `tvs_` key can read parent data and cannot read foreign channels.
- [ ] Revoking/expiring parent invalidates child keys.

## Admin journey

- [ ] Bootstrap/admin token is created and stored securely.
- [ ] Admin can create profile and admin TVS keys.
- [ ] Expiry and allowlist/unlimited policy can be edited after creation.
- [ ] Reveal/copy and revoke actions appear in audit history.
- [ ] Load page shows user/session activity, request totals, p50/p95, errors,
  active channels, API keys and poller state.

## Reliability and security

- [ ] Poller isolates one channel error and survives Twitch timeout.
- [ ] Unchanged viewer/chat observations deduplicate correctly.
- [ ] Stream shutdown does not fake a Twitch offline transition.
- [ ] No full secret appears in URL, Referer, logs, localStorage or audit.
- [ ] Webhook URLs reject private IPs and use signed payloads.
- [ ] `python -m compileall -q app src tests` passes.
- [ ] `node --check public/app.js` passes.
- [ ] `python -m unittest discover -s tests -v` passes.
