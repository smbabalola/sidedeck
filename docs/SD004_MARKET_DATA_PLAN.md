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

## Phase 4 evidence reconciliation

The SEC 10-K identifies one common stock class listed on Nasdaq and reports
7,425,545,491 actual common shares outstanding as of 2026-07-23. FY26 diluted
weighted-average shares are 7,453 million, basic weighted-average shares are
7,429 million, and FY26 diluted EPS is $17.95. The implementation now carries
an explicit `actual_outstanding` share-basis requirement and rejects diluted
weighted-average shares as a substitute.

Microsoft's official history reports the latest split as a 2-for-1 effective
2003-02-18, and its June 2026 dividend release records a $0.91 dividend
with an 2026-08-20 ex-dividend date. There is no split in the Jul 29-Oct 20
window. The SIP `adjustment=split` series is therefore compatible with the
split basis, but dividend adjustment is not part of a closing-price valuation.

Quiver's public MSFT history page displays `Close` and `Adj. Close` separately
and shows the 2026 window's rows, but the page currently stops before the
Alpaca series' final 2026-10-20 observation. Its terms permit personal,
non-commercial use but restrict redistribution and commercial/product use.
No export was acquired or committed. The source is therefore an independent
candidate only, not complete reproducible corroboration for SideDeck's 59-row
audit. Yahoo remains rate-limited and unverified. No market cap or P/E is
emitted.

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

Independent complete MSFT prices remain unavailable for a reproducible 59-row
comparison. Corporate-action and actual-share basis are now verified, while
independent price corroboration is `BLOCKED_EXTERNAL`; do not mark SD-004
verified or emit valuation from a partial/proprietary display or fixtures. No
further authenticated request is authorized by this phase.
