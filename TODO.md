# SideDeck — Living TODO and delivery status

**Repository:** https://github.com/smbabalola/sidedeck  
**Canonical branch:** `feat/p2-agent-adapters` until reviewed and merged.  
**Updated:** 2026-10-18 (SD-12A SideDeck-managed Alpaca PAPER read-only adapter complete; live account unverified)
**Verified code SHA:** `ff27ab168f6b4bfbbf8183e8bad5588a6bb069cd` (Alpaca PAPER read-only groundwork)
**Latest code CI evidence:** https://github.com/smbabalola/sidedeck/actions/runs/39155948631 and https://github.com/smbabalola/sidedeck/actions/runs/39155944560 — Python 3.12, **130 passed**, 3 known SQLite warnings, Ruff passed, mypy passed for 28 source files, disposable PostgreSQL CI environment.
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
- [x] **SD-10A / Immediate:** Followed `docs/REAL_AGENT_SMOKE_TEST.md`; added explicit opt-in smoke CLI, provider preflight and separate provider/graph status. One Ollama request was run with synthetic context; offline CI remains network-free. Local: 41 passed / 1 PostgreSQL skipped; CI: 42 passed.
- [ ] **SD-10B / Immediate:** **PARTIALLY COMPLETE / DATA-ISOLATION BLOCKED:** rating contract fixed; exact graph import verified in a disposable Python 3.12 environment after targeted dependency repair; one minimal graph invocation attempted but stopped when upstream `curl_cffi` tried `fc.yahoo.com`. `UPSTREAM_GRAPH_RUN_VERIFIED=false`, `DATA_ISOLATION_VERIFIED=false`; no rating or order claimed.
- [ ] **SD-10C / UX:** User visual acceptance shows an unstyled plain HTML table, not final UI. Add a presentable comparison dashboard when safe without delaying model verification. No need to repeat completed fixture demo.
- [ ] **SD-10D / Security:** Check repository history and CI logs for accidental secret inclusion using safe redacted detection and owner notification if found. Never echo potential secret values. Current remote `.env` absent and `.gitignore` ignores it; a historical scan is a separate check.

**Next action:** Resolve the disposable TradingAgents runtime installation/data-isolation blocker before claiming an upstream graph run. Provider-only Ollama evidence is complete. Actual eToro use and unlicensed `imranpollob/ai-trading` source remain blocked.

## Priority integration defect — pinned upstream graph (2026-10-18)

- [x] **Source compatibility inspected:** At pinned `TauricResearch/TradingAgents@e8f5503...`, `TradingAgentsGraph.propagate(...)` returns `(final_state, five-tier rating string or REVIEW)`, **not** a structured trade dictionary. This is verified from upstream `tradingagents/graph/trading_graph.py` and `tradingagents/agents/rating.py`.
- [x] **SD-10B-1 / Critical:** Adapter accepts Buy/Overweight/Hold/Underweight/Sell/REVIEW, preserves `upstream_rating`, requires final-state provenance, and never synthesizes executable order fields. Tests cover all ratings, malformed signals and missing state.
- [x] **SD-10B-2 / Critical:** Disposable Python 3.12 source/runtime environment established; the initial full dependency transaction stalled during package installation, targeted graph wheels were installed, and exact `TradingAgentsGraph` import succeeded. No paid model call was used for import verification.
- [ ] **SD-10B-3 / Critical:** **BLOCKED:** the graph's Yahoo `curl_cffi` path attempted `fc.yahoo.com` despite a Python socket guard. A stronger upstream data boundary or an isolated local vendor injection is required before another graph call.
- [ ] **SD-10B-4 / P1:** **BLOCKED by SD-10B-3:** one bounded minimal graph invocation was attempted and stopped before a rating; provider-only Ollama smoke was not repeated.
- [ ] **SD-10B-5 / P1:** Update `docs/INTEGRATION_REPORT.md` and `TODO.md` with exact evidence and CI. See **`docs/REAL_AGENT_SMOKE_TEST.md`, section "Next focused task"**. Push normal commits; no merge or credentials.
- [x] **SD-10B-6 / Security:** Evidence distinguishes `UPSTREAM_IMPORT_VERIFIED=true`, `UPSTREAM_GRAPH_INVOKED=true`, `UPSTREAM_GRAPH_RUN_VERIFIED=false`, `DATA_ISOLATION_VERIFIED=false`, prior `PROVIDER_INFERENCE_VERIFIED=true`, and `EXECUTABLE_PROPOSAL_VALIDATED=false`. Zero trade/account mutations occurred.

**Next action for Codex:** Read the updated smoke-test runbook and execute SD-10B-1…6 continuously, preserving untracked/ignored local work; stop only at actual unsafe external data or permission gates.

## SD-10C — Native-network isolation and real graph recovery (2026-10-18)

- [x] **Last independently verified SD-10B baseline:** commit `727fd2924c490feace0c76f7ebf1b88ec5395ad7`; [CI 39140134851](https://github.com/smbabalola/sidedeck/actions/runs/39140134851) succeeded with 50 tests, Ruff/mypy and disposable PostgreSQL. User-reported 49 local passes, 1 local PostgreSQL skip, 3 known SQLite warnings.
- [x] Exact upstream `TradingAgentsGraph` import verified in disposable Python 3.12, five-level rating adapter fixed. Full graph did **not** finish, due to Yahoo `curl_cffi` native-network attempt; Python-only socket guard was insufficient. No accepted graph rating or trade.
- [x] **Source-level route identified:** `TradingAgentsGraph.resolve_instrument_context` calls Yahoo-backed `resolve_instrument_identity` before graph execution, and the market analyst's compiled `ToolNode` binds `get_stock_data`, `get_indicators` and `get_verified_market_snapshot` routed to vendors; memory and other routes require independent review.
- [ ] **SD-10C-1 / Critical:** Build strict synthetic identity/market tool fixture interface, injected **before upstream graph construction**, deny all unspecified tools/symbols/as-of timestamps; never permit live Yahoo fallback.
- [ ] **SD-10C-2 / Critical:** Prove **OS-level** default-deny native network egress, covering `curl_cffi`/DNS/subprocesses; local Ollama access must be separately allowlisted or mediated. Do not alter user's general Windows firewall/services without approval. If isolation unavailable, skip actual Ollama graph and mark `OS_EGRESS_BOUNDARY_BLOCKED`.
- [ ] **SD-10C-3 / P1:** After both gates pass, invoke **one** real pinned-upstream Ollama graph with bounded tokens/time and controlled fixture data, capture actual final rating/REVIEW, no executable order/ledger changes. If blocked, run a truly offline compiled upstream graph with deterministic model stubs and label it **stubbed**, not real-LLM graph proof.
- [ ] **SD-10C-4 / P1:** Test native-deny and compiled-tool binding, CI and redacted evidence; update `TODO.md`/`docs/INTEGRATION_REPORT.md` after execution, push normal commits. Full runbook: [`docs/DATA_ISOLATION_RECOVERY.md`](docs/DATA_ISOLATION_RECOVERY.md).

**Next action:** Codex performs SD-10C-1 through SD-10C-4 **continuously** with no repeat of completed provider/rating tests. No unauthorised market-data provider requests, no paid models, no eToro.

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
| 2026-10-18 | Guarded local model smoke `3059971` | [39138613194](https://github.com/smbabalola/sidedeck/actions/runs/39138613194) | One local Ollama provider-only inference accepted by SideDeck proposal validation; 42 CI tests green; upstream graph remains unverified |
| 2026-10-18 | SD-10B rating/isolation gate `12ae6ea` | [39140051347](https://github.com/smbabalola/sidedeck/actions/runs/39140051347) | Five-level rating contract fixed; exact graph import verified; one graph attempt stopped at Yahoo `curl_cffi` egress; 50 CI tests green |
| 2026-10-18 | SD-01–SD-06 offline demo `4a35d412` | [39134181178](https://github.com/smbabalola/sidedeck/actions/runs/39134181178) | Track A minimal offline demo verified: 35 CI tests, Ruff, mypy, disposable PostgreSQL passed |

**Next action:** SD-10B import and rating contract are complete. Follow `docs/DATA_ISOLATION_RECOVERY.md` for synthetic-data injection and native egress containment before another real graph run. Use the canonical CLI `python -m sidedeck.demo run` (and `reset-fixture` as a separate command), **not** the unsupported `--reset` flag. Leave broker calls disabled until explicit Demo-only approval. Draft PR #1 remains draft/unmerged.

## SD-10C execution evidence (2026-10-18)

- [x] **SD-10C-1:** Added `SyntheticResearchBoundary` and deterministic `OfflineTradingAgentsGraph`. The approved tool set is identity, OHLCV, indicators and verified AAPL/USD snapshot at `2026-01-05T21:00:00Z`; unknown tool, ticker, date, source and invalid lookback requests fail closed. Values are labelled `FIXTURE / NOT LIVE MARKET DATA`.
- [ ] **SD-10C-2:** **BLOCKED — `OS_EGRESS_BOUNDARY_BLOCKED`.** Docker is installed but its Linux daemon is unavailable. WSL is installed but is not an already-provisioned default-deny namespace with an allowlisted Ollama mediation. No Windows firewall/service changes were made. Native `curl_cffi`, DNS and subprocess containment therefore remains unverified.
- [x] **SD-10C-3 safe fallback:** Ran the fully offline deterministic graph-shaped test twice; it returned `Hold` with identical fixture provenance and zero model/broker/order/ledger mutations. The actual pinned Ollama graph was not attempted after the native isolation gate failed. `UPSTREAM_IMPORT_VERIFIED=true` remains the prior disposable-runtime import evidence; `UPSTREAM_GRAPH_RUN_VERIFIED=false`.
- [x] **SD-10C-4:** Added regression coverage for deterministic replay, provenance, compiled-tool allowlisting, unknown-tool fail-closed behaviour and mandatory native-isolation policy. Full test, Ruff, mypy, SQLite migration and disposable PostgreSQL CI evidence is recorded with the completion commit below.

**Remaining blocker:** A disposable OS-level default-deny runtime covering native `curl_cffi`/DNS/subprocesses and a separately allowlisted loopback Ollama path. Provisioning it requires external/privileged environment support; the user's system firewall was intentionally left unchanged.

**SD-10C verification commit:** `8c4566d24d00a7045701202d22703a7f5a3171ae`; local `pytest`: 59 passed, 1 skipped, 3 warnings; Ruff passed; mypy passed (23 source files); SQLite Alembic upgrade passed. GitHub Actions: [run 39140855365](https://github.com/smbabalola/sidedeck/actions/runs/39140855365) — Python 3.12, pytest/Ruff/mypy passed; CI PostgreSQL container initialized and no existing user database was contacted.


## SD-11A — next continuous sprint: read-only eToro historical-data feasibility

**Decision:** Stop devoting the immediate sprint to Yahoo access, Windows firewall changes, or unblocking the *live upstream graph* through Yahoo. Pursue a SideDeck-controlled historical-data adapter, preferring eToro as instrument/feed source **if verified**. The native-eject / upstream-tool network-safety blocker is retained separately; data-source substitution does not resolve it.

- [x] **Final SD-10C close-out:** Branch commit `4e02c4f6a4ca8ecff8aa40aeddfb163edad99586` checked remotely. [Final GitHub Actions 39140923450](https://github.com/smbabalola/sidedeck/actions/runs/39140923450) succeeded; preceding [39140855365](https://github.com/smbabalola/sidedeck/actions/runs/39140855365) succeeded. Codex reports local **59 passed / 1 skipped / 3 warnings**; native OS isolation still BLOCKED and no actual Ollama graph run occurred.
- [x] **eToro API research:** Official eToro Market Data site confirms current rates, OHLC historical candles and historical closing prices; per-account/asset depth unverified. Independent live-tested clients report at most **1,000 candles per interval**, so eToro's OneDay bars may only cover about **four years**. **Five years of daily OHLCV remains UNVERIFIED; weekly candles do not meet the requirement.**
- [ ] **SD-11A-1:** Verify official search/candle/closing-price schemas, current eligibility, limits and rights. Create an independently testable SideDeck-owned market-data GET-only adapter with injected transport and **no broker methods**.
- [ ] **SD-11A-2:** Provide a fixture-based scanner for per-instrument five-year daily history: `AAPL`, `MSFT`, `SPY`, `QQQ`, count/date range, gaps, incomplete bars, validity, currency and adjustment treatment. Test max 1000 daily bar response, no pagination and failure cases.
- [ ] **SD-11A-3:** Determine whether the historical closing-price endpoint can provide older daily closes; if not, select a licensing-compatible 5-year daily OHLCV source/import for the older missing data, with eToro for ongoing updates if allowed. No fabricated daily bars or conversion from weekly to daily.
- [ ] **SD-11A-4:** Normalize approved data into immutable `MarketBundle` records and controlled research tools; disable Yahoo fallback in SideDeck. An upstream TradingAgents graph **must still have a separate native network egress guard**; prices alone don't prevent its independent Yahoo/SEC/news requests.
- [ ] **SD-11A-5:** Run offline pytest/Ruff/mypy, disposable PostgreSQL CI, preserve all local secrets; update docs and TODO in implementation commits. Draft PR remains draft/unmerged.
- [ ] **SD-11A-6 / owner action when ready:** Prepare an explicit opt-in **read-only eToro market-data API** smoke command. **Do not run authenticated eToro requests or load its API credentials without fresh owner approval**; no Demo or Real order endpoints.

**Working plan:** [`docs/ETORO_HISTORICAL_DATA.md`](docs/ETORO_HISTORICAL_DATA.md). Execute SD-11A code-only research/tests in one continuous pass without further minor reviews. Focus on genuine five-year daily data, not a superficially passing stub.

## SD-11A eToro historical-data adapter (2026-10-18)

- [x] **Read-only client:** Added `EtoroHistoricalDataClient` with injected transport, fixed official host, explicit `market-data-read` capability, deterministic approved-instrument resolution, no order methods/imports, bounded 429 retry and redacted status errors. No eToro credentials or authenticated requests were used.
- [x] **Coverage scanner:** Added typed daily-candle validation and five-year report statuses. Requests clamp at 1,000 candles; incomplete/future/malformed/duplicate data and OHLCV violations fail closed. No missing sessions are fabricated.
- [x] **Probe/fallback:** Added an explicit three-flag `sidedeck.data_probe` command that cannot start without owner confirmation and both eToro key names. Existing licensed CSV import is the prepared fallback; Yahoo is not a fallback.
- [ ] **Coverage gate — UNVERIFIED:** Official docs confirm market-data search/candles/historical-closing-price surfaces, but owner-specific earliest date, five-year daily depth, volume quality, adjustments and storage rights require an authorised read-only GET. Do not run the probe until that approval is provided.
- [x] **Offline evidence:** `pytest` 68 passed / 1 skipped / 3 warnings; Ruff passed; mypy passed for 25 source files; SQLite Alembic upgrade passed. No network calls were made by tests.

**Next action:** obtain explicit owner approval for a read-only eToro market-data GET with permitted credentials/environment, then run one bounded coverage probe for AAPL/MSFT/SPY/QQQ. Until then, remain on the offline adapter and licensed CSV fallback; preserve TradingAgents native-network safety restrictions.


## SD-11A independent acceptance — code foundation verified, live coverage still unverified

- [x] **Verified pushed feature commit** `a7e678a3a6b43f15d4c17bc01d2a51200b6ef0de`, [CI 39141855089](https://github.com/smbabalola/sidedeck/actions/runs/39141855089) and [CI 39141852093](https://github.com/smbabalola/sidedeck/actions/runs/39141852093) both passed. Owner-reported local 68 passed, 1 PostgreSQL skipped, 3 existing warnings; Ruff/mypy/SQLite passed. Draft PR #1 remains unmerged.
- [x] **SD-11A code only:** Market-data-only injected client, approved universe, synthetic coverage scanner and explicit owner-confirmation CLI exist; no authenticated eToro read occurred, so actual daily depth and trading data correctness remain **UNVERIFIED**.
- [x] **SD-11B-1 / Must fix before any real probe:** Official eToro instrument guide specifies `internalSymbolFull=AAPL`, exact match on `internalSymbolFull` and a verified instrument ID. Current code requests `search=AAPL` and defaults critical instrument attributes. Normalise verified live response/metadata, reject ambiguous symbols, CFDs and unverified classification.
- [x] **SD-11B-2 / Must fix:** Published candle payload nests `candles` by instrument and timestamps rows using `fromDate`; current flat parser expects `timestamp|date|time`. Check nested group instrument IDs and support documented zero volume without inventing it.
- [x] **SD-11B-3 / Must fix:** Current `sidedeck.data_probe` prints only the AAPL instrument resolution. It does **not request or scan history**, so no authenticated five-year test would answer the goal. Implement offline-dry-run and bounded four-symbol history scanner, redacted output.
- [x] **SD-11B-4 / Must fix:** `urllib.urlopen` throws `HTTPError` on 429, so current client retries do not work through the real transport. Correct status normalization, documented bounded Retry-After, safe GET URL allowlist and same-host redirect policy.
- [x] **SD-11B-5 / Must fix:** A single max-1000 OneDay candle response **cannot** prove five years of approx 1,250 daily sessions; use accurate exchange-calendar coverage, leap-safe five-year periods, gaps/holidays and actual supported historical pagination or a legitimate second source. Do not fabricate data or treat weekly candles as daily.
- [x] **SD-11B-6 / Required acceptance:** Full offline schema-fixture tests (including published examples), pytest/Ruff/mypy/PostgreSQL and README/docs. Keep live calls and key use disabled until the owner separately approves only eToro `/market-data/` GET and local secrets. **Actual account-specific depth remains unverified** until that bounded check.

**One-pass coding brief:** [`docs/ETORO_API_FIXES.md`](docs/ETORO_API_FIXES.md). Complete SD-11B code fixes without routine review pauses. No further Yahoo/OS firewall work, no paid LLM, no orders/eToro broker access.

## SD-11B completion (2026-10-18)

- [x] **SD-11B-1:** Corrected instrument search to `internalSymbolFull`, require exact symbol match, verified internal instrument ID, asset type, currency and classification metadata; ambiguous, CFD-like and incomplete results fail closed.
- [x] **SD-11B-2:** Corrected published nested candle groups and `fromDate` parsing, matched group instrument IDs, accepted documented zero volume without inference, bounded response bodies, blocked redirects/arbitrary paths, and normalized `HTTPError` status responses.
- [x] **SD-11B-3:** `sidedeck.data_probe --provider etoro --dry-run` now scans all four approved instruments and emits redacted coverage reports. Live mode remains gated by explicit owner confirmation and both local key names; it was not run.
- [x] **SD-11B-4:** No unsupported closing-price stitching was added. Existing licensed CSV import remains the explicit fallback; Yahoo is not used or silently substituted.
- [x] **SD-11B-5:** Coverage uses leap-safe five-year periods and an explicit exchange-session set. Weekdays are not treated as a market calendar; one 1,000-bar response cannot pass the five-year gate.
- [x] **SD-11B-6:** Offline tests cover published samples, nested/cross-instrument payloads, zero volume, malformed/future/incomplete candles, 401/403/429 handling, redirects/path safety, leap years and four-symbol dry run. Local: 73 passed, 1 skipped, 3 warnings; Ruff, mypy (25 files) and SQLite Alembic passed. No authenticated request or credential load occurred.

**SD-11B status:** `CODE_READY`; read-only coverage probe is ready for owner approval, but actual account-specific five-year coverage remains `LIVE_COVERAGE_UNVERIFIED`.

## SD-11B independent review and live-probe cutoff correction (2026-10-18)

- [x] Independently verified Codex's SD-11B commit `01377cb010b1cb39fcfff6e2de63353a63ac66f0` and [GitHub CI 39142661967](https://github.com/smbabalola/sidedeck/actions/runs/39142661967): **74 passed**, Ruff/mypy/disposable PostgreSQL green. Local author report: 73 passed, 1 PostgreSQL skipped, 3 known warnings.
- [x] Source review found a **live-only correctness defect** after the green CI: `sidedeck.data_probe` continued using an old fixed **2026-01-06** cutoff and a fake **single-day 2026-01-05 exchange calendar** for real account requests. This would reject current genuine candles and falsely imply historical coverage had been checked. Updated live mode to use a dynamically computed cutoff through the **previous UTC day** (conservatively excluding currently forming daily bars) and pass **no invented calendar**. Dry-run's dated fixture remains unchanged.
- [x] Tightened exact GET history path syntax, checked nested row instrument IDs, and made history scan return **INSUFFICIENT_DEPTH** when the earliest received observation is demonstrably newer than the five-year target; otherwise it remains **UNVERIFIED** until an actual verified exchange-session calendar is supplied. No five-year pass is fabricated from a single 1,000-bar response.
- [x] Added offline regressions for actual live-cutoff calculation, untrusted GET paths, absence of invented exchange sessions, recent/old history status, and cross-instrument values. Code HEAD `0da1ef47f943643fd792285d3f8136bbc287344f` passed [CI 39143425931](https://github.com/smbabalola/sidedeck/actions/runs/39143425931) and [CI 39143421549](https://github.com/smbabalola/sidedeck/actions/runs/39143421549): **78 tests passed**, 3 known warnings, Ruff and mypy (25 source files) green, disposable PostgreSQL.
- [ ] **Only remaining market-data permission gate:** owner-approved **read-only eToro `/market-data/` GET** using locally held `ETORO_API_KEY` and `ETORO_USER_KEY`, with max four approved instruments and bounded calls. No credentials have been read or transmitted in this review; no authenticated eToro request has occurred. The real-data depth, adjustment quality and licence/storage rights remain unverified.
- [ ] **Separate unchanged external gates:** upstream TradingAgents native-network isolation and graph completion; original AI Trading framework licensing; eToro Demo broker access/real forward research. Do **not** interpret read-only market data as trading permission.

**Owner decision needed next:** Approve one bounded read-only eToro market-data coverage test, or continue using exclusively offline fixture/licensed CSV inputs. Do not ask to re-run completed SD-11B implementation.

## SD-11C — owner-approved one-time market-data coverage read (2026-10-18)

- [x] **Owner authorisation received in this conversation:** One **bounded read-only eToro market-data GET coverage test** for exactly **AAPL, MSFT, SPY and QQQ** using only the owner's *locally held* `ETORO_API_KEY` and `ETORO_USER_KEY`. Authorised requests are the four exact symbol search GETs and at most one 1,000-OneDay-candle GET per validated instrument, plus the existing at-most-one bounded 429 retry per GET. This includes local credential use solely for the scoped test, not disclosure or repository upload.
- [ ] **SD-11C-1 / local execution:** Codex on the owner's Windows computer checks that locally provisioned eToro credentials exist without printing or committing their values, synchronises the branch **without deleting any local work**, and runs `$env:PYTHONPATH="src"; .\.venv\Scripts\python.exe -m sidedeck.data_probe --provider etoro --market-data-only --allow-read-network --confirm-owner-read-only` **once**. No model/graph runtime; no other URLs or account/positions/orders endpoints; no Demo/Real orders. No scripted recurring repeats.
- [ ] **SD-11C-2 / validation:** Capture *only safe metadata* for each of AAPL/MSFT/SPY/QQQ: whether the search resolves correctly, historical returned candle count, earliest/latest completed daily timestamps, error type/status if blocked, and five-year daily verdict. Check response-type, currency, missing volume/adjustment evidence and whether weekly or historical close must remain separate. If API response differs, stop additional live requests; correct schema offline with redacted examples, then obtain renewed consent before any further network test.
- [ ] **SD-11C-3 / reporting:** Mark the actual evidence `LIVE_READ_ONLY_VERIFIED` or `BLOCKED` per instrument; never claim five-year coverage from a max-1,000-row response. The current live probe cannot yield `PASS_5Y_DAILY` without a separately verified exchange calendar; `UNVERIFIED` or `INSUFFICIENT_DEPTH` are legitimate outcomes. Avoid printing raw API response, full URL/query with secrets, account identity, headers, local `.env` or tokens. Update `docs/INTEGRATION_REPORT.md` and this living TODO, run CI if code changes, commit and push safe **documentation/evidence only**.
- [ ] **Genuine blocker if credentials absent:** This chat/GitHub cannot read the user's local `.env`. If `ETORO_API_KEY` / `ETORO_USER_KEY` are not configured on the Windows machine, mark `LOCAL_ETORO_KEYS_MISSING` and ask owner to provision them **locally**; do not request key values in chat, dump environment variables or invent results.
- [ ] **Other external gates unchanged:** native network-safe **TradingAgents graph** run, unlicensed original AI Trading source, eToro Demo order access and real-money routes are *not approved* by this market-data authorisation.

**Authorised scope:** one-time locally executed GET-only probe, **not** a persistent entitlement for future pulls, autonomous monitors, broker actions or personal account data. No keys or network request have been used through GitHub by this assistant. Draft PR #1 remains open and unmerged.

## SD-11C live probe evidence (2026-10-18)

- [x] **One authorized execution:** The existing live command was run exactly once with locally loaded ignored `ETORO_API_KEY` and `ETORO_USER_KEY`; values were not printed, logged, staged or uploaded. The process was limited to the market-data client and the four approved symbols.
- [x] **Safe stop:** AAPL instrument search returned HTTP `403` and the client raised `EtoroAccessBlocked`. The fail-closed behavior stopped the run before any candle GET and before MSFT, SPY or QQQ search requests.
- [x] **Per-instrument result:** AAPL — search blocked with HTTP 403, 0 candles retrieved, earliest/latest unavailable, **five-year daily depth UNKNOWN (not tested)**. MSFT, SPY and QQQ — not attempted due to fail-closed stop, five-year daily depth UNKNOWN. **A 403 is an access/permission failure, not evidence that historical data is unavailable.**
- [ ] **Coverage status:** `BLOCKED` / `LOCAL_ETORO_MARKET_DATA_403`; account-specific daily depth, dates, adjustments, volume and five-year availability remain unverified. No retry or second live run was made.

**Required owner follow-up:** verify that the locally provisioned keys are entitled to the official `/market-data/` search endpoint, then provide fresh approval before any subsequent bounded read-only attempt. No account, portfolio, balance, position, order, Demo or Real endpoint was accessed.

## SD-11D — eToro 403 authorisation investigation (read-only; no API retry approved)

- [x] **Independently verified** commit `94f8dbd7b772f50a93147464d48f59a9c400fd86` is remote branch head at review and [CI 39144154129](https://github.com/smbabalola/sidedeck/actions/runs/39144154129) succeeded. The initial approved probe was **consumed exactly once**: AAPL search GET returned HTTP 403; no subsequent instrument searches or any candle GET occurred. No credentials were printed or uploaded.
- [x] **Interpretation corrected:** 403 indicates endpoint access denied, **not** that AAPL five-year coverage is unavailable. Status is `LOCAL_ETORO_MARKET_DATA_403 / ACCESS_BLOCKED`; actual depth for AAPL/MSFT/SPY/QQQ remains UNKNOWN.
- [ ] **Owner UI-only verification (no API requests):** On eToro API Portal `https://api-portal.etoro.com`, review the current API key pair's environment, **read permission/scope for market-data/search**, expiration/revocation and any IP whitelist. Official documentation: `https://builders.etoro.com/learn/authentication-and-api-keys`, `https://api-portal.etoro.com/getting-started/authentication`. Avoid changing keys or scope as a blind troubleshooting step, and **never paste the values into chat/Codex output/GitHub**.
- [ ] **If permissions appear correct:** Seek eToro developer support confirmation that this key/account has authorised `GET /api/v1/market-data/search?internalSymbolFull=AAPL` access in the chosen environment. Share safe endpoint name, HTTP 403 and UTC time only; never share key values or raw headers. IP whitelist / account eligibility or entitlement may also explain access denial. No automatic retry.
- [ ] **Next fresh authorisation:** Only after the eToro account permissions are confirmed should a second scoped market-data-only GET be proposed, and only with fresh owner approval. No account/position/order endpoints, no Demo or Real execution.
- [ ] **Nonblocking parallel work:** Continue SideDeck's existing **licensed local CSV** historical-data import and offline fixtures, checking five-year daily dates, corporate-action adjustments, rights, volume integrity and as-of timestamps; do not silently substitute Yahoo, claim five years from a single 1000-bar response or assert real performance. Find an additional legitimate 5-year daily OHLCV provider only after reviewing cost/licensing.
- [ ] **Other outstanding releases:** Genuine pinned TradingAgents graph execution still requires a network containment decision; upstream AI Trading source rights unresolved; no eToro Demo trading authorisation given.

**Next action:** owner checks eToro API Portal access settings without issuing another GET; Codex must not rerun the exhausted authorisation. Work on licensing-compatible CSV import/analysis can proceed without waiting on eToro support.


## SD-11D — credential-format and portal-permission check (2026-10-18)

- [x] **Owner's eToro settings screenshot:** The currently viewed `signaldeckdemokey` entry is under **Main** account, has **Market Data → Read** enabled, no IP allowlisting configured and no expiration entered. `Trading — Real → Write` was not selected in the displayed permissions. **This is UI evidence only; it does not prove the local key pair belongs to that entry or is entitled to the endpoint.**
- [x] **Codex local no-network configuration review:** Ignored `.env` exists and has exactly one `ETORO_API_KEY` and `ETORO_USER_KEY`; each nonempty, printable ASCII, unquoted, no internal/edge whitespace and mutually distinct. No values, hashes or secrets were displayed, uploaded or logged. The previous live attempt expressly loaded these variables from `.env`; PowerShell does not automatically inject them into its environment.
- [x] **Clarify local environment flag:** `ETORO_ENVIRONMENT` is classified locally as demo/test; the current SideDeck `src/sidedeck/data_probe.py` **does not read this variable**, uses the same official market-data host regardless of it, and only supplies the API key/user key/request UUID to `/market-data/search`. **The local environment label alone did not cause the 403.** The **eToro account / key issuance environment** must still be checked independently; key display name is not sufficient evidence.
- [ ] **Most useful offline next check:** Confirm in the portal UI which actual Public API Key and User Key were originally obtained for this precise active key/account pairing, without exposing either value. An older/mismatched user key cannot be ruled out merely by nonempty formatting. Do not issue new keys or make additional authenticated requests blindly.
- [ ] **eToro support escalation if key pairing is confirmed:** Ask eToro to verify the market-data search endpoint entitlement for this Main-account key despite `Market Data → Read` selected and no IP/expiry restrictions. Include sanitized endpoint and prior HTTP 403, never API values, headers or raw body.
- [ ] **Permission gate:** Previous one-shot market-data read authorisation was consumed; **no new authenticated eToro calls** until key/account issue is resolved and owner separately re-approves. No broker/portfolio/order access is authorised.

**Primary source:** eToro public API auth docs specify `x-api-key` (application), `x-user-key` (user) and `x-request-id` UUID; eToro also classifies 403 as forbidden by scope and requires matching account/environment. See `https://builders.etoro.com/learn/authentication-and-api-keys` and `https://api-portal.etoro.com/getting-started/authentication`.


## SD-11E — eToro support and historical-data alternative (2026-10-18)

- [x] **Source research:** eToro official support ticket route https://www.etoro.com/customer-service/ and developer community https://builders.etoro.com/community confirmed. An account-authenticated ticket cannot be submitted from GitHub/chat; draft details are ready for user to paste without keys. For tracing, user may privately supply a request UUID to eToro support if available.
- [x] **eToro blocker unchanged:** One approved `/market-data/search` GET returned HTTP 403 despite a key reported active with Market Data — Read; both local credentials reportedly came from same key setup, valid nonempty formatting. Do not repeat without separate permission; no five-year eToro data verdict.
- [x] **Alternative researched:** Tiingo EOD free individual plan advertises 30+ years of available price history and raw/adjusted OHLCV plus dividends/splits; internal personal use only, no redistribution. Individual AAPL/MSFT/SPY/QQQ coverage and personal research entitlement still need to be verified by a future authorised local test. Sources and developer brief: `docs/HISTORICAL_DATA_ALTERNATIVE.md`.
- [x] **New code:** Added **offline-only** `sidedeck.domain.tiingo_eod` parser with approval flag, typed/Decimal raw & adjusted EOD records, validated dates, corporate actions, a provenance digest and verified-session five-year coverage assessment. Data remains `point_in_time_verified=false` even when date coverage passes. No transport/token/access to eToro or Tiingo; no actual historical data and no claim of backtest success.
- [ ] **SD-11E-1:** Inspect raw/adjusted field consistency, collection timestamp vintage, corporate-action corrections, 5-year dates/holidays and licensing with provider/owner. Implement private, licence-respecting raw-data storage and converter for user-supplied licensed EOD CSV/JSON. Existing `market_import.py` accepts **one snapshot/instrument**, not a five-year series; avoid misusing it.
- [ ] **SD-11E-2:** Add deterministic historical replay with past-only market bundles, walk-forward splits, risk controls, transaction costs, SPY/cash benchmarks and no performance claim from fixture prices.
- [ ] **SD-11E-3 / owner gate:** Create a separate **Tiingo personal account** if suitable and confirm terms before provisioning any token locally; a Tiingo live GET requires **fresh explicit permission**. No API calls or credential use are approved by this docs/code sprint.
- [ ] **SD-11E-4:** Full real licensed five-year daily EOD verification for AAPL/MSFT/SPY/QQQ, publication availability and store/use rights required before genuine market backtests. Keep TradingAgents actual graph isolation and AI Trading licensing as separate pending gates.

**Verified code milestone:** `cab8dc6c5b020f30cd19681dd25596b05fd08451`; [GitHub CI 39150920040](https://github.com/smbabalola/sidedeck/actions/runs/39150920040) — Python 3.12, **95 passed**, three existing SQLite warnings, Ruff passed, mypy passed for 26 files and disposable PostgreSQL initialized. Offline Tiingo payload parser is checked in; **zero actual Tiingo observations** and no live network/credential requests.

**Next action:** Submit the prepared support request through eToro's signed-in customer-service centre; separately continue licence-aware, offline historical-series replay and data-vintage controls. No API calls or broker routes are authorised.

## SD-11F — Original SignalDeck eToro HTTP-200 comparison (2026-10-18)

- [x] **Original implementation located:** Private repo `smbabalola/SignalDeck`, reviewed branch `bundle7/complete-demo-lifecycle`. Its eToro REST adapter sends `GET /api/v2/market-data/instruments/search?query=AAPL&limit=5`, `GET /api/v2/market-data/rates?instrumentIds=...` and `GET /api/v1/market-data/instruments/{id}/history/candles/asc/OneDay/10`, using `x-api-key`, `x-user-key`, `x-request-id` and direct `http.client.HTTPSConnection` by default.
- [x] **Difference to failed SideDeck call:** `GET /api/v1/market-data/search?internalSymbolFull=AAPL`, same documented header names but **`urllib`** transport; exact eToro current official guide still documents v1 search. **Do not assume v2 will work now without permission**.
- [x] **Prior owner acceptance recalled:** On 2026-09-27 direct PowerShell reportedly returned HTTP 200 for several SignalDeck market/demo reads; previous Codex contexts sometimes received 403. This is owner-reported prior evidence, not a live verification today.
- [x] **SD-11F candle direction defect:** SignalDeck uses `asc|desc`; published market-data OpenAPI also enumerates those two values, while SideDeck currently constructs `/history/candles/backward/OneDay/1000`. **This is an untested follow-on compatibility bug**, unrelated to the first 403, which occurred at search. Replace with `desc` in a separate offline-tested code change before any consented history reads. See `docs/SIGNALDECK_ETORO_COMPARISON.md`.
- [ ] **Next offline task:** Locally compare **only boolean equality** of the loaded key pairs across SignalDeck and SideDeck, verify cwd/`.env` selection and proxy environment indicators without displaying values, hashes or keys. Build sanitized request-shape unit tests for v1 vs v2. No network requests.
- [ ] **Fresh authorisation required:** Only after offline findings should the owner consider **one** newly scoped read-only v2 search request, never broker/account/orders. Old permission remains consumed.
- [x] **Investigation report:** `docs/SIGNALDECK_ETORO_COMPARISON.md`. The HTTP 403 is a request/access-context failure, **not evidence eToro lacks five years of history**.

## SD-11G — offline SignalDeck request-contract alignment

- [x] Corrected SideDeck `/api/v1/market-data/instruments/{id}/history/candles/desc/OneDay/{n}` from unsupported `backward`; GET allowlist remains strict and bounded to 1,000, no other HTTP paths permitted.
- [x] Added synthetic tests for v1 query, direction/allowlist, v2 reference request shape, auth header keys/UUID and no network calls. **No v2 live fallback** was activated; the earlier HTTP 403 still occurred before any candle GET.
- [ ] **SD-11G local only:** Confirm SignalDeck's and SideDeck's actually loaded key values match with booleans only, correct `.env` roots and proxy-config presence. No values, hashes, length metadata or remote requests. Local Codex to report findings.
- [ ] **Gate:** Fresh explicit owner approval is required before any further authenticated eToro GET, including a single v2 instrument search. Broker and Demo account endpoint access remain forbidden.
- [x] **Code CI:** `4a8f9dc21ee2ff912cd7f017666b3c5848f154b1` passed [39152259268](https://github.com/smbabalola/sidedeck/actions/runs/39152259268) and [39152256473](https://github.com/smbabalola/sidedeck/actions/runs/39152256473): 99 tests passed / 3 known SQLite warnings, Ruff passed, mypy passed (26 source files), disposable PostgreSQL CI passed. Zero provider/network calls.

**Detailed handoff:** `docs/SIGNALDECK_ETORO_COMPARISON.md`, [local-only secret-safe checklist](docs/SIGNALDECK_LOCAL_CHECK.md), and `AGENTS.md`. **Do not claim that the locally ignored key pairs or proxy configuration have been checked through GitHub.**
## SD-11G offline SignalDeck/SideDeck parity findings (2026-10-18)

- **Result:** `OFFLINE_LOAD_MISMATCH`.
- **Checkout presence:** `CHECKOUT_SIGNALDECK_PRESENT=true`; `CHECKOUT_SIDEDECK_PRESENT=true`.
- **Credential file booleans:** `SIGNALDECK_FILE_BOTH_PRESENT=true`; `SIDEDECK_FILE_BOTH_PRESENT=true`; `DOTENV_SAME_API_KEY=true`; `DOTENV_SAME_USER_KEY=true`; `DOTENV_SAME_KEY_PAIR=true`.
- **Formatting:** `SIGNALDECK_FORMAT_CLEAN=true`; `SIDEDECK_FORMAT_CLEAN=true` — nonempty, printable, no quotes, edge whitespace, internal whitespace or non-ASCII characters. No values, hashes, lengths or prefixes were recorded.
- **Loading:** SignalDeck source uses Pydantic `env_file=".env"` with `ETORO_*`/`SIGNALDECK_ETORO_*` aliases, so its checkout-local settings loader can read the matching pair. SideDeck `data_probe.py` reads process environment only. `SIGNALDECK_RUNTIME_ENV_BOTH_PRESENT=false`; `SIDEDECK_RUNTIME_ENV_BOTH_PRESENT=false`; a plain SideDeck launch therefore does not auto-load its `.env`.
- **Proxy booleans:** `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY` were absent from both `.env` files and the process environment. User and machine proxy settings were disabled/unconfigured; WinHTTP was direct. No proxy values were printed or stored.
- **Request contract:** offline eToro request-shape/safety tests passed: **8 passed**. SignalDeck’s legacy v2 shape and SideDeck’s v1 shape remain different; no v2 fallback or network call was attempted.
- **Account status:** Matching local file values do **not** prove correspondence to the currently active eToro account or endpoint entitlement. No eToro request was made.

**Independent interpretation:** `OFFLINE_LOAD_MISMATCH` accurately identifies the default loading behavior of the two tools, **but is not the demonstrated cause of the Oct 18 HTTP 403**. The earlier one-shot SideDeck probe had manually loaded `.env` into its process, passed the presence guard and actually received eToro's 403. Matching file values substantially weakens the swapped-key explanation; unverified possibilities remain endpoint-specific access, legacy v2 vs currently documented v1 behavior, network transport/egress variation, and account entitlement. No proxy configuration was observed in the offline owner environment.

**Source check:** eToro's current [Find Instrument ID](https://api-portal.etoro.com/guides/get-instrument-id) documents **v1** `GET /api/v1/market-data/search?internalSymbolFull=AAPL` with the three headers; legacy SignalDeck used `/api/v2/market-data/instruments/search?query=AAPL&limit=5` and direct `http.client`. Do not declare v1 incorrect or assume the legacy v2 path is currently supported.

**Safe next action:** Preserve a secret-safe launcher for later tests and do not alter either `.env`. The next meaningful discriminating test would be **one** local, read-only, AAPL-only legacy v2 instrument-search GET using the same key pair and host (no rate/candle/portfolio/order requests, no automatic fallback or retries, no browser and no credential output), **only following fresh explicit owner permission**. If 403 persists, escalate via eToro support. No fresh eToro permission is implied by this offline comparison.


## SD-11H — Owner selected SignalDeck legacy v2 instrument search (2026-10-18)

- **Owner instruction:** “Use V2” / “Use it anyway.” Instrument search is switched to the actual legacy SignalDeck query: `GET /api/v2/market-data/instruments/search?query=AAPL&limit=5` with `results[]` / `symbol` / `instrumentId` / `type` decoding. This is a user-selected compatibility route although current public eToro documentation also lists v1 search.
- **Mixed-version behavior is intentional:** Daily candles stay on `GET /api/v1/market-data/instruments/{id}/history/candles/desc/OneDay/{n}`, matching SignalDeck's v1 candles. Fixed HTTPS host, per-request UUID, bounded response size, market-data-only GET allowlist, 401/403 fail-closed and no broker endpoints remain enforced.
- **Normalization caveat:** Legacy v2 search may omit currency; USD is an expectation from SideDeck's curated US symbol universe, **not an independently observed provider currency or broker-instrument certification**. Reject an explicitly non-USD, leveraged, inverse, unsupported-type or ambiguous match. Historical data and tradability remain unverified.
- **Scoped local diagnostic:** A new `--single-v2-search AAPL` mode needs explicit read-only CLI flags and makes at most one AAPL instrument GET, zero candle/rate/trading/portfolio requests and zero automatic retries. It does not auto-load the local `.env`. The latest owner permission covers this one bounded local read only; mark it consumed after execution. No secret access or network call was conducted through GitHub.
- **Verification:** Offline synthetic tests added for v2 search shape, strict allowlist, live opt-in guard, AAPL-only/no-candle dry run and response type checks. **CI green:** [39153964246](https://github.com/smbabalola/sidedeck/actions/runs/39153964246), code SHA `f1075e4`: **103 passed**, 3 existing SQLite warnings, Ruff passed, mypy passed on 26 source files. This confirms offline implementation only, not an authenticated eToro HTTP 200. The prior real SideDeck v1 HTTP 403 remains historical evidence; **v2 HTTP status is unknown**.
- **External blockers:** No proof v2 is currently accessible; no five-year daily historical coverage and no broker Demo/Real orders. No unrestricted repeat probe authorized.
- **Code:** commits `decfc16` through `f1075e4` on `feat/p2-agent-adapters`; draft PR stays unmerged. Prior `SD-11F/G` notes are retained as historical findings rather than current route descriptions.

**Next action:** Verify branch CI, then execute at most one bounded AAPL v2 read on the owner's local checkout using the ignored matching key pair; record status without secrets. If denied, stop and escalate to eToro developer support. Continue offline licensed history work independently.
## SD-11H one-shot v2 search evidence (2026-10-18)

- [x] **Exact authorized diagnostic executed once:** `.venv\Scripts\python.exe -m sidedeck.data_probe --provider etoro --market-data-only --allow-read-network --confirm-owner-read-only --single-v2-search AAPL`.
- [x] **Credential handling:** Existing ignored `.env` values were loaded privately into the child process only. No values, hashes, headers or URLs containing secrets were displayed, logged, staged or uploaded.
- [x] **Result:** HTTP `403`; AAPL `RESOLVED=false`; safe error classification `EtoroAccessBlocked` / `market-data access denied`. Automatic retries were disabled (`max_retries=0`).
- [x] **Scope proof:** No candles, rates, account, portfolio, positions, orders, Demo or Real endpoints were requested. No second symbol or fallback route was attempted.
- [ ] **Access status:** `V2_SEARCH_BLOCKED`; this does not establish historical-data availability. The one-shot v2 authorization is consumed; further eToro requests require fresh explicit approval.

**Next action:** escalate the sanitized v2 endpoint/status to eToro support or verify portal entitlement out-of-band. Preserve credentials and do not broaden the scope.


## SD-12A — owner selects Alpaca PAPER controlled exclusively by SideDeck (2026-10-18)

- [x] **Decision:** Alpaca PAPER becomes preferred future broker. **SideDeck remains the only portfolio control plane**, maintaining separate `tradingagents` and `ai-trading` strategy ledgers at USD 1,000 each. This does not establish two broker accounts from one paper key. No paper/live Alpaca request or broker order has been executed.
- [x] **Paper read-only groundwork:** `src/sidedeck/domain/alpaca_paper.py` parses PAPER account cash/equity/buying power/restrictions, long-only positions and open orders with strict read GET paths. `src/sidedeck/paper.py` implements inert fixture `--dry-run` and opt-in paper-account inspection. All network access requires explicit flags plus locally loaded key and secret. Never auto-submit/cancel orders.
- [x] **Licensing/architecture:** Paper host is locked to `https://paper-api.alpaca.markets`. Market-data service is separate. New architecture decision: `docs/ADR-002-alpaca-paper-control-plane.md`.
- [ ] **SD-12A-1 local credential check:** Confirm `ALPACA_API_KEY` **and paper secret** under supported environment name(s) in ignored local `.env`. No credential values, hashes or account IDs in logs/commits. Check dashboard-issued paper keys. Default process does not load `.env`.
- [ ] **SD-12A-2 owner/local verification:** Require bounded explicit read-only authorisation before first account/positions/open-orders GET. Do not equate paper account default (often USD 100k) with SideDeck allocated USD 1k.
- [ ] **SD-12A-3 independent broker accounts:** For two truly broker-separated strategy portfolios, establish two distinct paper accounts + credentials, manually configured and privately mapped to each strategy; don't create accounts or reset balances automatically. Until then, SideDeck internal ledgers remain separate, broker execution disabled.
- [ ] **SD-12A-4:** Implement robust paper order intent/risk/idempotency/kill switch/reconciliation and audited broker fill postings, with a distinct explicit owner gate before paper writes. **No real/live trading, no crypto/shorts/leverage/options/CFDs.**
- [ ] **SD-12A-5:** Verify Alpaca historical adjusted daily prices, five-year availability and rights; distinguish historical backtest from ongoing paper execution. Basic feed real-time IEX and recent 15-minute delayed SIP caveats apply.
- [x] **Offline verification:** commit `ff27ab168f6b4bfbbf8183e8bad5588a6bb069cd`: [CI 39155948631](https://github.com/smbabalola/sidedeck/actions/runs/39155948631) and [CI 39155944560](https://github.com/smbabalola/sidedeck/actions/runs/39155944560) both green — **130 passed**, three known SQLite warnings, Ruff/mypy (28 source files), disposable PostgreSQL. 27 additional synthetic Alpaca PAPER tests cover no-network opt-in guard, read-only host/headers, one aggregate account, long-only approved positions, orders, nonfinite values, 401/403 fail-closed and error-body redaction. **No Alpaca account or market data has been read.**

**Acceptance handoff:** `docs/ALPACA_PAPER_ACCEPTANCE.md`. First run offline dry-run, verify existence (not values) of local paper key + secret. Next bounded paper account inspection is a distinct opt-in in the user's local Codex environment. No order API until an independent owner write gate after account allocation, risk preflight, kill switch and reconciliation.

## SD-12B — Two Alpaca PAPER key IDs reported (2026-10-18)

- [x] **User report:** Two local key ID variables, `ALPACA_API_KEY` and `ALPACA_API_KEY2`. This does **not** independently verify two distinct paper accounts. Require the corresponding `ALPACA_SECRET_KEY` and `ALPACA_SECRET_KEY2` or supported paper secret aliases; never upload, log, hash, print or commit values.
- [x] **Offline-only two-account readiness:** `sidedeck.paper_pair --dry-run` uses synthetic accounts and needs no keys. `DualPaperAccountInspector` checks exactly one GET `/v2/account` per injected paper credential transport, compares broker account IDs **in memory**, and reports only the distinctness/active/unblocked/margin booleans. No account IDs, secret values, positions or order contents appear in its output. The result always sets `broker_order_submission_enabled=false`.
- [ ] **Scope test outstanding:** Two real paper account identities must be checked via owner-approved read-only two-GET local test (never GitHub); two keys can still belong to the same paper account. Distinct paper accounts must be mapped to `tradingagents` / `ai-trading` before broker writes are ever enabled.
- [ ] **Credential safety:** Validate the two secret variables exist locally and both sets were issued under Alpaca *Paper*. Different API key values do **not** establish different accounts. Don't call the live trading API, don't create/reset accounts, and don't trade.
- [ ] **Additional broker safety gate:** Paper order APIs stay entirely unimplemented; separately verify both ledgers' $1,000 allocations and risk gates, broker-side balances (which can default to $100,000), fill-level journal reconciliation, no leverage/shorts/crypto and strict account mapping before asking for paper-order approval.
- [x] **CI verified:** code commit `4c9475e4a33fb8e33608d03c8d89d090f572141d` passed [39157153830](https://github.com/smbabalola/sidedeck/actions/runs/39157153830) and [39157148985](https://github.com/smbabalola/sidedeck/actions/runs/39157148985): 144 tests green, Ruff green, mypy green, disposable PostgreSQL CI. 14 new dual-paper-account fixture tests. The code does not prove the real account identities are distinct.
