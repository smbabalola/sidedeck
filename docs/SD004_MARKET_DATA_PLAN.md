# SD-004 historical market-data evidence plan

Status: `ALPACA_SIP_ACQUIRED`; full genuine MSFT valuation remains
`BLOCKED_EXTERNAL` as of 2026-10-21. One owner-authorized local authenticated
request was used; no account, portfolio or trading endpoint was accessed.

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

## Authorized acquisition result

The bounded local retrieval used only `GET /v2/stocks/MSFT/bars` with
`feed=sip`, `timeframe=1Day`, `adjustment=split`, and the approved date window.
It made 1 of 20 permitted requests and received HTTP 200. The ignored local
bundle contains 59 bars from 2026-07-29 through 2026-10-20, one page, and a
crash-safe budget file. The sanitized manifest records SHA-256 digest
`20e1e97074cb133d2afb0a3ebe5bca65629c4587cd137a448e3ef50dab3b5284`.
The 2026-09-07 weekday gap is retained as a potential US holiday gap, not
silently treated as missing or filled; a verified exchange calendar is still
required. Corporate-action verification remains pending.

The local SEC reconstruction reports the latest 2026-06-30 period and a
2026-07-29 filing date, with 10/12 latest metrics and 8 fully reconciled
periods. A filing date is not a filing publication timestamp, so the first
price cannot yet be admitted as point-in-time evidence. The Alpaca series is
also not independent corroboration.

## Phase 3 offline reconciliation

The official Nasdaq Trader 2026 schedule confirms that 2026-09-07 was closed
for Labor Day. The 59 expected regular sessions from 2026-07-29 through
2026-10-20 therefore match the acquired dates with no missing or unexpected
sessions. The official SEC EDGAR records match the local Company Facts
accession lineage: 8-K `0001193125-26-323632` was accepted at 16:04:53 ET on
2026-07-29, and 10-K `0001193125-26-323660` was accepted at 16:08:01 ET. Both
are after the 16:00 ET close, so the first eligible valuation close is
2026-07-30; 2026-07-29 is rejected for look-ahead.

Yahoo MSFT history remains an independent candidate, not evidence. Its public
history page was rate-limited during research and no CSV was acquired. The
offline owner-supplied parser uses `Close`, never `Adj Close`, and keeps
provenance and adjustment status unverified until a lawful export and
corporate-action basis are supplied. No market cap or P/E is emitted.

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

Independent corroborated MSFT prices, publication-time evidence, corporate
action validation and share-basis compatibility remain unavailable. SD-004
therefore remains `BLOCKED_EXTERNAL`; do not mark it verified from the single
Alpaca source or fixture adapters. No further authenticated request is
authorized by this phase.
