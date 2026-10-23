# SideDeck — Continuous Delivery Sprint (Codex execution brief)

**Date:** 2026-10-18  
**Branch:** `feat/p2-agent-adapters`  
**Owner's direction:** Deliver as much working SideDeck functionality as possible now, without repeated handoffs between ChatGPT and Codex.  
**Execution boundary:** Approved local/offline development and CI only. No eToro authenticated access, no broker orders, no real money, no unauthorised paid AI calls, no reuse of unlicensed upstream source.

## Start with the true repository state

P1.2 at `cae13cfb7f01b8fd3a5c1c2ae21a56ac9de94733` is accepted. P2A is **already implemented** at `a2b402d18de9de525ebe97d40ebbe444482b8a4f`. [P2A CI](https://github.com/smbabalola/sidedeck/actions/runs/39132670450) passed. P2A contains typed agent request/bundle/envelope contracts, point-in-time validation, two **fixture-only** workers, persistent audit records and Alembic 0004. **Do not rebuild or redo P2A.** No upstream AI has been run and no local virtual fills were executed.

Read `TODO.md`, `AGENTS.md`, `docs/P1_REPORT.md`, `docs/P2_REPORT.md` and `docs/P2_IMPLEMENTATION.md` before editing. `TODO.md` is the living source of truth; this brief gives the end-to-end implementation sequence and exit tests. Record architecture deviations in an ADR, preserving P1 invariants.

## Sprint objective — a real, runnable local demo

Without any paid tools or credentials, an engineer should be able to:

1. Clone/install the repository using one documented setup command.
2. Run a deterministic, labelled **offline fixture** competition containing exactly two USD 1,000 independent ledgers.
3. Observe both fixture competitors emit BUY/SELL/HOLD trade intents, including realistic rejection cases.
4. See every intent validated through the **SideDeck-owned risk and execution simulator**, with actual in-app journal entries for **simulated** fills only.
5. Inspect stable run -> intent -> risk decision -> order -> fill -> ledger event -> position lineage and restart-safe persistent audit.
6. Open a local dashboard to compare NAV, cash, realised/unrealised P&L, fees, exposure, drawdown, trade history and logged model/data provenance.
7. Rerun against the same fixture set and reproduce the same financial results without leaking a request to the network. Distinguish fixture from actual agent inference and simulator fills from broker fills in every display/export.

This is **Track A** of `TODO.md`. Do not present it as proof that the two GitHub AI engines, external prices, or eToro Demo work.

## Implementation order — pursue tasks consecutively

### A. Developer entry point, non-destructive setup
- Inspect and preserve the current tree, local untracked work and ignored `.env`. Checkout the correct feature branch non-destructively.
- Clean up root `README.md` (currently essentially empty) so it explains capabilities accurately and gives Windows PowerShell and bash examples. Set up an isolated venv and repeatable dependency install; run tests first.
- Add `python -m sidedeck.demo` (or another stable documented CLI) with modes `run`, `status`, `report`, `reset-fixture` where appropriate. Never silently delete prior runs: resets must use a scoped disposable/demo dataset or opt-in flag.
- Use stable experiment IDs and fixture versions, not hardcoded global singleton state.

### B. Risk engine independent of AI outputs
- Implement `RiskPolicy`, `RiskDecision`, `RiskGate`, reason codes, policy version and *read-only* portfolio snapshot evaluation. Revalidate against current actual ledger state at execution time, never just the worker-provided holdings.
- Enforce configured maximum 20% position allocation, 80% total invested exposure, 4 simultaneous holdings, no borrowing/negative cash, long only, no shorts, no crypto/crypto-linked ETFs, no CFDs, FX, leverage, inverse ETFs or unknown instruments.
- Validate USD denominations, accepted as-of market bundle, snapshot age and source type; prohibit using fixture pricing for an eToro/broker mode by construction.
- For trade-level 1% intended stop-risk budget, require an explicit stop price / invalidation and check consistent units; if no usable stop information is available, HOLD/REJECT, do not invent it. In a fixture, provide a clearly artificial deterministic stop for testing. A stop is never guaranteed to execute at its limit.
- Use Decimal and UTC everywhere; fees/spread/slippage are booked once. Include policy-denied and allowed examples.

### C. Local fill simulator and atomic lineage
- Implement explicit order state transitions, immutable intents and fills; support buy, partial fill, sell, cancel, restarts, duplicates and idempotency conflicts, never accepting invalid transitions.
- If P1 ledger needs new metadata keys, use forward-compatible migrations and retain posted financial semantics. Avoid mutable historical journal entries.
- Simulated fill pricing is deterministic from fixture observations with explicitly stated assumptions. Respect opening cash, exposure, instrument precision, fees, and price gaps. Avoid manufactured backtesting alpha claims.
- Treat a batch write as atomic. A crash/retry must not double-debit cash or duplicate positions. Validate corresponding accounting journal postings.
- Preserve audit lineage and portfolio boundaries across persistence and recovery. Mark every fill `SIMULATED_LOCAL`; no eToro order ID should be fabricated.

### D. Demonstrable dual-portfolio workflow
- Reuse P2A request/bundle/gateway/audit contracts; coordinate both fixture workers through the same input point-in-time universe and decision clock.
- The current AI Trading fixture produces HOLD by default. Add **independently authored, deterministic scenario behaviour** that exercises both competing ledgers while clearly marked protocol-fixture (not actual upstream AI), or use an approved alternate fake worker for integration tests. Do not modify/copy `imranpollob/ai-trading` source.
- Produce at least three timestamped trading sessions with distinct cash/position paths, plus at least one rejection path and one intentional HOLD. Use one of the fixed approved US tickers with explicit scenario-specific prices, but do not present these prices as actual observed market history.
- Produce JSON/CSV run artifacts under ignored `results/` and/or persistent SQLite/Postgres test DB; ensure deterministic result hashes (excluding generated run IDs and wall-clock durations if required).

### E. Local dashboard and report
- A minimal Streamlit dashboard is preferred for fast validation; do not build an elaborate SPA.
- Show distinct $1,000 portfolio names, NAV/equity series, position quantities, realised/unrealised P&L, cash, cost/fees, drawdown, latest decisions, rejected proposals, simulated fills, model costs (fixture=0), timestamps and provenance.
- Clearly print `FIXTURE — NOT UPSTREAM AI`; `SIMULATED ORDERS — NO ETORO`; `PRICES ARE SYNTHETIC`. Hide no real-execution caveats in tooltips.
- Export results. If benchmark prices are synthetic or missing, label comparison accordingly or omit benchmark; do not imply real SPY outperformance.

### F. Green evidence and handoff
- Add tests for valid/invalid risk constraints, partial fills/cancel, negative cash, future/injected prices, duplicate operation IDs, cross-portfolio contamination, replay after restart, deterministic comparison, dashboard data accuracy, failed process actions, prohibited broker/network paths.
- Run local `pytest`, `ruff check .`, `mypy src`, SQLite Alembic migration round trip and disposable PostgreSQL CI. Give exact pass/skips and warnings; do not misreport fixture tests as real-AI smoke tests.
- Produce `docs/MVP_REPORT.md` with a truthful execution transcript/expected output, CLI/dashboard commands, samples, financial reconciliation and screenshots only if screenshots actually captured.
- Update `TODO.md` as tasks complete; include final SHA, CI URLs and outstanding external gates. Commit and push each meaningful step normally, no force push or merge.
- **Do not pause between A through F to ask the user for permission.** If a test fails, debug and rerun. Stop only on a material blocker or after accomplishing the maximum achievable safe code development.

## Safe follow-on work when Track A is green

Without needing another approval, proceed to **code-only, zero-credential** preparation of the actual licensed TradingAgents adapter: pinned upstream protocol, separate process, strict no-broker interfaces, model/config cost bounds, data as-of enforcement and isolated fixture tests. Do not invoke an actual paid LLM without approved API credentials. Clearly report integration smoke test as not run if unavailable.

Next, document `imranpollob/ai-trading` licence and execution-tool blockers. Its original source is not licensed for embedding/redistribution based on current evidence; an independently authored substitute worker is **not** the same upstream system. Do not use real GitHub repo source in the project without lawful permission.

Prepare read-only eToro Demo API interfaces **without making network calls**, with a future explicit opt-in gate for authenticated reads and an even higher gate for Demo writes. Never implement real-money write endpoints.

## Non-negotiable engineering rules

- **Always fail closed**: no synthetic fallback disguised as market data; no missing-data-to-zero conversion; no AI direct broker tool access; no arbitrary shell command execution from model text.
- All source and event identities must be traceable; never allow two competitor portfolios to transfer funds, fills or positions.
- The local simulator must never share credentials or transport classes with a broker execution adapter.
- No attempts to install or run the unlicensed AI Trading repository or send data to external systems without approved rights and credentials.
- No secrets committed; no database changes on an existing personal Windows PostgreSQL server.
- Only isolated reviewer-approved commits, normal pushes, no destructive operations, no merging main.

## Codex invocation — paste once

> Read TODO.md, AGENTS.md, docs/DELIVERY_SPRINT.md and the P1/P2 reports. P2A is already done; do not rebuild it. On feat/p2-agent-adapters, implement the entire safe offline SideDeck MVP described in sections A–F in one uninterrupted development pass. Write the tests, fix failures, and update TODO.md in the same commits as features. Push normal commits; do not merge. After the MVP works, continue safe code-only TradingAgents adapter preparation if possible. Do not ask me to approve each small stage. Stop only for an actual external permission/credentials/licence/broker-access gate or after the complete safe backlog is delivered. Report final SHA, CI URL, CLI/dashboard launch instructions and which integrations are still mocked or blocked.
