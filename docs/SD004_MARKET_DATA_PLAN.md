# SD-004 historical market-data evidence plan

Status: implementation verified; genuine MSFT valuation evidence remains
`BLOCKED_EXTERNAL` as of 2026-10-21. No authenticated request, paid dataset or
credential was used in this batch.

## Provider findings

Alpaca documents the historical stock-bars route as
`https://data.alpaca.markets/v2/stocks/{symbol}/bars`, with explicit `feed`
values including `sip` and `iex`, `1Day` timeframes, pagination through
`next_page_token`, and explicit `adjustment` values. Its FAQ says a historical
SIP query without a subscription must end at least 15 minutes in the past. The
adapter therefore requires the feed and adjustment in the request and records
them in the evidence; it never uses the subscription-dependent default.

Nasdaq’s public MSFT historical page was reviewed and currently reports that
data is unavailable. Nasdaq Data Link documents historical consolidated EOD
data, but access and licensing/entitlement were not established locally. A
Nasdaq parser exists for owner-supplied evidence only; it has no transport.

## Admission rules

`p5_alpaca_history.py` is a read-only data adapter boundary. It validates
approved ticker shape, explicit IEX/SIP feed, USD, regular daily OHLCV, cutoff,
pagination, duplicate dates, bounded retry classes and redacted failures.
`p5_nasdaq_history.py` validates exact MSFT identity, dates, session, adjustment
basis and source IDs, but deliberately returns provenance as pending.

`p5_msft_valuation.py` admits market cap/P-E only when two distinct source
identities agree within an explicit tolerance, the filing publication timestamp
precedes the cutoff and price, corporate actions are explicitly verified,
shares/EPS are filing-dated and the price basis is split-adjusted. Otherwise it
fails closed. Fixture tests demonstrate rejection paths; they are not genuine
market evidence.

## Remaining blocker and next action

No local, independently corroborated MSFT price series is available in the
approved checkout. SD-004 remains `BLOCKED_EXTERNAL`; do not mark it verified
from the fixture adapters. A future bounded approval request should name the
exact Alpaca data endpoint/feed, symbol, date range, request count and local
credential use. Nasdaq evidence must separately establish lawful access,
adjustment semantics and a genuinely independent source relationship.
