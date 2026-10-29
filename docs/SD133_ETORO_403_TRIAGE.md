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
`SINGLE_DEMO_PAIR_OWNER_ACCEPTED`. **Already-demonstrated Demo trading
access:** on 2026-10-26 the owner-authorised MSFT pilot sent
`POST /api/v2/trading/execution/demo/orders` and received HTTP 200 acceptance
with echoed reference/order linkage. The owner observed a new MSFT Demo
position of 0.09 units. The immediate automated lookup returned HTTP 404,
triggering SideDeck's kill switch. The owner subsequently closed that position
manually; on 2026-10-27 a separately owner-authorised read-only Demo `/pnl`
GET returned HTTP 200 / MATCHED, with all four protected baseline positions,
zero remaining MSFT pilot position and no pending order. **The pilot verified
the trading endpoint could accept a Demo order**, not a completed autonomous
open-to-close workflow or a permanent guarantee across all API endpoints.

## Findings

- HTTP 403 was returned by the documented AAPL search URL
  `GET https://public-api.etoro.com/api/v1/market-data/search?internalSymbolFull=AAPL`.
  This is an external authorization/access failure for **that endpoint**, not a
  general diagnosis of all Demo APIs, nor a reason to discount the successful
  Demo order acceptance and portfolio-read reconciliation.
- eToro's published authentication guidance distinguishes 401 authentication
  failures from 403 permission failures. The owner reconfirmed on 2026-10-27
  that the existing key is **Demo**, has **Read and Write** permissions and
  **expiration not defined**. Do not ask for those same confirmations again.
- The collector intentionally did not record the response body/headers. It
  therefore cannot distinguish endpoint scope from Cloudflare/WAF or another
  upstream 403. Past supervised Demo write acceptance remains independently
  demonstrated; autonomous trading remains unreleased.
- One diagnostic network GET consumed exactly one request. No trades,
  portfolio/order reads, additional eToro requests, retries, account access
  changes, key rotations or credential uploads were made by engineering.

## Outstanding eToro provider question (no API request)

The owner has **already confirmed** Demo, Read/Write and no defined expiry;
yesterday's supervised Demo order was accepted. **Do not demand new keys
or repeat that permission audit.** The remaining provider-specific question is
why the otherwise documented market-data AAPL search route returned HTTP 403.

Ask eToro API support about this specific search endpoint and the dated 403
if necessary. Do not transmit keys, account identifiers, signable artifacts or
unredacted response details. Check an IP whitelist only if support has specific
evidence it is relevant; never disable security controls indiscriminately.

Do not replay either consumed AAPL authorization or broaden authenticated
requests merely to test whether the provider denial persists.

## Engineering path independent of external permission

Continue offline SD-107/108/129 production Demo transport review against
SD-063/064/074 controls, replay/fill/reconciliation and protected baseline.
eToro Demo is **not released**. If eToro market data remains unavailable,
investigate a licensed independent full-session five-minute market-data
feed as a separately scoped project: an external feed does not authorize
future Demo writes or replace a separately signed owner trading release.

Before Demo automation: genuine historical/current intraday feed; OOS DAY
strategy admission; owner-approved production Demo route; remote audit anchors;
protective-close evidence, monitoring, independent review, and bounded owner
release. The original four Demo holdings must remain protected.

Official reference:
- https://api-portal.etoro.com/guides/get-instrument-id
- https://api-portal.etoro.com/getting-started/authentication
- https://builders.etoro.com/learn/authentication-and-api-keys
