# SideDeck — Living TODO and delivery status

**Repository:** https://github.com/smbabalola/sidedeck  
**Canonical branch:** `feat/p2-agent-adapters` until reviewed and merged.  
**Updated:** 2026-10-18 (SD-11A code delivered; SD-11B official API compatibility fixes required before live reads)
**Verified integration branch SHA:** `12ae6eaae21e567034536d7d0c0ebb10397848da`  
**Latest CI evidence:** https://github.com/smbabalola/sidedeck/actions/runs/39140051347 — Python 3.12, 50 passed, Ruff and mypy (22 source files) green, disposable PostgreSQL; three existing warnings.  
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
- [ ] **SD-11B-1 / Must fix before any real probe:** Official eToro instrument guide specifies `internalSymbolFull=AAPL`, exact match on `internalSymbolFull` and a verified instrument ID. Current code requests `search=AAPL` and defaults critical instrument attributes. Normalise verified live response/metadata, reject ambiguous symbols, CFDs and unverified classification.
- [ ] **SD-11B-2 / Must fix:** Published candle payload nests `candles` by instrument and timestamps rows using `fromDate`; current flat parser expects `timestamp|date|time`. Check nested group instrument IDs and support documented zero volume without inventing it.
- [ ] **SD-11B-3 / Must fix:** Current `sidedeck.data_probe` prints only the AAPL instrument resolution. It does **not request or scan history**, so no authenticated five-year test would answer the goal. Implement offline-dry-run and bounded four-symbol history scanner, redacted output.
- [ ] **SD-11B-4 / Must fix:** `urllib.urlopen` throws `HTTPError` on 429, so current client retries do not work through the real transport. Correct status normalization, documented bounded Retry-After, safe GET URL allowlist and same-host redirect policy.
- [ ] **SD-11B-5 / Must fix:** A single max-1000 OneDay candle response **cannot** prove five years of approx 1,250 daily sessions; use accurate exchange-calendar coverage, leap-safe five-year periods, gaps/holidays and actual supported historical pagination or a legitimate second source. Do not fabricate data or treat weekly candles as daily.
- [ ] **SD-11B-6 / Required acceptance:** Full offline schema-fixture tests (including published examples), pytest/Ruff/mypy/PostgreSQL and README/docs. Keep live calls and key use disabled until the owner separately approves only eToro `/market-data/` GET and local secrets. **Actual account-specific depth remains unverified** until that bounded check.

**One-pass coding brief:** [`docs/ETORO_API_FIXES.md`](docs/ETORO_API_FIXES.md). Complete SD-11B code fixes without routine review pauses. No further Yahoo/OS firewall work, no paid LLM, no orders/eToro broker access.

