# SideDeck P2 — proposal-only acceptance gate

Initial, isolated P2 implementation branch: `feat/p2-proposal-gate`, branched from P1 commit `cae13cf`.

## Boundary

`evaluate_proposal` checks a strategy's typed `TradeIntent` against the experiment manifest and a validated, time-aligned market snapshot. Its response is a pure immutable decision with a reason. It **never creates an Order, submits an order, invokes Alpaca, or changes the accounting ledger**.

The acceptance result means only that the suggested intent passes structural and market-data checks. It is **not executable authorization**. Any later simulated order must independently validate cash, positions, per-trade risk, instrument policy and broker execution restrictions.

## Explicit deferred work

- AI/agent isolation and provider adapters; licensed use only.
- Portfolio-specific allocation and portfolio risk checks.
- Historical market-data provenance, session calendar and corporate actions.
- Durable proposal storage, decision audit and replay.
- Alpaca **paper-only** brokerage adapter, credentials and account binding after independent acceptance.
- No live funds, no eToro access and no external broker calls in this phase.

## Tests

`tests/test_proposals.py` covers accepted-but-not-executed intents, rejected portfolios, instrument scope, mismatched snapshot, stale snapshot and as-of mismatch. CI must pass before merging this branch.

## P2 additional components (2026-10-19)

Portfolio risk screening is implemented in `application/risk.py`; buy limits are initially 20% single-position, 80% gross exposure and 10% cash reserve, subject to review. `infrastructure/proposal_audit.py` adds an append-only SQLite-testable audit record with replay, SHA-256 integrity checks and scoped idempotency; it still requires an Alembic migration and concurrency hardening before production. `infrastructure/alpaca_paper.py` contains only a disabled configuration boundary for `SideDeckdemo` and `ALPACA_API_KEY2` (with independent secret environment variable `ALPACA_API_SECRET_KEY2`). No keys are read; no network or order endpoints are called. Real execution remains forbidden.
