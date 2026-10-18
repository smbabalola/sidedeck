# SideDeck — Living TODO and delivery status

**Repository:** https://github.com/smbabalola/sidedeck  
**Canonical branch:** `feat/p2-agent-adapters` until reviewed and merged.  
**Updated:** 2026-10-18 (user visual demo verified; limited provider tests authorised)  
**Verified integration branch SHA:** `cbee3d03406c250d16574d81df59c37113375cd8`  
**Latest CI evidence:** https://github.com/smbabalola/sidedeck/actions/runs/39135705189 — Python 3.12, 39 passed, Ruff and mypy (21 source files) green, disposable PostgreSQL; three existing warnings.  
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

**Track A:** runnable offline MVP **delivered and hardened** at `cbee3d0`, CI 39 tests passed. This does **not** constitute verification of live third-party AI inference, real data, broker execution, or performance.

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

## Latest verified integration evidence and launch correction

- [x] Integration sprint: `cbee3d03406c250d16574d81df59c37113375cd8`; [GitHub CI 39135705189](https://github.com/smbabalola/sidedeck/actions/runs/39135705189) passed **39 tests** under Python 3.12, Ruff, mypy (21 files), and disposable PostgreSQL. Local report: 38 passed / 1 PostgreSQL skipped. Three SQLite deprecation warnings were reported.
- [x] `docs/INTEGRATION_REPORT.md` and `docs/LICENSING_DECISION.md` present. `src/sidedeck/agents/tradingagents_adapter.py` is **CODE_READY only**, not upstream-import/runtime-verified.
- [ ] **External Gate A:** Authorise/configure a chosen supported LLM provider locally, establish maximum spend and data privacy/network policy before genuine TradingAgents calls. Credential-free offline tests are not a real-model test.
- [ ] **External Gate B:** Obtain affirmative rights/licensing clarity for `imranpollob/ai-trading` before copying or running original upstream source. An independent SideDeck protocol worker may continue separately without claiming it is the upstream project.
- [ ] **External Gate C:** Approve authenticated **eToro Demo only** access and scope before calls or orders; ensure broker fills reconcile to isolated SideDeck virtual portfolios.
- [ ] **SD-07F / Minor UX/documentation:** The reported `python -m sidedeck.demo --reset` command does not exist in the inspected `argparse` CLI. Use `python -m sidedeck.demo reset-fixture` then `python -m sidedeck.demo run`. Keep README and reports accurate or add a tested alias intentionally. Reset is destructive to the chosen fixture results folder; never target user data.
- [ ] **SD-07G / Deferred nonblocking robustness:** `reset_fixture` currently allows deleting any existing directory named `results`; tighten to an explicit project-owned marker, preserving legacy default fixture flow. Do not treat the current offline demo as production hardened.
- [ ] **SD-10:** Upstream TradingAgents smoke verification, AI Trading rights clearance, observed data and representative forward sessions are not complete, despite all green CI tests.

## Real LLM verification sprint — authorised and awaiting local execution

- [x] **User visual acceptance:** Owner successfully ran `python -m sidedeck.demo run` and opened `results/dashboard.html` in PowerShell on 2026-10-18. Synthetic AAPL/MSFT trades, simulated portfolio summaries, an oversell rejection, and HOLD visibly appeared. **This is fixture acceptance only.**
- [x] **Private provider configuration reported:** User has Ollama, NVIDIA and OpenAI provider credentials/settings in a local ignored `.env`; not checked into this GitHub repository. Only `.env.example` placeholders are tracked. Never disclose or commit values.
- [x] **Scoped user authorisation:** Small local **model-only** smoke-test calls using existing local provider configuration, favour no-cost local Ollama / eligible NVIDIA allowance before any OpenAI paid usage. No unrestricted billing, no market-data scraping, no broker APIs. A local code agent must check availability, model and allowance without printing keys.
- [ ] **SD-10A / Immediate:** Follow `docs/REAL_AGENT_SMOKE_TEST.md`: preflight local provider setup and support explicit opt-in model smoke CLI. Mark provider test versus genuine TradingAgents graph test independently. Offline CI must stay network-free.
- [ ] **SD-10B / Immediate:** Safely install/verify the pinned licensed TradingAgents runtime in an isolated environment, validate adapter mapping and execute one limited real-model call **only when** provider and data/network constraints can be enforced. Test with synthetic/controlled context, not actual orders. Persist masked cost/time/result evidence.
- [ ] **SD-10C / UX:** User visual acceptance shows an unstyled plain HTML table, not final UI. Add a presentable comparison dashboard when safe without delaying model verification. No need to repeat completed fixture demo.
- [ ] **SD-10D / Security:** Check repository history and CI logs for accidental secret inclusion using safe redacted detection and owner notification if found. Never echo potential secret values. Current remote `.env` absent and `.gitignore` ignores it; a historical scan is a separate check.

**Next action:** Codex in the local Windows workspace executes the new smoke-test runbook, uses local ignored `.env` only, tests with explicit low-cost bounds and updates this TODO with evidence. Actual eToro use and unlicensed `imranpollob/ai-trading` source remain blocked.

## Active blockers and mitigations

1. **AI Trading copyright:** Upstream `imranpollob/ai-trading` shows no root licence; do not reuse source without permission. Safe independent protocol/fixture work may proceed.
2. **Model credentials / AI cost:** Owner reports Ollama/NVIDIA/OpenAI configuration in local ignored `.env` and authorises small local smoke tests. Availability, safe provider policy, free allowance and actual model inference remain unverified. **Do not send keys to GitHub or chat.**
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
| 2026-10-18 | Final integration report `cbee3d0` | [39135705189](https://github.com/smbabalola/sidedeck/actions/runs/39135705189) | Independently verified 39 green tests + PostgreSQL; genuine upstream agent runs and eToro gated |
| 2026-10-18 | SD-01–SD-06 offline demo `4a35d412` | [39134181178](https://github.com/smbabalola/sidedeck/actions/runs/39134181178) | Track A minimal offline demo verified: 35 CI tests, Ruff, mypy, disposable PostgreSQL passed |

**Next action:** Owner-approved model provider/access and point-in-time market-data policy are needed for an actual TradingAgents smoke test; AI Trading upstream remains blocked until licence/rights are clarified. Continue only independent safe work without permissions. Use the canonical CLI `python -m sidedeck.demo run` (and `reset-fixture` as a separate command), **not** the unsupported `--reset` flag. Leave broker calls disabled until explicit Demo-only approval. Draft PR #1 auto-tracks branch commits and must remain draft/unmerged.
