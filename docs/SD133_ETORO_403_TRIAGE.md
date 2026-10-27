# SD-133 — eToro Demo market-data HTTP 403 triage (27 October 2026)

**Evidence:** The owner executed one newly signed, single-use SD-120 AAPL
search diagnostic from the `sidedeck-etoro-auto` worktree. Sanitized result:

```json
{"broker_execution":"DISABLED",
 "classification":"ACCESS_OR_ENTITLEMENT_DENIED",
 "requests_used":1,"status":403}
```

The separate, preceding signed AAPL diagnostic was consumed with a
`FAILED:URLError` ledger entry and no HTTP status. Neither authorization may
be reused. Subsequent owner-run uncredentialed DNS, TCP 443 and Python TLS 1.3
tests succeeded, with no Python proxy configured. SSH signature verification
passed. The local Demo credential configuration preflight returned
`SINGLE_DEMO_PAIR_OWNER_ACCEPTED`, but does **not** verify provider
entitlement.

## Findings

- HTTP 403 was returned by the documented AAPL search URL
  `GET https://public-api.etoro.com/api/v1/market-data/search?internalSymbolFull=AAPL`.
  This is an external authorization/access failure for **that endpoint**, not a
  general diagnosis of all Demo APIs.
- eToro's published authentication guidance distinguishes 401 authentication
  failures from 403 permission failures. eToro key settings include Demo vs
  Real environment, Read/Write permissions, expiry and optional IP whitelist.
- The collector intentionally did not record the response body/headers. It
  therefore cannot distinguish endpoint scope from Cloudflare/WAF or another
  upstream 403. No claims about verified Demo write privilege are justified.
- One diagnostic network GET consumed exactly one request. No trades,
  portfolio/order reads, additional eToro requests, retries, account access
  changes, key rotations or credential uploads were made by engineering.

## Owner action (no API request)

Inspect the **existing** key's metadata in eToro Settings -> Trading ->
API Key Management or api-portal.etoro.com:

1. Environment is Demo, not Real. Confirm the same credential pair is active.
2. Verify the appropriate Read and intended Demo Write permission (do not
   infer write from a separate market-data access error).
3. Check key expiry and any configured IP whitelist.
4. Check whether market-data search entitlement/terms require provider
   enablement; contact eToro API support if the portal settings are correct.
   Report endpoint, HTTP 403 and UTC diagnostic date without transmitting
   keys, signed files, or sensitive account data.

Do not disable an IP restriction indiscriminately or create multiple key pairs
to bypass the denial. Do not run another identical authenticated diagnostic
without new evidence and a separately signed narrow scope.

## Engineering path independent of external permission

Continue offline SD-107/108/129 production Demo transport review against
SD-063/064/074 controls, replay/fill/reconciliation and protected baseline.
eToro Demo is **not released**. If eToro market data remains unavailable,
investigate a licensed independent full-session five-minute market-data
feed as a separately scoped project: an external feed cannot substitute for
Demo **broker write** entitlement or the owner release.

Before Demo automation: genuine historical/current intraday feed; OOS DAY
strategy admission; owner-approved production Demo route; remote audit anchors;
protective-close evidence, monitoring, independent review, and bounded owner
release. The original four Demo holdings must remain protected.

Official reference:
- https://api-portal.etoro.com/guides/get-instrument-id
- https://api-portal.etoro.com/getting-started/authentication
- https://builders.etoro.com/learn/authentication-and-api-keys
