# SideDeck P1/P1.2 implementation report

Date: 2026-10-18  
Branch: `feat/p1-foundation`  
Baseline: `06d41b0567143214a237de1f1701b25f8d3f74f6`
Phase status: final persistence gate complete for review; stopped before P2

## Hardening changes

- Double-entry events validate economic semantics: opening capital, buy gross/fee/cash, sell cash/cost-basis/fee/realized-P&L postings, USD currency, unique accounts, and supported event types.
- In-memory and database idempotency keys reject different-content reuse; retries are no-ops, composite `(portfolio_id, idempotency_key)` uniqueness is durable, and writes are transactional.
- Journal persistence has an autoincrement sequence so equal `occurred_at` timestamps replay in insertion order. PostgreSQL sequence state is reset after populated migration.
- Legacy same-portfolio equal-timestamp journals fail safely instead of being UUID-reordered.
- `save_events` retries the entire atomic batch after a uniqueness race, resolving equivalent retries while retaining all noncolliding events.
- `operation_id` is the stable semantic operation identity; generated `event_id` identifies a journal row. Same key plus equivalent payload is a no-op with a new event UUID; different payload is an explicit conflict.
- NAV requires approved instrument-specific USD snapshots whose market and ingestion timestamps are both at or before the decision cutoff and within the configured freshness window.
- Trade intents, manifests, orders, ledger events, instruments, and snapshots fail closed on invalid IDs, sizes, times, currencies, portfolios, unsupported events, or prohibited assets.
- Only `tradingagents` and `ai-trading` can create or mutate ledger events through the application/domain boundary.
- Root `AGENTS.md`, Python 3.12 CI, disposable PostgreSQL CI coverage, and canonical documentation provenance are present.

## Test evidence

Executed with the isolated `.venv` on Python 3.13.16:

| Command | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest` | PASS — 24 passed, 1 skipped; 3 SQLite adapter deprecation warnings |
| `.venv\Scripts\ruff.exe check .` | PASS |
| `.venv\Scripts\mypy.exe src --no-incremental --follow-imports=silent` | PASS — 10 source files |
| `.venv\Scripts\python.exe -m alembic upgrade head` | PASS — disposable SQLite |
| SQLite Alembic upgrade → downgrade → upgrade | PASS |
| Populated legacy SQLite migration and immediate post-migration insert | PASS |
| SQLite ambiguous-order rejection, retries, conflicts, concurrent batches, rollback, and replay | PASS |
| Economic posting, NAV cutoff/freshness, ID, portfolio, and unsupported-event regressions | PASS |
| Hypothesis deterministic replay/idempotency properties | PASS |

Independent pre-hardening evidence: [GitHub Actions run 39130709618](https://github.com/smbabalola/sidedeck/actions/runs/39130709618) passed on Python 3.12 with PostgreSQL schema migration, Ruff, mypy, and 22 tests. Final P1.2 evidence: [GitHub Actions run 39131490502](https://github.com/smbabalola/sidedeck/actions/runs/39131490502) passed on Python 3.12 with disposable PostgreSQL, 25 tests, Ruff, and mypy. An earlier final-gate attempt ([39131409864](https://github.com/smbabalola/sidedeck/actions/runs/39131409864)) correctly exposed the rollback-test issue that was corrected before the passing run.

The PostgreSQL test provisions a disposable CI service and covers populated legacy migration, sequence-safe post-migration inserts, persistence, replay, rollback, unique-key conflicts, and downgrade/upgrade. It is skipped locally because Docker has no usable daemon; existing PostgreSQL Windows services were not contacted.

## Deterministic replay example

Both `tradingagents` and `ai-trading` open with USD 1,000. A `tradingagents` buy of 2 AAPL at USD 100 with USD 1 fee leaves cash at USD 799 and cost basis at USD 200. Selling one share at USD 120 with USD 1 fee leaves cash at USD 918, one share marked at USD 110, gross realized P&L USD 20, net realized P&L USD 18, and NAV USD 1,028. Equal timestamps use the durable journal sequence; save/reload/replay preserves the result.

## Scope exclusions

No credentials, agent integration, external market data, eToro call, broker connection, order submission, real funds, scheduler, or live capability was added or invoked. The unlicensed AI Trading source remains external and unexecuted.

## Unresolved items

1. Local PostgreSQL upgrade/downgrade and persistence evidence remain unverified because Docker has no usable daemon and existing PostgreSQL Windows services were not contacted. Disposable PostgreSQL coverage is configured in CI.
2. The local environment is Python 3.13.16; Python 3.12 is exercised by CI.
3. Three local SQLite adapter tests emit a Python 3.12 datetime-adapter deprecation warning from SQLAlchemy; no correctness failure.
4. P2 must preserve proposal-only worker isolation and resolve AI Trading licensing before any source use.
