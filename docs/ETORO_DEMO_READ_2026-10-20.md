# eToro Demo portfolio API — authenticated read success (2026-10-20)

**Project:** SideDeck, P5 agent adapters (`feat/p5-agent-adapters`)
**Status:** `DEMO_PORTFOLIO_READ_OK` / `demo_portfolio_access=PASS`.
**Provenance:** User-executed, single authenticated probe output shared with SideDeck. No access to local credentials or raw response from GitHub.

## Request and outcome

| Field | Sanitized result |
| --- | --- |
| Method | GET |
| Endpoint | `https://public-api.etoro.com/api/v1/trading/info/demo/pnl` |
| User-Agent | `SideDeck/0.1 (read-only demo portfolio probe)` |
| Credential variable names | `ETORO_API_KEY`, `ETORO_USER_KEY` (both reported present; values not disclosed) |
| HTTP | **200** |
| Classification | **DEMO_PORTFOLIO_READ_OK** |
| Requests made | **1** |
| Orders submitted | **0** |
| Real-money endpoints called | **0** |
| Request ID | `c402d92f-2eec-490b-8fb4-161c4687d8c5` |
| CF-Ray | `a4d6ec83b9940ec9-LHR` |
| Response top-level | `clientPortfolio` |

This demonstrates valid API access to **Demo account information**, not permission for Demo writes or proof of a safe execution adapter.

## Observed sanitized collections

| `clientPortfolio` collection | Items |
| --- | ---: |
| `positions` | **4** |
| `entryOrders` | 0 |
| `exitOrders` | 0 |
| `orders` | 0 |
| `ordersForClose` | 0 |
| `ordersForCloseMultiple` | 0 |
| `ordersForOpen` | 0 |
| `stockOrders` | 0 |
| `mirrors` | 0 |

Response schema includes `credit`, `bonusCredit`, `accountCurrencyId`, `unrealizedPnL`; positions expose `positionID`, `instrumentID`, `units`, `amount`, `isBuy`, `openDateTime`, `orderID`, leverage, fees/taxes, and nested `unrealizedPnL.pnL` and asset currency information. No actual balances, P&L amounts, instrument IDs for the positions, or account identifiers were disclosed.

**Important:** Four positions predate SideDeck's verified Demo trading integration. In any SideDeck accounting design, treat them as read-only **unattributed baseline positions**; do not allocate them to `tradingagents` or `ai-trading` or allow an automated close.

## Cash and reporting rules, sourced from eToro documentation

eToro defines USD **available cash** as:

`credit - sum(ordersForOpen[].amount for mirrorID == 0) - sum(orders[].amount)`

The observed collections `ordersForOpen` and `orders` both had zero items, so for this *particular snapshot*, the documented formula reduces to `available cash = credit`. No monetary value can be established from this schema-only report. Validate numeric values, currency ID mapping and the response's actual fields before computing or reporting cash. Do not mistake `bonusCredit` or `unrealizedPnL` for free cash or double-count pending orders.

eToro defines unrealised P&L using individual position fields plus mirror components and associated closed mirror profits. Since mirrors count was zero in this snapshot, direct positions are the relevant source, but currency and numeric validation remain mandatory.

Sources:
- https://api-portal.etoro.com/guides/calculate-available-cash
- https://api-portal.etoro.com/guides/calculate-profit-loss
- https://api-portal.etoro.com/guides/calculate-equity
- https://api-portal.etoro.com/guides/market-orders

## Next work: READ-ONLY P5 adapter, no trading activation

1. Build an eToro **Demo-only** HTTP adapter with strict GET allowlist, exact host/paths, no redirect, bounded responses, conservative retries and clear errors; keep keys in local `.env`, never print sensitive payloads or send them to CI.
2. Parse `clientPortfolio` with strict typed Decimal arithmetic; resolve missing/invalid data as `UNAVAILABLE` or fail closed. Distinguish order arrays, leverage, position direction, fees, USD account cash and asset-currency P&L.
3. Capture a broker-grounded **baseline of the four pre-existing positions** using `positionID` as the position identity. Keep encrypted/private raw snapshot material locally only as required, not in GitHub. Mark baselines unattributed/read-only.
4. Design separate `etoro-demo:tradingagents`, `etoro-demo:ai-trading` and `etoro-demo:unattributed` logical books, isolated from Saxo SIM, Alpaca paper and research. No capital allocation or top-ups until an explicit audited owner decision and verified broker account funds; avoid importing Saxo's EUR 1,000 allocation rule.
5. Reconcile broker positions and orders read-only, with fail-closed discrepancies. Do not infer ownership from matching tickers alone; future SideDeck trades need durable strategy -> order -> broker position ID attribution and exact position-ID protection against closing a pre-existing position.
6. Add offline fixtures and regression tests for zero/missing cash, duplicate position IDs, multi-lot assets, negative/invalid quantities, mirror positions, pending-order deductions, currency mismatch, stale snapshots, concurrent polling, duplicate events and access-control failures.
7. **No Demo or Real POST/DELETE**, no real-account GET, no automatic live tests, no opening/closing orders, and no switch to execution-ready until a separate approval.

## Gate status

- [x] `ETORO_MARKET_DATA_READ=PASS`: prior one-shot AAPL search HTTP 200 / standard Nasdaq instrument 1001 (see `ETORO_V1_MARKET_DATA_PROBE_2026-10-20.md`).
- [x] `ETORO_DEMO_PORTFOLIO_READ=PASS`: this single read-only response.
- [x] `ETORO_DEMO_POSITION_SCHEMA_OBSERVED`: four positions and explicit position IDs.
- [ ] Full value-level cash/position accounting validation with local sensitive-data controls.
- [ ] Read-only Demo snapshot and reconciliation adapter with full offline acceptance tests.
- [ ] Owner-approved, audited virtual capital partitioning between SideDeck strategy books.
- [ ] Separately reviewed Demo-only order lifecycle, idempotency and explicit operator release.
- [ ] Real-money execution remains disabled, regardless of key's possible wider permissions.

**Isolation:** Saxo P4 `NO-GO`, `SIM_SUBMISSION_RELEASED=False`, Alpaca unchanged, no effect on outer `feat/p2-agent-adapters` checkout.
