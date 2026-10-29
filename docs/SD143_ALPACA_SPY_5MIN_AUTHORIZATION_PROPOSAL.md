## Owner direction recorded 29 October 2026 — YES to proposed usage

The owner wishes to proceed assuming (1) local retention and repeat backtesting of downloaded bars, and (2) use of resulting signals with **eToro Demo**. This is an owner decision about the **intended workflow**, **not written permission from Alpaca, the exchanges, or any other rights holder**. It does not establish account-specific entitlement, non-display/cross-broker rights, or compliance with data terms; those are still `UNVERIFIED_EXTERNAL`. Avoid misclassifying these responses as provider licensing evidence.

**Engineering authorised now:** continue offline preparation, request construction, expected-session validation, reproducibility and non-executable research using data already lawfully available under confirmed rights. **Not authorised by this statement:** authenticated Alpaca GETs, subscriptions, remote credentials, distribution, activating eToro, order POSTs or historical HALT reset. Before any request, validate the relevant current terms and account-specific permission, then obtain a scoped authorization describing exact parameters, GET cap and expiry. If provider permission cannot be established, the acquisition remains `BLOCKED_EXTERNAL`.

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

## Pagination calculation and hard request proposal

At most 366 calendar days fall between the proposed bounds. There are at most 262 weekdays in that interval, and a full XNYS regular session has 390/5 = 78 bars (early-close sessions have fewer). A conservative cap is therefore 262 × 78 = 20,436 regular-session bars; a 10,000-bar page size requires at most **three nonempty pages** for the specified regular-session-only window.

**Proposed hard ceiling: 3 successful page GETs, 3 total attempts, 0 retries**, subject to independent verification of Alpaca's boundary semantics and whether any pre/postmarket or extra corrections appear in the response. If a token requests page 4, the request must STOP and produce a new owner-reviewed scope rather than continuing. This estimate is a planning bound, not a licensed entitlement or a substitute for validating each actual exchange session. Non-session bars or provider pagination semantics that invalidate this estimate must be treated as a failure, not silently trimmed to fabricate completeness.

Compute signed absolute UTC endpoints from New York calendar sessions at authorisation time. In particular, do not use naive UTC midnight boundaries and do not infer rights from a successful API response.

## Acceptance and refusal
- Validate complete XNYS market sessions including opening range 09:30–09:45 local New York, early closes, DST, duplicate/missing/out-of-order bars and split-adjustment identity through the existing SD-142 pipeline.
- Independently verify terms, entitlement, raw data integrity, adjustment basis, licensed use, and instrumentation of actual spread/quote delay for future sends. OHLCV alone does not establish execution prices.
- Run a genuinely locked chronological/walk-forward OOS test (>=30 qualified OOS trades plus robustness/cost gates) through the unchanged admission rules; no retroactive split-selection or strategy self-signing.
- Record `BLOCKED_EXTERNAL` if rights or data are unavailable and `NO_GO` if results fail. A successful data read is **not** strategy admission, grant approval, broker release or historical HALT recovery.

## Human decision, only when prerequisites are met

A later authorisation must enumerate the verified account entitlement, terms evidence, exact UTC boundaries, page/retry/GET budget, permitted local storage and cross-broker uses, costs (if any) and expiry. No such authorisation has been made. Until then **zero authenticated Alpaca calls**, zero purchase, eToro Demo `NOT_RELEASED`, historical HALT unchanged.

## Verified offline authorization-contract inspection (29 October)

The current `src/sidedeck/application/sd077_data_authorization.py` already recognises the `ALPACA_SIP_INTRADAY` provider and **only** allows the approved `data.alpaca.markets` HTTPS host. Its `DataAuthorization` type requires all six exact query dimensions: `timeframe=5Min`, `feed=sip`, `adjustment=split`, `start`, `end`, and `limit=10000`; page tokens may vary, but repeated or oversized tokens are rejected. An owner's signed authorization must be short-lived (at most seven days), with a separately persisted request ledger, a bounded request count and retries. The broker/order paths remain disallowed.

**Remaining implementation/evidence split:** This validates only the *local authorization contract*, not a historical SIP collector actually using the scope, complete pagination, immutable persisted provider evidence, account-specific licensing or a genuine strategy result. A fixed `max_requests=3`, `max_retries=0`, and the single SPY URL would be **proposed parameters** for a future signed approval, not an existing grant. The signed `scope.start` and `scope.end` must be calculated using exchange-session UTC boundaries and approved separately.

**No call may be made yet.** The owner's two YES answers describe desired SideDeck functionality and cannot replace the provider's written permission for local archival and eToro-cross-broker automated/non-display use. Do not set `owner_terms_reviewed=True` merely because this review was performed; that flag does not constitute the missing licence.


## Revised architecture decision — ephemeral raw-data handling (29 October)

**Permanent retention of raw Alpaca bars is optional, not a release prerequisite.** The preferred acquisition design processes authorised payloads in memory or an access-controlled temporary workspace, computes input hashes and session/corporate-action validation, performs the offline research, then disposes of raw bars and temporary copies after the authorised run. Do not log full payloads, write raw bars into the repo, retain them in backup/cache, or automatically archive them. If a future independent reproducibility review requires an exact raw dataset, arrange a separately licensed archive or a separately authorised re-fetch; a hash and method alone do **not** guarantee reproducibility.

Persist only non-price-bearing metadata *where the licence allows it*: provider/source identity, entitlement decision reference, query bounds, UTC acquisition time, page count, cryptographic payload hashes, transformation code/version, calendar/adjustment declarations, signed research configuration, holdout identity, summary metrics and audit decisions. Store no bar arrays or invertible derived per-bar series under this policy; retain trade/event details only when licensing allows them. Broker/order/position lineage, risk grants, security audit and incident evidence remain durable independently of this feed-lifecycle choice.

**Rights still required:** authorised download and transient processing, any permitted derived metadata/outputs, automated non-display use, and signals intended for eToro Demo. Eliminating permanent storage does not waive those rights or imply that Alpaca has granted them. The previously recorded YES to retention is superseded as a design preference, not as evidence that any terms were accepted. Until provider rights and a signed narrow acquisition are established, send no Alpaca GETs.
