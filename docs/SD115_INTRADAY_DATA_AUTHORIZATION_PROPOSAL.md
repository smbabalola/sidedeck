# SD-115 owner-reviewable five-minute data proposal

## Status

Draft only. No request has been made, no provider has been paid, and no credential has been used.
The Day Trader module remains `RESEARCH_ONLY` and the broker remains disabled.

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

If owner-supplied files are unavailable, the owner must first approve the provider, license terms,
credential variable names and exact endpoint contract. A future runner may then be authorized for
at most one bounded retrieval package covering only the three symbols, the stated date window and
five-minute bars, with a persistent reserve-before-send request budget, no retries, no redirects,
no other endpoints, no orders/account calls, and no provider spend beyond the approved amount.
The runner must return only sanitized status, file hashes, coverage and license metadata. A failed
request consumes its budget and is not retried automatically.

No provider or endpoint is selected by this draft, and no authenticated request is authorized by
it. A new owner authorization must name the provider, endpoint(s), budget and data-use terms.

## Acceptance and strategy boundary

After lawful data exists, SideDeck will run completed-session validation, corporate-action checks,
session coverage, realistic spread/fee/slippage/latency/gap assumptions and locked chronological
out-of-sample evaluation. Time Machine probabilities will remain scenario estimates. A positive
fixture or backtest result cannot admit a strategy or enable DAY execution.
