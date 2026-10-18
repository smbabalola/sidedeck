# SideDeck — Coding agent standing instructions

Read **`TODO.md` first**; it is the single living progress register. For the **current active sprint**, read **`docs/ETORO_API_FIXES.md`** next, then `docs/ETORO_HISTORICAL_DATA.md`. The earlier `docs/REAL_AGENT_SMOKE_TEST.md`, `docs/DATA_ISOLATION_RECOVERY.md` and `docs/INTEGRATION_SPRINT.md` remain background; do not resume Yahoo-native isolation work unless the user separately requests it. Then read `docs/DELIVERY_SPRINT.md`, `docs/P2_IMPLEMENTATION.md`, `docs/P1_REPORT.md` and `docs/P2_REPORT.md` before changing architecture.

## Current authorisation and work style

P0, P1/P1.2, **P2A, and the minimal offline SideDeck demo (SD-01 through SD-06) are complete**. The project owner has authorised **continuous safe development of the integration-hardening and proposal-only research adapter sprint** (SD-06H and SD-07/SD-09 in TODO.md) without repeated approval checkpoints. Continue to the next safe unblocked item after each green test. Do not restart accepted scope. The owner has now authorised **small, locally controlled NVIDIA/Ollama/OpenAI model-only smoke tests** with existing ignored `.env` credentials, governed by `docs/REAL_AGENT_SMOKE_TEST.md`. This does not authorise unrestricted paid calls, disclosure/commit of credentials, unlicensed upstream AI Trading execution, or broker orders/real trading. **Consumed permission (2026-10-18):** The owner authorised one bounded eToro **market-data-only** GET probe for AAPL/MSFT/SPY/QQQ, and Codex ran it once. AAPL search returned HTTP **403**, causing the fail-closed stop before any candle GET or further symbol searches. **That authorisation is now exhausted; no further authenticated eToro endpoint calls or key use are permitted** without fresh approval. See `TODO.md` SD-11C evidence / SD-11D. Investigate scope, environment, expiration and IP whitelist through the eToro API Portal **UI only**; a 403 does not establish historical coverage. Keep working independently on offline licensed CSV ingestion and fixtures. The GitHub assistant has no access to the owner's ignored local `.env`. Never broaden to account, portfolio, Demo/Real orders, or fresh market-data calls without express approval.

Work on `feat/p2-agent-adapters`; preserve untracked local work, especially `SideDeck-Blueprint/`, and ignored `.env`/`.venv` and databases. Use scoped, reviewed commits and normal pushes; no force pushes, main merges, or destructive actions. Report a material design change in an ADR.

**Update `TODO.md` in the same commit as each meaningful milestone**, including exact tested functionality, head SHA or reference, CI URL, pass/fail/skip totals, blockers and next action. Make the README accurate. Do not claim upstream integrations, eToro execution or real-market returns from fixture tests.

## Safety invariants

- No credentials, API keys, private keys, account IDs or real-money execution capabilities in tracked content or logs.
- Do not call eToro endpoints or submit real/Demo broker orders without a fresh, explicit owner permission and provisioned **Demo-only** access. Local deterministic simulated fills are authorised and must be marked as such.
- Do not contact existing user databases. PostgreSQL verification runs in a disposable CI/container test database only.
- Never copy, vendor, modify or run `imranpollob/ai-trading` source without rights clearance. An independently authored protocol fixture is not the upstream engine.
- Limited model-only provider calls are owner-authorised for local testing subject to the runbook's privacy, call-count, allowance and provider policy checks. The TradingAgents licensed adapter may be tested using local ignored `.env` credentials, but actual upstream graph runtime vs provider-only inference must be independently evidenced. No secret values in source, logs, git or chat.
- AI model outputs are **proposals**, never direct orders. SideDeck owns validation, risk, local execution simulation, accounting, identity and persistence.
- Use `Decimal` for money/prices/quantities, UTC-aware time and validated as-of market bundles. Missing/stale/future/fabricated-as-real data fail closed.
- Separate the two USD 1,000 portfolios. No cash, fill, fee or idempotency cross-contamination.
- Never disguise fixture data or synthetic results as genuine market observations or trading performance.
- For tasks blocked by an external permission gate, record `BLOCKED` in TODO and continue with safe independent work.

## Minimum continuous verification

Use the isolated venv, run:
```powershell
.venv\Scripts\python.exe -m pytest
.venv\Scripts\ruff.exe check .
.venv\Scripts\mypy.exe src --no-incremental --follow-imports=silent
.venv\Scripts\python.exe -m alembic upgrade head
```

Test disposable SQLite migration round trips and PostgreSQL CI when schemas change. Report CI run links, warnings, exact test counts and unverified external dependencies. End with a runnable demo command, measurable outputs and a truthful `TODO.md` status, without requesting minor approvals.
