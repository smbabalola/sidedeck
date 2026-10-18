# SideDeck — Living TODO and delivery status

**Repository:** https://github.com/smbabalola/sidedeck  
**Canonical branch:** `feat/p2-agent-adapters` until reviewed and merged.  
**Updated:** 2026-10-18 (integration hardening and proposal adapter sprint)  
**Verified Track A SHA:** `4a35d4120d3a6653250083906f10808b593e8994`  
**Track A CI evidence:** https://github.com/smbabalola/sidedeck/actions/runs/39134181178 — 35 passed, Ruff and mypy green, disposable PostgreSQL.  
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

- [x] **SD-01 / P0 — Runnable project:** README setup/launch commands, fixture disclaimers, `python -m sidedeck.demo` source-path launch, status/report/reset modes and dashboard instructions are documented.
- [x] **SD-02 / P0 — Deterministic risk policy:** Risk policy enforces the approved universe, cash, 20% position cap, 80% exposure cap, four-position cap, long-only ownership and 1% stop-risk budget with explicit refusal reasons.
- [x] **SD-03 / P0 — Local execution simulator:** Local simulated orders support fees, spread, partial fills, cancellation, restart-safe artifact/journal persistence and causal run/decision/order/fill/journal lineage; no broker transport exists.
- [x] **SD-04 / P0 — Two-agent end-to-end fixture runner:** Both independent fixture workers share three timestamped synthetic bundles and separate $1,000 ledgers with BUY/SELL/HOLD/rejection paths.
- [x] **SD-05 / P0 — Local dashboard & export:** Ignored `results/` contains labelled HTML dashboard, JSON report and CSV export with cash, NAV, P&L, fees, fills, refusals and provenance.
- [x] **SD-06 / P0 — Initial offline MVP acceptance:** 34 local tests pass / 1 PostgreSQL skipped; [final CI 39134181178](https://github.com/smbabalola/sidedeck/actions/runs/39134181178) runs Python 3.12, 35 tests including disposable PostgreSQL, Ruff and mypy (19 source files), all green. This verifies a **minimal local demo**, not complete research integration or production-grade replay.

## IMMEDIATE — finish integration-boundary correctness in one batch (no separate approval gate)

These are source-review findings at verified commit `4a35d4120d3a6653250083906f10808b593e8994`. Fix them alongside the next continuous research-adapter sprint. Do **not** reopen P1 or pause after each one.

- [x] **SD-06H-01 / P0 — Single trusted decision:** `run_validated` returns and audits the exact one-shot envelope; execution is gated by its validation result.
- [x] **SD-06H-02 / P0 — Actual read-only portfolio context:** Each demo request carries ledger-derived cash and holdings at the cutoff.
- [x] **SD-06H-03 / P0 — Post-fill risk invariants:** Risk marks existing positions and projected exposure, includes spread/fees in cash checks, and revalidates ownership, caps and stop budget before simulation.
- [x] **SD-06H-04 / P0 — End-to-end idempotency and recovery:** Journal idempotency and canonical-journal recovery prevent duplicate economic posting after an incomplete artifact write.
- [x] **SD-06H-05 / P1 — Honest dashboard:** Dashboard now includes agent status, final summary, session equity/NAV, positions, exposure, risk decisions and JSON/CSV exports, with fixture/simulation labels.
- [x] **SD-06H-06 / P1 — Calendar and data provenance:** Demo sessions use weekdays; CSV import validates licence confirmation, UTC as-of/publication/ingestion timestamps, stale/future data and weekend rejection.

**Track A:** runnable minimal offline MVP **delivered**. **Track A hardened:** pending SD-06H-01…06; work in parallel with safe SD-07/SD-09 adapter preparation so there is no handoff delay.

## THEN — genuine research integrations without broker execution

- [x] **SD-07 / P1 — Actual TradingAgents adapter preparation:** Code-ready injected `TradingAgentsGraph.propagate` proposal adapter with pinned SHA, strict normalization and no default runtime/network; upstream import/model run remain unverified.
- [ ] **SD-08 / P1 — AI Trading rights gate:** Inspect licence/permission. No vendoring/copying/running upstream source without lawful rights; if unresolved, keep **original independently implemented protocol/worker** distinct and honestly tagged as *not imranpollob upstream*. Disable upstream direct MCP buy/sell, random quotes, scheduled autonomous trades and crypto exposures when eventually authorised. Four internal personas share exactly one $1,000 SideDeck ledger.
- [x] **SD-09 / P1 — Market-data adapter:** Licensed local CSV import boundary validates schema, UTC timestamps, approved USD instruments, stale/future data, weekday calendar and provenance hash.
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
| 2026-10-18 | Integration hardening + SD-07/SD-09 `3d21d80` | [39135593162](https://github.com/smbabalola/sidedeck/actions/runs/39135593162) | 39 CI tests green, Ruff/mypy/PostgreSQL passed; one initial CI packaging omission fixed |
| 2026-10-18 | SD-01–SD-06 offline demo `4a35d412` | [39134181178](https://github.com/smbabalola/sidedeck/actions/runs/39134181178) | Track A minimal offline demo verified: 35 CI tests, Ruff, mypy, disposable PostgreSQL passed |

**Next action:** Keep actual upstream TradingAgents execution credential/provider gated; SD-08/SD-10 and broker tasks remain externally blocked.
