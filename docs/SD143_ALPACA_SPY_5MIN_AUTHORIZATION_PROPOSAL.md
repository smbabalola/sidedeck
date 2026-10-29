# SD-143 — proposed first Alpaca 5-minute data scope (NOT AUTHORIZED)

Prepared 29 October 2026 as an **unsigned decision packet**, not an API request, entitlement, grant or approval.

## Purpose and preconditions

Determine whether a limited SPY 5-minute historical SIP sample can support lawful and reproducible ORB research. The **existing ORB** remains unqualified and no strategy is admitted from this request. The owner previously selected Alpaca as a preferred candidate; that choice is **not** consent to authenticated access or spending.

Before any access, an account-specific provider entitlement and permitted personal/business use, local retention/replay, and use for signals intended for eToro Demo must be independently established. If the applicable terms do not permit the activity, stop and request a licensed alternative. Confirm actual SIP plan entitlement and any charge **before** a paid change.

## Narrow proposed scope (awaiting authorisation)

| Dimension | Proposed boundary |
| --- | --- |
| Provider | Alpaca historical equities market data only |
| Host/path | `data.alpaca.markets/v2/stocks/SPY/bars` |
| Instrument | SPY only |
| Timeframe/feed | `5Min`, `sip`, `adjustment=split` |
| History | 2025-10-27 through 2026-10-23, regular and half-day XNYS sessions |
| Method | Paginated read, fixed request ceiling to be calculated and approved **before** execution; zero automatic retries |
| Storage | Only if provider terms permit, record byte hashes, UTC timestamps, page tokens, receipt/provenance |
| Spend | £0/$0 without a separate explicit approval of any fee or subscription |
| Excluded | Trading/accounts/orders, other symbols, quote/live stream, other provider routes, eToro API, bulk expansion, automatic execution |

The nominal `limit=10000` may require pagination. Before a signed request, calculate the maximum pages/request count from the expected sessions and bar count; fix UTC start/end precisely and make any pagination count an explicit hard cap. A missing/looping page token or unexpected number of bars must fail closed. Never silently enlarge symbol, window or budget.

## Acceptance and refusal
- Validate complete XNYS market sessions including opening range 09:30–09:45 local New York, early closes, DST, duplicate/missing/out-of-order bars and split-adjustment identity through the existing SD-142 pipeline.
- Independently verify terms, entitlement, raw data integrity, adjustment basis, licensed use, and instrumentation of actual spread/quote delay for future sends. OHLCV alone does not establish execution prices.
- Run a genuinely locked chronological/walk-forward OOS test (>=30 qualified OOS trades plus robustness/cost gates) through the unchanged admission rules; no retroactive split-selection or strategy self-signing.
- Record `BLOCKED_EXTERNAL` if rights or data are unavailable and `NO_GO` if results fail. A successful data read is **not** strategy admission, grant approval, broker release or historical HALT recovery.

## Human decision, only when prerequisites are met

A later authorisation must enumerate the verified account entitlement, terms evidence, exact UTC boundaries, page/retry/GET budget, permitted local storage and cross-broker uses, costs (if any) and expiry. No such authorisation has been made. Until then **zero authenticated Alpaca calls**, zero purchase, eToro Demo `NOT_RELEASED`, historical HALT unchanged.
