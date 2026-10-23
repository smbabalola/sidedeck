# SideDeck — Continuous Integration Sprint / One-Pass Codex Brief

**Status:** Authorised for safe implementation without repeated review pauses.  
**Repository:** `smbabalola/sidedeck`  
**Branch:** `feat/p2-agent-adapters`  
**Verified offline demo:** `4a35d4120d3a6653250083906f10808b593e8994`  
**CI:** https://github.com/smbabalola/sidedeck/actions/runs/39134181178 — Python 3.12, 35 pass, Ruff/mypy/Postgres success.  
**Date:** 2026-10-18.

## Why this sprint

The minimal local demo is complete, but the two original upstream AI trading frameworks have not been run and no market/broker integration exists. The owner wants rapid delivery with **no approval loop for routine safe engineering**. This document is the next, continuous development handoff; `TODO.md` is the authoritative living status list.

## Execution order: work continuously; do not pause after each batch

1. **Fix SD-06H-01…06 integration-boundary correctness** from `TODO.md` in the same working branch as the new adapter work. These are not a P1 reopening. Use source-backed negative regression tests, especially “validated response differs from subsequently executed response,” actual portfolio state in agent request, post-fee cash/exposure, recovery, market calendar and dashboard evidence.
2. **Build the actual TradingAgents adapter** as a separate, restricted **proposal-only worker**, with pinned reviewed upstream reference `e8f5503e9b86d5c2710b0c76b1f686703968c9df` (Apache-2.0). Inspect upstream interfaces and confirm the exact API contract. Do not vendor more than licence permits and do not alter the upstream implementation unless separately authorised. Implement a typed adapter boundary and an optional `TradingAgentsGraph.propagate(...)` invocation through a controlled, separately installed environment:
   - Stable market bundle / timestamp cutoff, no future news or external latest-quote leakage. If upstream research agents cannot be constrained to the approved dataset, **do not claim point-in-time/fair comparison**; explicitly block genuine backtests and document a forward-only alternative.
   - Output normalized to immutable `AgentProposalEnvelope`, rigorous portfolio/instrument checks, STOP/HOLD/BLOCKED if size or price/stop metadata missing. **Never invent trade sizing, stop price or conviction.**
   - Per-run timeout, cost/token budget, model/provider revision, no broker endpoints and no tools for transactions or shell execution under AI control. Fail closed, capture sanitized error/timeout logs. Offline CI must rely on a mocked entrypoint and deny networking; opt-in actual model run only after owner has supplied model credentials locally and approved model spend.
   - Separate *CODE_READY*, *UPSTREAM_IMPORT_VERIFIED*, *UPSTREAM_MODEL_RUN_VERIFIED*, and *ORDER_EXECUTION_DISABLED* statuses so code-only success cannot be mistaken for true running AI.
3. **Create a safe point-in-time market-data import boundary** that accepts local CSV/parquet with data provenance and licensed usage flags; validate schema, monotonic timestamps, coverage, exchange calendar, ingestion/publication cutoffs, explicit adjusted/unadjusted price treatment, split/dividend policy, quote currency and stale data. No free provider/quote scraping is presumed. A locally imported historical data set is **not** necessarily point-in-time unless it has genuine availability timestamps. For a real forward experiment, validate contemporaneous data when observed and persist immutable snapshot hashes.
4. **Prepare independently authored AI Trading protocol** using only its public high-level behavioural specification and legal metadata. Four research personas may map to a single `ai-trading` allocation when licensed. Absolutely no importing/running/editing/copying `imranpollob/ai-trading` source while rights are unclear. Create `docs/LICENSING_DECISION.md` recording observed licence status, required permission, and what has *not* been tested. An independent protocol worker is a substitute, not proof of integrating that original framework. Avoid copying from its source text into code.
5. **Enhance the dashboard** to distinguish three states for every agent (FIXTURE / CODE-READY / VERIFIED EXTERNAL) and show a proper historical equity series, drawdown, positions, fees, every accepted/rejected decision and evidence chain. Correctly report each competitor's virtual `$1,000` allocation. Data provenance and simulation disclaimers must be prominent.
6. **Dry run and test** all safety invariants and cross-agent isolation, including failures, concurrent proposals, invalid data and retries. Fix and rerun without seeking owner signoff at minor steps. Update TODO entries as actually verified; record SHA/CI and exact commands/results in `docs/INTEGRATION_REPORT.md`.

## Key issues already identified in the current actual source

- `src/sidedeck/demo.py` calls the worker twice per agent per session: once in `AgentRunCoordinator.run()` and again directly. The second result is not guaranteed to be identical to the first validated proposal. Never let the unvalidated instance enter the risk/order simulator.
- `_request(...)` always sends `cash_usd=1000` and no holdings even after prior fills. Generate read-only agent snapshot from actual ledger at cutoff; do not trust arbitrary worker-side balances.
- `domain/risk.py` calculates projected exposure using historical cost basis instead of mark-to-market and does not include existing same-symbol holdings in the 20% max position test. It also needs spread/fees revalidation at simulated fill time.
- `domain/simulator.py` and `demo.py` store economic transactions in SQLite and lineage JSON separately. Prove crash recovery and idempotency; keep atomic/reconcilable semantics.
- `_bundle(session)` synthesises EOD market data on Jan 2, 3, 4 2026 (Saturday/Sunday for latter dates). Mark artificial time unambiguously or switch fixture to actual trading-session days, but never imply these are real observed prices.
- Current `results/dashboard.html` is a simple summary table, not complete equity/drawdown/lineage representation. Finish honestly.
- Current `reset-fixture` recursively deletes arbitrary `--results-dir`; add a marker/confirmed scoped safety check to protect user folders.

## Success gates

**Integrated local research engineering (without paid model credentials):**
- Two separately funded ledgers; completely validated proposals, then risk and simulated orders; correct persistence/lineage and P&L; credible offline historical-data import; meaningful dashboard.
- TradingAgents adapter code imports through a constrained, testable boundary in an isolated optional install; unit/integration mocks are green, but **actual upstream run status remains unverified** until authorised and performed.
- AI Trading remains explicitly licensing-blocked, with independent fixture/protocol available but never mislabelled.
- Python 3.12 + disposable PostgreSQL, SQLite, Ruff, mypy, property and negative cases pass in CI.

**External gates (pause only this specific task):**
- A real paid LLM model smoke test requires user-approved model vendor/API credentials and spend.
- An actual imranpollob AI Trading runtime requires clear lawful rights/permission.
- eToro Demo authenticated reads and writes require explicit separate user approval and Demo-only credentials. Do not attempt.
- A real out-of-sample/forward performance competition requires elapsed market sessions and cannot be completed in a coding sprint.

## Git/workflow rules

- Preserve local untracked `SideDeck-Blueprint/` and ignored `.env`, `.venv`, database/results files.
- Commit useful tested increments and update `TODO.md` with each milestone. Normal push only, no force push or merge.
- No private tokens or account identifiers in commits. Do not access an existing user PostgreSQL service.
- Never present fixture output as a trading result from the upstream GitHub frameworks, or simulator output as eToro Demo performance.
- Do not stop between unblocked milestones to ask for confirmation. Record genuine external blockers in TODO and carry on with other safe work.

## Copy-once Codex instruction

> On `feat/p2-agent-adapters`, fetch latest origin and preserve all local untracked/ignored files. Read `AGENTS.md`, `TODO.md` and `docs/INTEGRATION_SPRINT.md`. The offline MVP SD-01…06 has passed CI; do not rebuild it. Implement the SD-06H safety corrections and SD-07/SD-09 code-only integration work in a continuous pass. Expand the existing demo, risk engine, crash recovery, dashboard and offline market-data import; prepare the licensed TradingAgents worker under strict proposal-only, no paid credential/no network defaults. Document AI Trading licensing as blocked. Run tests/CI, update TODO in each milestone, commit/push normally, and report a consolidated final result. Do not ask for review after small tasks, do not execute real upstream agents without approved model access, and never connect to eToro or submit orders.
