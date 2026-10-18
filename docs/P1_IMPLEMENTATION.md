# SideDeck — Codex P1 Implementation Brief

**Status:** P0 accepted; P1 authorised for implementation in a dedicated feature branch.  
**Repository:** https://github.com/smbabalola/sidedeck  
**Target:** deterministic accounting, market-data validation, domain contracts and automated tests.  
**Out of scope:** any broker call, eToro API, external AI runtime, autonomous scheduler, real funds, paid APIs, actual orders, strategy optimisation.

## 0. Rules of engagement

1. Read all existing documentation before edits, especially the P0 reports and ADRs. Verify the local Git state, including untracked files. Preserve all local work and avoid destructive operations.
2. Correct the folder structure without silently overwriting conflicting files. Place `AGENTS.md` and `START_HERE.md` at the repository root if supplied in the prior development pack. Consolidate canonical documentation into `docs/` from the nested `SideDeck-Blueprint/SideDeck-Blueprint/docs/` only after comparing contents. Preserve the P0 `ADR-001-decisions.md`, `REPOSITORY_AUDIT.md`, and `THREAT_MODEL.md`. Record provenance and discrepancies. If the previous pack is unavailable, report that rather than fabricate its contents.
3. Never embed credentials, account IDs, sensitive paths, secrets, API keys or real-money capabilities. Ensure `.env`, local data, logs and interpreter artifacts are ignored. Any sample config must contain non-secret placeholders.
4. Work on a `feat/p1-foundation` branch created from the actual current base after preserving untracked files. Keep commits scoped and reviewable. Do not push or merge without explicit approval from the project owner; do not force-push.
5. Python 3.12 is the primary runtime; Python 3.13 may be used only if dependency compatibility is demonstrably green and documented. Pin package versions/lock resolution, avoid unnecessary dependencies, and do not use system-wide installs.
6. Do not integrate or copy the unlicensed `imranpollob/ai-trading` implementation into SideDeck. Keep both future agent integrations as explicit TODOs only. Do not install upstream frameworks in P1.
7. P1 can install local Python dependencies in an isolated venv and use local PostgreSQL, but must not contact trading, broker or paid external data systems.

## 1. Deliverables

### 1.1 Repository foundation
- Use a minimal `src/sidedeck/` Python package layout, `tests/`, `pyproject.toml`, lockfile, `.gitignore`, `.env.example`, `README.md` and optional local-only database setup instructions.
- Establish formatting, linting, type checking, test commands and GitHub Actions CI (safe unit tests without secrets). Consider `ruff`, `pytest`, `hypothesis`, `mypy` or equivalent only as justified.
- Add an architecture boundary: `domain`, `application`, `infrastructure`, `fixtures`; domain code imports no broker or network client.

### 1.2 Typed contracts
- `ExperimentManifest`: unique experiment ID, immutable strategy/portfolio IDs, capital allocation of exactly USD 1,000 per competitor, configuration revision, created timestamp, chosen instrument universe and data policy.
- `MarketSnapshot`: canonical instrument ID, source/provider, price type (EOD close or quote), price currency, market timestamp, ingestion timestamp, session, quality metadata; reject NaN/infinity/non-positive/future-dated invalid values.
- `TradeIntent`: immutable strategy/portfolio/experiment identifiers, instrument, buy/sell/hold side, proposed quantity or notional (explicit units), rationale, model/config revision, decision timestamp and data-as-of timestamp; this is **not** an order and cannot execute.
- `Order` and `OrderEvent`: typed proposed/rejected/accepted/submitted/part-filled/filled/cancelled lifecycle, but only in-memory simulation transitions are legal in P1.
- `LedgerEvent`: globally unique event ID, per-portfolio idempotency key, time, currency, causation/correlation ID, immutable journal postings, quantities and traceable event type.
- All money, quantities, prices and fees use `decimal.Decimal`; time is timezone-aware UTC internally. Define canonical serialization.

### 1.3 Accounting core
- Initialise exactly two logically separate portfolios, `tradingagents` and `ai-trading`, with USD 1,000 each. Initial capital must be represented by auditable opening entries, never inferred from a hardcoded NAV value alone.
- Implement balanced, append-only journal postings and deterministic event replay. No mutation of historical postings.
- Track USD cash, positions, cost basis, realised P&L, accumulated fees and externally marked unrealised P&L. NAV = cash + marked position value (minus any recognised liabilities) without double counting.
- Reject negative cash, oversells, duplicate operations, invalid event ordering and cross-portfolio postings unless explicitly designed otherwise. Ensure atomicity on writes and per-portfolio idempotency.
- Make persistence via repository interfaces. Use PostgreSQL + Alembic for durable implementation, with deterministic in-memory fixtures for fast domain tests. Do not build a microservice or event bus.
- Reconcile exact balance, cash and position quantities after save/reload/replay, with safe transactional handling. Include rollback tests and schema migration test.

### 1.4 Instrument and market data safety
- Fixed allowlist for selected liquid US **equities and ETFs only**, identifying asset type, venue, quote currency, precision/fractional policy and pricing/market session. Unknown names/symbols and instrument classifications reject closed.
- Explicitly prohibit crypto, crypto ETFs where policy excludes them, CFDs, FX pairs, leveraged/inverse ETPs, shorting, borrowing and margin.
- Fractional quantities are representable via Decimal but only allowed if enabled per instrument under a documented policy; future broker execution must revalidate supported precision.
- Market snapshot validation is aware of price type and exchange session; EOD prices are not wrongly presented as current real-time quotes. Reject invalid, suspicious, stale, future and missing prices. Define explicit stale-data policy per quote type and state. No random or silent synthetic price fallback in executable valuation/trade flow.
- Simulation fixtures may contain **clearly labelled deterministic synthetic data** only; never pass fixture prices off as live market data.

### 1.5 P1 local simulator
- Accept deterministic scripted trade events from tests only. No external AI-generated orders, no network, no broker client, no scheduler.
- Exercise fills, fees, position updates and equity reconstruction. Model partial-fill and cancel state transitions at the schema level and with unit tests even if execution simulation stays minimal.
- Record sufficient provenance for future strategy-to-intent-to-order-to-fill-to-position audit lineage.

## 2. Acceptance suite (all mandatory)

Tests must cover, at minimum:
- Both portfolios start with exactly USD 1,000, identical allowed instruments and no positions.
- No journal event in A can alter B; no duplicate trade/event can be applied twice, including replay after restart.
- Journal debits/credits balance in the defined accounting units; reconstructed NAV and realised/unrealised returns agree with hand-checked examples.
- Buying beyond cash, overselling, negative/zero quantities, negative fees, wrong currencies and prohibited instruments are rejected.
- Missing/stale/future/zero/negative/non-finite quotes fail closed; UTC/timezone edge cases, market holidays and EOD freshness semantics are covered.
- No floating-point rounding drift on repeated fractional trades or fees; quantities obey instrument precision and execution mode.
- Cancels, partial fills, rollback, recovery and out-of-order event attempts do not corrupt state.
- Property-based tests for conservation/isolation/idempotency/replay consistency; deterministic seed recorded.
- PostgreSQL migration round-trip and persistence smoke tests executed against disposable test DB if local service is available; never touch unrelated user databases. If DB access is unavailable, mark DB acceptance unverified rather than claiming complete.
- CI and local tests run offline without credentials, trading APIs or source-repo imports.

## 3. Deliverable evidence and report

Produce a P1 report stating:
1. branch, head SHA and changed-files inventory;
2. architecture choices and any ADR changes;
3. exact commands executed, test counts and pass/fail/skip totals;
4. sample two-portfolio deterministic ledger replay, with balances and NAV explained;
5. database migration and persistence evidence (or explicit unverified blocker);
6. scope exclusions verified: no AI integration, no broker connection, no actual/simulated external order submission, no credentials;
7. known defects, unresolved design questions and P2 entry risks.

P1 is **NOT COMPLETE** until the finance, market-data, isolation and replay tests pass, the canonical documentation tree is coherent, and we review the evidence. Stop for review at the end of P1; do not advance into P2 autonomously.
