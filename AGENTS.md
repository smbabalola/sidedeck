# SideDeck — Coding agent standing instructions

Read **`TODO.md` first**; it is the single living progress register. Read `docs/DELIVERY_SPRINT.md`, `docs/P2_IMPLEMENTATION.md`, `docs/P1_REPORT.md` and `docs/P2_REPORT.md` before changing architecture.

## Current authorisation and work style

P0, P1/P1.2 and **P2A are complete**. The project owner has authorised **continuous implementation of the safe, offline SideDeck local demo** (tasks SD-01 to SD-06 in TODO.md) without repeated approval checkpoints. Continue to the next safe unblocked item after each green test. After the demo, code-only proposal-adapter preparation may proceed without credentials or network calls. Do not restart the completed P2A scope.

Work on `feat/p2-agent-adapters`; preserve untracked local work, especially `SideDeck-Blueprint/`, and ignored `.env`/`.venv` and databases. Use scoped, reviewed commits and normal pushes; no force pushes, main merges, or destructive actions. Report a material design change in an ADR.

**Update `TODO.md` in the same commit as each meaningful milestone**, including exact tested functionality, head SHA or reference, CI URL, pass/fail/skip totals, blockers and next action. Make the README accurate. Do not claim upstream integrations, eToro execution or real-market returns from fixture tests.

## Safety invariants

- No credentials, API keys, private keys, account IDs or real-money execution capabilities in tracked content or logs.
- Do not call eToro endpoints or submit real/Demo broker orders without a fresh, explicit owner permission and provisioned **Demo-only** access. Local deterministic simulated fills are authorised and must be marked as such.
- Do not contact existing user databases. PostgreSQL verification runs in a disposable CI/container test database only.
- Never copy, vendor, modify or run `imranpollob/ai-trading` source without rights clearance. An independently authored protocol fixture is not the upstream engine.
- Actual paid AI calls and external data access require owner-approved secrets/provider policies. The TradingAgents licensed adapter may be coded and tested offline with fixtures, but a live model smoke test is separately gated.
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
