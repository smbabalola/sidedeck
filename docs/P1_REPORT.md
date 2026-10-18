# SideDeck P1/P1.1 implementation report

Date: 2026-10-18  
Branch: `feat/p1-foundation`  
Baseline: `06d41b0567143214a237de1f1701b25f8d3f74f6`
Phase status: hardened P1 complete for review; stopped before P2

## Hardening changes

- Double-entry events now validate economic semantics: opening capital, buy gross/fee/cash, sell cash/cost-basis/fee/realized-P&L postings, USD currency, unique accounts, and supported event types.
- In-memory and database idempotency keys reject different-content reuse; retries are no-ops, composite `(portfolio_id, idempotency_key)` uniqueness is durable, and writes are transactional.
- Journal persistence has an autoincrement sequence so equal `occurred_at` timestamps replay in insertion order.
- NAV requires approved instrument-specific USD snapshots whose market and ingestion timestamps are both at or before the decision cutoff and within the configured freshness window.
- Trade intents, manifests, orders, ledger events, instruments, and snapshots fail closed on invalid IDs, sizes, times, currencies, portfolios, unsupported events, or prohibited assets.
- Root `AGENTS.md`, Python 3.12 CI, disposable PostgreSQL CI coverage, and canonical documentation provenance were added.

## Test evidence

Executed with the isolated `.venv` on Python 3.13.16:

| Command | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest` | PASS — 21 passed, 1 skipped |
| `.venv\Scripts\ruff.exe check .` | PASS |
| `.venv\Scripts\mypy.exe src --no-incremental --follow-imports=silent` | PASS — 10 source files |
| `.venv\Scripts\python.exe -m alembic upgrade head` | PASS — disposable SQLite |
| SQLite Alembic upgrade → downgrade → upgrade | PASS |
| SQLite retries, conflict, concurrent write, rollback, equal-timestamp replay | PASS |
| Economic posting, NAV cutoff/freshness, ID and unsupported-event regressions | PASS |
| Hypothesis deterministic replay/idempotency properties | PASS |

The PostgreSQL test is present and runs in CI when `SIDEDECK_TEST_POSTGRES_URL` points to the workflow's disposable service. It was skipped locally because Docker has no usable daemon and connecting to the running PostgreSQL Windows services would risk using an existing user database without approval.

## Deterministic replay example

Both `tradingagents` and `ai-trading` open with USD 1,000. A `tradingagents` buy of 2 AAPL at USD 100 with USD 1 fee leaves cash at USD 799 and cost basis at USD 200. Selling one share at USD 120 with USD 1 fee leaves cash at USD 918, one share marked at USD 110, gross realized P&L USD 20, net realized P&L USD 18, and NAV USD 1,028. Equal timestamps use the durable journal sequence; save/reload/replay preserves the result.

## Scope exclusions

No credentials, agent integration, external market data, eToro call, broker connection, order submission, real funds, scheduler, or live capability was added or invoked. The unlicensed AI Trading source remains external and unexecuted.

## Unresolved items

1. PostgreSQL upgrade/downgrade and persistence evidence remain unverified locally; CI is configured for a disposable PostgreSQL service on Python 3.12.
2. Python 3.12 has CI configuration but has not run in this local Windows environment, which is Python 3.13.16.
3. P2 must preserve proposal-only worker isolation and resolve AI Trading licensing before any source use.
