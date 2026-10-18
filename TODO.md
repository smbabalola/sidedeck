# SideDeck — Living TODO and delivery status

**Repository:** https://github.com/smbabalola/sidedeck  
**Canonical branch:** `feat/p2-agent-adapters` until reviewed and merged.  
**Updated:** 2026-10-18 (initial delivery-sprint board)  
**Verified branch HEAD at creation:** `a2b402d18de9de525ebe97d40ebbe444482b8a4f`  
**CI evidence:** https://github.com/smbabalola/sidedeck/actions/runs/39132670450 — successful.  
**Delivery priority:** runnable, honestly labelled local two-portfolio trading demo first; genuine third-party integrations after their gates.

## Mandatory maintenance

- This file is the single living task list. Every coding agent **must read it first** and update it **in the same commit** as each completed milestone. Record actual head SHA, CI URL, exact tests, user-visible evidence, changes, remaining risks and next task.
- Never check an item off because its specification, mock, or fixture exists. Mark a third-party engine integrated only after **its actual framework** ran successfully under controlled access.
- Codex may complete all safe local/offline tasks below in one continuous development run, with small reviewed commits and CI checks. **Do not stop for approval at every item.**
- Stop only for an unavoidable external gate: secrets or paid model/data access; rights/licensing clearance; eToro authenticated reads/writes; access to existing personal databases; a potentially destructive operation; or permission to merge/release.
- Do not overwrite or stage untracked local `SideDeck-Blueprint/`, ignored `.env`, `.venv` or private database files. No real-money trading. Never fabricate market observations, execution fills or P&L.
- Keep `docs/DELIVERY_SPRINT.md`, project reports and README aligned. If blocked, record blocker and implement the next safe independent task; do not halt the entire sprint.

## Definition of “complete”

**Track A — runnable local demo:** The developer starts SideDeck using documented commands; two **separate $1,000 virtual ledgers** receive validated fixture-produced decisions; trades are risk-checked and **simulated locally only**, with accounting, positions, exposure, equity curves, P&L, audit lineage, dashboard and reports. Testable without credentials. Mark synthetic inputs **FIXTURE / NOT LIVE MARKET DATA** and decisions **NOT REAL UPSTREAM AI**.

**Track B — genuine original experiment:** The actual TradingAgents and imranpollob/ai-trading frameworks run in isolated proposal-only mode (subject to licence/rights and model credentials), consume valid common point-in-time data, and eToro Demo orders/fills reconcile to the two SideDeck ledgers after explicit broker access approval. A fair forward test requires elapsed trading sessions. **Track B cannot be promised within hours** and is separate from the working demo.

## Verified complete

- [x] **P0 — Foundation planning and security assessment** (2026-10-18).
- [x] **P1/P1.2 — Portfolio ledger and persistence foundation.** Accepted GitHub SHA `cae13cfb7f01b8fd3a5c1c2ae21a56ac9de94733`, CI https://github.com/smbabalola/sidedeck/actions/runs/39131573901 — 25 passed, PostgreSQL service, Ruff/mypy green.
- [x] **P2A — Proposal gateway, two deterministic fixture workers, audit persistence, migration 0004.** `a2b402d18de9de525ebe97d40ebbe444482b8a4f`; CI https://github.com/smbabalola/sidedeck/actions/runs/39132670450 — passed. **Neither upstream AI engine has run.** Local 30 passed/1 skipped; PostgreSQL CI 31 passed.

## NOW — execute continuously to working demo

- [ ] **SD-01 / P0 — Runnable project:** Replace the placeholder README with truthful setup, Windows/Linux commands, expected outputs, fixture disclaimers, `python -m sidedeck.demo` (or documented equivalent) and instructions for viewing logs/dashboard. Preserve other documents.
- [ ] **SD-02 / P0 — Deterministic risk policy:** Enforce eligible universe (no crypto, crypto-linked ETFs, leveraged/inverse products, CFDs, shorts or FX), valid as-of input, cash sufficiency, per-position cap 20%, gross exposure cap 80%, max 4 positions, configurable 1% risk budget if a defensible stop exists; reject trades without mandatory risk metadata instead of inventing stops. Include clear refusal reasons.
- [ ] **SD-03 / P0 — Local execution simulator:** Validate proposals and generate durable order/fill lifecycle with transaction fees, configurable spread/slippage, partial fills and cancellation, idempotency and causal link `run -> intent -> decision -> order -> fill -> journal -> position`. **No broker adapter and no network orders.**
- [ ] **SD-04 / P0 — Two-agent end-to-end fixture runner:** Both competitors consume the same timestamped fixture bundle, each funds $1,000; SideDeck applies risk and simulator; verify position, cash, NAV, fees and replay. Provide several deterministic market sessions so the output is inspectable rather than a one-off empty ledger.
- [ ] **SD-05 / P0 — Local dashboard & export:** Side-by-side cash, market value, NAV/equity curves, positions, exposure, P&L, drawdown, rejected intents, trades/fills, evidence, agent and data provenance. Explicit `FIXTURE`, `SIMULATED`, `NO ETORO` labels. Downloadable local CSV/JSON report; no unverified claims of AI profitability.
- [ ] **SD-06 / P0 — Full acceptance:** End-to-end deterministic regression/property tests, portfolio isolation, no duplicated economic effect, restart persistence, cutoff/timezone guards, no network leakage, negative inputs, price gaps and both zero-trade and multiple-trade scenarios. Python 3.12 + disposable PostgreSQL CI, SQLite, Ruff and mypy green. Update this TODO and publish reproducible demo evidence.

## THEN — genuine research integrations without broker execution

- [ ] **SD-07 / P1 — Actual TradingAgents adapter:** Pin supported licensed upstream SHA; isolated worker and bounded resource/time/API cost; no broker tools; verified as-of market data; normalized structured proposals and provenance. Opt-in local model smoke test only with owner's approved model credentials. Offline CI remains fixture-only. Do **not** claim integrated based only on a fixture.
- [ ] **SD-08 / P1 — AI Trading rights gate:** Inspect licence/permission. No vendoring/copying/running upstream source without lawful rights; if unresolved, keep **original independently implemented protocol/worker** distinct and honestly tagged as *not imranpollob upstream*. Disable upstream direct MCP buy/sell, random quotes, scheduled autonomous trades and crypto exposures when eventually authorised. Four internal personas share exactly one $1,000 SideDeck ledger.
- [ ] **SD-09 / P1 — Market-data adapter:** Use a verifiable approved provider or safe timestamped CSV import; quality, publication/ingestion timestamps, point-in-time availability, calendar/session policy, split/dividend semantics and explicit data licensing. No synthetic prices used for genuine scorecards.
- [ ] **SD-10 / P1 — Real research acceptance:** Demonstrate both actual upstream engines only if access/rights solved, record costs and prompt/version hashes, compare identical data cutoffs, budget limits and agent failures. If not, mark an honest blocker and close only Track A.

## LATER — authenticated Demo and forward validation (external dependencies)

- [ ] **SD-11 / P2 — eToro Demo API (separate owner approval):** Verified Demo-only read and write API scopes, secure secrets, sandbox/virtual account semantics, broker instrument mapping, request deduplication and fill/position reconciliation. Simulated isolated SideDeck ledgers must not be misrepresented as two independent broker subaccounts.
- [ ] **SD-12 / P2 — Supervised then automated Demo:** Reconciliation, risk stop, kill switch, recovery, unmatched-fill alerts and auditable order approval. Never connect to Real trading.
- [ ] **SD-13 / P2 — Fair forward evaluation:** Risk-adjusted return vs SPY and cash baselines, trading spreads/slippage, model/data costs, drawdown and uncertainty; collect sufficient real trading sessions before declaring a winner.
- [ ] **SD-14 / P2 — Merge and release:** Only after owner approves release; commit SHA, CI, operations runbook and rollback evidence.

## Active blockers and mitigations

1. **AI Trading copyright:** Upstream `imranpollob/ai-trading` shows no root licence; do not reuse source without permission. Safe independent protocol/fixture work may proceed.
2. **Model credentials / AI cost:** No approved API credentials supplied to Codex or GitHub; genuine model inference cannot be verified until user configures approved secrets locally.
3. **eToro Demo:** User approval, private Demo credentials and endpoint-level scope checks required before authenticated calls/orders; do not auto-attempt access.
4. **Real quote access:** No provider or point-in-time feed connected. Keep deterministic fixtures clearly marked; no real performance claims.
5. **Actual forward test:** Requires market sessions and cannot be completed just by writing code.
6. **Previous P1 SQLite datetime deprecation warning:** Record as nonblocking unless it affects correctness.

## Change log

| Date | Source / checkpoint | CI | Updated state |
|---|---|---|---|
| 2026-10-18 | P1.2 `cae13cf` | [39131573901](https://github.com/smbabalola/sidedeck/actions/runs/39131573901) | Accepted accounting foundation |
| 2026-10-18 | P2A `a2b402d` | [39132670450](https://github.com/smbabalola/sidedeck/actions/runs/39132670450) | Accepted fixture proposal gateway |
| 2026-10-18 | Delivery sprint authorised | See subsequent commit | Living backlog established |

**Next action:** Codex reads `docs/DELIVERY_SPRINT.md` and implements **SD-01 through SD-06 as one continuous local demo sprint**, pushing incremental working commits and updating this file.
