# SD-115 / SD-117 owner-reviewable eToro five-minute data proposal

## Status

Draft only. No request has been made, no provider has been paid, and no credential has been used.
The Day Trader module remains `RESEARCH_ONLY` and the broker remains disabled. eToro Demo is
the primary broker and the primary candidate market-data source; Alpaca intraday acquisition is
not proposed by this package.

## Exact eToro discovery package (not authorized)

This package is prepared for owner review only. It would consume at most **nine authenticated
GET requests**, with zero retries and no redirects:

1. Three exact instrument searches, one each for `SPY`, `QQQ`, and `MSFT`, using the existing
   v1 search contract and exact-symbol matching. An ambiguous or non-equity result stops the
   package; no ID is displayed or retained in chat.
2. Three coverage requests, one per verified instrument ID, to
   `/api/v1/data/instruments/{instrumentId}/candles/coverage`.
3. Three bounded sample requests, one per instrument, to `/api/v1/data/instruments/{instrumentId}/candles`
   with `interval=5m`, `side=both`, an owner-approved short UTC window and a local response
   ceiling of 2,000 rows.

The package must return only sanitized status, exact coverage ranges/counts, row counts,
response hashes and whether the three samples passed schema checks. It must not request account,
portfolio, rates, orders or trading endpoints. A failed request consumes its slot and stops the
package. The official documentation describes a shared quota of 120 requests per 60 seconds and
cursor pagination; SideDeck will not assume the pasted 2,000-page or five-year claims without a
real response.

Required owner sign-off: exact nine-request eToro Demo market-data-only scope, the UTC sample
window, permission to use the returned data for internal research, and confirmation that the
credential pair is entitled for these endpoints. This is separate from any Demo execution
release and does not authorize orders.

## Preferred path: owner-supplied licensed files

The lowest-risk path is a local package supplied by the owner with written reuse rights. Place it
under `data/day_trader/intraday/` only after review, accompanied by `manifest.json` containing:

- instruments exactly `SPY`, `QQQ`, `MSFT`;
- five-minute bars from `2021-10-26T00:00:00Z` through the final completed XNYS session before import;
- exchange-local timestamps or an unambiguous UTC conversion rule;
- OHLCV, completed-bar marker, source, retrieval time, corporate-action/adjustment basis and
  licensing statement;
- SHA-256 for every file and a manifest SHA-256; no credentials or account data.

The importer must reject missing intervals, duplicate/non-positive bars, future timestamps,
unexplained corporate actions, partial sessions and ambiguous adjustment basis. It must label the
result `OWNER_LICENSED_REAL_DATA` only after those checks and retain a point-in-time cutoff.

## Optional bounded provider retrieval (requires separate approval)

If eToro coverage is insufficient, the owner must separately approve an alternative provider,
license terms, credential variable names and exact endpoint contract. A future runner may then be
authorized for at most one bounded retrieval package covering only the three symbols, the stated
date window and five-minute bars, with a persistent reserve-before-send request budget, no
retries, no redirects, no other endpoints, no orders/account calls, and no provider spend beyond
the approved amount.
The runner must return only sanitized status, file hashes, coverage and license metadata. A failed
request consumes its budget and is not retried automatically.

No authenticated request is authorized by this draft. A new owner authorization must name the
eToro endpoints, exact request count, UTC window, credential scope and data-use terms.

## Acceptance and strategy boundary

After lawful data exists, SideDeck will run completed-session validation, corporate-action checks,
session coverage, realistic spread/fee/slippage/latency/gap assumptions and locked chronological
out-of-sample evaluation. Time Machine probabilities will remain scenario estimates. A positive
fixture or backtest result cannot admit a strategy or enable DAY execution.
