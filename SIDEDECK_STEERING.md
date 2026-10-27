# SIDEDECK_STEERING.md — Autonomous engineering charter

**Status:** ACTIVE | **Owner:** SideDeck project owner | **Applies to:** `feat/p5-agent-adapters` and descendants until deliberately superseded.
**Purpose:** Give Codex a durable mandate to finish SideDeck through coordinated, tested batches without asking for new instructions after every task. This file governs `TODO.md`. It is an engineering policy, **not** permission to spend money, access authenticated accounts, or trade.

## 0. How to start every Codex session

1. Read `AGENTS.md`, **this file**, `TODO.md`, `README.md`, relevant docs and latest CI. Precedence: explicit current owner instruction > non-negotiable safety rules in `AGENTS.md`/this charter > `TODO.md` > historical docs. Resolve conflicts conservatively, document them; never silently bypass safety.
2. Check branch, HEAD, working tree, untracked files, local toolchains, pending commits and GitHub Actions. Work only in the **nested** SideDeck checkout on `feat/p5-agent-adapters` or an approved worktree. The outer `feat/p2` worktree is separate. Never discard uncommitted or untracked work.
3. Read the top **Current execution board** in `TODO.md`. Select the highest-priority **READY** items with no unmet dependencies. Create a batch of 3–8 compatible tasks rather than a one-issue cycle.
4. Execute all safe tasks through implementation, deterministic tests, independent checks, docs, commits, push, GitHub CI and remediation. When blocked, record precise evidence and pivot to the next unblocked item. Do **not** stop a batch because one provider, dataset, permission or workstream is unavailable.
5. Report at meaningful milestones and at the end; do not ask for routine architecture, naming, testing, refactoring or synthetic-data decisions that can be resolved under this charter. Explicit owner approvals defined below are the only deliberate stops.

## 1. Product outcome and definition of done

Build an auditable, practical SideDeck **research → strategy evaluation → controlled paper portfolio** workstation for US equities initially (SPY/NASDAQ universe where genuinely sourced), extensible to other markets. It must:

- Ingest genuine, provenance-tagged point-in-time OHLCV and SEC accounting evidence with strict instrument/session/currency/filing-time/corporate-action validation.
- Run separate real **TauricResearch/TradingAgents** and **virattt/ai-hedge-fund (BuffettAgent first)** research adapters with pinned upstream identity, bounded provider usage and reproducible inputs. Preserve abstentions and failures. Never turn an AI opinion directly into an order.
- Compare hypotheses, versions and strategies with deterministic, **no-look-ahead** backtests and explicit transaction costs, slippage, drawdown, position/risk sizing, train/validation/out-of-sample splits, parameter stability and leakage controls. Benchmark to buy-and-hold; synthetic testing is not profitability evidence.
- Show a polished Tailwind/React dashboard: evidence, agent comparison, reproducible experiments, strategy equity/drawdowns, research readiness, broker reconciliation and clear data age, with privacy-by-default.
- Reconcile strictly segregated broker **paper/demo** books with strategy → research → intent → authorization → order → fill → position → exit lineage. Broker integration must be separately released; do not confuse research completion with order authorization.
- Provide operational reliability: typed contracts, audit logging with no secrets, replay/recovery, idempotency, stale-data checks, automated tests, reproducible builds, explicit risk limits, controlled demo soak and incident stops.

**Full completion =** all applicable release gates evidenced, no unresolved P0/P1 risks, accepted real-data research and backtests, separately approved paper-order lifecycle and soak, passing CI, demonstrated operator workflows and documentation. A green CI run alone is not completion. Real-money trading is **out of scope**, not a future implicit toggle.

## 2. Immutable boundaries: never cross autonomously

- **No real-money orders, withdrawals, deposits, transfers, leveraged transactions or live execution.** Do not add a path that can silently unlock them.
- **Broker priority (owner decision 2026-10-21, [ADR-003](docs/ADR-003-etoro-demo-primary-broker.md)):** eToro **Demo** is the PRIMARY paper broker; Alpaca PAPER is SECONDARY (retained, separation `UNVERIFIED`, authorizations exhausted). **eToro Real execution is permanently excluded**, including agent portfolios with Real scopes. Position ownership only via verified order→position lineage, never ticker. A priority change is not permission to trade.
- **No paper/demo order submission, cancel, close, modify or automatic execution** unless the owner separately approves a *specific broker, environment, execution scope, order controls and release*. The presence of `ALPACA_API_KEY`/`ALPACA_API_KEY2` or eToro credentials is not authorization. Saxo P4 remains `NO-GO`, `SIM_SUBMISSION_RELEASED=False`.
- Preserve the **four original eToro Demo positions** as immutable, unattributed baseline and protected from SideDeck closes. Never re-run baseline capture, reset or replace its SQLite database or attribute positions merely by ticker.
- **No paid LLM/provider calls**, subscriptions, financial commitments or unattended spending without separately recorded, specific owner approval for provider/model, max calls, max USD, ticker, time period and single run. A CLI boolean is not sufficient evidence of independent owner authorization. Budget *validation* is not metering; implement enforceable runtime limits before releasing model calls.
- **No new authenticated eToro/Alpaca/Saxo/broker endpoint request** without specific owner authorization of endpoint, intent and request count. An earlier granted one-shot Demo refresh does not grant blanket broker polling. Public SEC downloads are allowed only when necessary, policy-compliant, read-only, clearly logged in an audit (genuine identified User-Agent, throttling), and never claimed to have occurred if offline.
- Never commit credentials, `.env`, raw account responses, broker IDs, monetary account values, private local datasets, `data/`, raw model outputs containing secrets, `node_modules`, build artifacts or personal identifiers. Broker credentials must be explicitly excluded from all spawned research runtimes.
- No fabricated data, fake real results, optimistic fallback, accidental latest-filing look-ahead or weak valuation admission. Unknown/irrelevant fields stay `UNAVAILABLE`/`NOT_APPLICABLE`; source labels such as 'official' do not certify SIP consolidated or price-adjustment basis.
- Never overwrite unrelated local changes or worktrees; no destructive database migrations, history rewrite, force push or merge to default without explicit approval.
- A simulated positive strategy return is **not** an investment recommendation or approval for execution.

## 3. Decisions delegated to Codex

Codex may autonomously: inspect source/docs, create/update architecture and tests; download/use public freely accessible issuer SEC data subject to source terms; use synthetic/offline fixtures; perform local **non-network** agent/interface preflight; change internal APIs and dashboard; refactor/resolve defects; run local tests, disposable DB containers, audits; make focused commits and push only the authorized feature branch; investigate CI failures and fix them; prepare risk/authorization plans; choose conservative defaults; add work items and acceptance checks.

Codex must **stop only the affected action** for: paid/credentialed data access; real agent provider call; any broker/demo order path; unexpected personal/portfolio access; allocating capital; publishing externally; merging/releasing to users; breaking schema changes on an existing real database; unresolved security/privacy or accounting ambiguity requiring operator judgment. Do not block independent offline work while awaiting these approvals.

### Authority / decision matrix

| Action | Autonomous? | Required proof |
|---|---|---|
| Offline implementation, tests, mocks, source review, UI | YES | CI + regression evidence |
| Public SEC retrieval | YES, compliant, read-only | URL, timestamp, source policy, filing availability |
| Existing private local data analysis | YES only approved project files, protect bytes | sanitized outputs, provenance |
| Authenticated price or broker-account GET | NO, owner scope approval | exact endpoint, requests, response privacy |
| Paid AI model or paid data service | NO, owner cost/scope approval | enforced spending ceiling and provider receipt |
| Demo/paper order/cancel/close or capital allocation | NO, separate explicit release | audited human approval + risk/security lifecycle |
| Real-money trade or order capability | NEVER | out of scope |
| Merge, deployment, production migrations | NO | owner release review |

## 4. TODO.md is the execution control plane

**STEERING = policies and goals; TODO = current state, ordered runnable tasks.** Maintain a short active board at the *top* of TODO.md and archive historical evidence below a clear separator (or to `docs/archive/`). No contradictory 'latest commit' metadata lingering as current truth.

Every active item must include an ID, priority (P0/P1/P2), status, dependency IDs, acceptance criteria, evidence pointer, and `BLOCKED_BY_OWNER` flag if relevant. Allowed statuses: `READY`, `IN_PROGRESS`, `BLOCKED_EXTERNAL`, `BLOCKED_OWNER`, `IMPLEMENTED`, `VERIFIED`, `CLOSED`. Never mark `CLOSED` on implementation alone: demand tests and evidence. Use `NOT_APPLICABLE` for intentionally excluded features.

Rules:
1. At session start, reconcile TODO with repo HEAD and actual CI. Prefer code and validated artifacts over old narrative or checkboxes.
2. Choose batch by risk reduction and dependency-unblocking value. Parallelize across independent modules where feasible; coordinate shared-file edits and merge safely.
3. For each completed batch: update statuses, relevant test names, evidence paths, remaining blockers, and next **READY** items. Record truthful CI results (pending means pending).
4. If blocked, record precise blocker, attempted offline alternatives, owner action and a **next runnable task**. Never loop on the same blocked provider endpoint without new authorization.
5. Always leave at least one useful next batch identified until the full product is accepted. Keep the board actionable for another Codex session with zero conversation context.
6. Issue-only backlogs that lack acceptance criteria are insufficient. Fix production-significant failures even if absent from the current board, and record them.

## 5. Prioritized roadmap and dependencies

**R0 — Trustworthy engineering baseline (highest priority, continuous):** check latest HEAD, no unexpected changes, CI/test evidence, security boundaries. Review previously added flags that can self-certify external evidence; require attestations/provenance for acceptance. Harden backtest no-look-ahead and cost accounting.

**R1 — Real market-data and valuation evidence:** find existing local MSFT price data first; identify exact source/entitlement. Add offline independent closing-price comparison with split/share class, filing publication time, point-in-time prices and adjustment rules. If evidence unavailable, build safe importer/tests and mark valuation `BLOCKED_EXTERNAL` (do not manufacture market cap/P/E). eToro v1 AAPL symbol search **was** verified HTTP 200; historical close/candle entitlements are **not** verified. Alpaca IEX is not a SIP consolidated close.

**R2 — Research fundamentals:** preserve MSFT 10/12 accounting coverage at 2026-06-30, 8 fully reconciled historical periods, valuation blocked. Confirm source accession, filing date and EPS/share denominators. MSFT first non-financial acceptance; SOFI second with bank profile (SPAC discontinuity, excluded leverage/BVPS valuation definitions). Do not treat `12/12` candidate tag presence as validated coverage.

**R3 — Two-agent genuine research gate:** confirm installed TradingAgents 0.7.0 and `aihf==2.5.0+git.ec025370c66cf71d3ea2f2d8f463b5934c1c48af` identity, clean pinned source; compare model/provider compatibility and bounded pricing. Build immutable research-input manifests, retries/cancel/quotas/budget ledger, no secrets to subprocess, owner authorization record. Verify real outputs only after approval; compare same instrument/time/provenance. SEC local injection means **Financial Datasets is not inherently required**.

**R4 — Strategy engine and validation:** implement deterministic order-timing model (signal at close cannot fill at that close without tradable subsequent-price proof), realistic spread/fees/slippage and order delay. Independently cross-validate equity, drawdown, profit factor, exposure, benchmark and split calculations. Robustness parameter surfaces/3D export, walk-forward/holdout and sensitivity; distinguish in-sample tuning and locked OOS. User prefers swing (5–15 days), long-term (1–6+ months), stocks/indices/FX, no crypto or intraday; first universe SPY/NASDAQ. Require out-of-sample evidence and robustness before portfolio use.

**R5 — Dashboard and operators:** complete research comparison, evidence explorer, experiment results, protected portfolio reconciliation, statuses and expiry, loading/error/privacy states, sample-independent UI E2E. Never show invented live positions or account values.

**R6 — Paper-trading release work (separate authorization):** eToro Demo first (offline desk SD-036; Alpaca PAPER secondary); isolated account mappings (eToro Demo vs Alpaca paper vs Saxo SIM), validated balances/cash, explicit virtual capital partitions, position/lot/order lifecycle, idempotency, risk limits, approval signatures and kill-switch. Only after audited permission can demo/paper sends be enabled; at least one month of supervised demo soak and documented kill criteria before further release. Keep existing four eToro positions untradeable by SideDeck.

**R7 — Operational hardening and release:** observability/redaction, reconnect/replay, migrations on disposable SQLite/PostgreSQL, secure local API, watchdogs, backup/restore, dependency scans, audit trail, docs/runbook, operator UAT and explicit release decision.

## 6. Batch execution algorithm

- Select **multiple** ready items spanning at least two independent workstreams when possible; minimize merge conflict. Plan a coherent 1–3 day-equivalent batch, not one minor check per handoff.
- First write or update failing tests/acceptance assertions where practical. Implement, run focused tests, full tests, Ruff, mypy, frontend typecheck/build and relevant UI E2E; separately run disposable SQLite and PostgreSQL migrations where applicable (never a user's live DB).
- Add negative/adversarial tests: wrong instrument, stale/future data, corporate actions, accounts mixed, missing evidence, untrusted LLM output, ID mismatch, credential leak, out-of-sample leakage, order attempts while disabled and invalid cost budgets.
- Treat **CI failures as active work**: inspect logs and fix, repeat until green. Report **BLOCKED** if tooling/permissions prevent verification rather than asserting pass.
- Commit in independently reviewable logical chunks, push to named branch, verify exact HEAD CI run; never rewrite history or trample another agent's commits.
- Continue down the TODO board until all safe, unblocked items in the batch are verified; only then hand off. If context/window runs out, leave complete resumable TODO state with exact files/tests/next steps. No promise of background activity beyond the running session.

## 7. Acceptance gates (separate; no implicit escalation)

- **G0 ENGINEERING:** tests, Ruff, mypy, frontend build and relevant migration/security tests pass on pushed exact HEAD. No unapproved change to portfolios or schema.
- **G1 DATA:** genuine data source, correct ticker, session, currency, as-of, filing-publication time, corporate actions, independent price corroboration and SEC metric reconciliation. Cannot pass on synthetic records.
- **G2 RESEARCH:** real pinned upstream runs and reproducible comparative output, explicit limited owner authorization, enforceable provider call/cost budget; no broker orders.
- **G3 BACKTEST:** independent calculation check, no future leakage, realistic costs, locked OOS and robustness tests, meaningful performance thresholds, failure analysis. Synthetic fixtures support correctness only.
- **G4 PAPER RELEASE:** independent human approvals, funds and attribution evidence, idempotent broker order lifecycle, risk caps, ability to halt, segregation and protected baseline; requires separate owner release even when G0–G3 pass.
- **G5 OPERATIONS:** sustained observed paper demo, monitoring/recovery/audit and UAT, documented go/no-go. No real-money toggle.

Gate evidence must state `PASS`, `FAIL`, `BLOCKED` or `NOT_ASSESSED`, dated with exact commit, test artifact, data source and explicit limitations. `G0 PASS` must never automatically set G1–G5 PASS.

## 8. Minimum end-of-session report

Return (1) branch/HEAD/commits and CI link/status, (2) workstream-by-workstream **IMPLEMENTED / VERIFIED / BLOCKED** status, (3) tests, migrations, frontend, security results with counts, (4) genuine versus fixture evidence, (5) what remains and owners of blockers, (6) explicit permissions **NOT** exercised, and (7) selected next ready batch. Avoid unnecessary back-and-forth and do not claim research or trading happened when it did not.

**Standing instruction:** Make as much safe, real, reviewable progress as possible. When a specific approval gate is reached, stop that *action*, clearly present one bounded approval request, and keep working on everything else.

## 9. Continuous autonomous execution — mandatory handoff correction (2026-10-21)

**Default behaviour: CONTINUE, not hand back after a green batch.** A milestone report is informational, not an invitation for new instructions. The owner has delegated ordinary engineering decisions and creation of new TODO tasks. Within the active Codex session, repeat the following cycle while tools/context remain available and safe work exists:

1. Reconcile HEAD, CI and the active TODO board. Execute the highest-impact unblocked work with failing assertions, implementation, independent review, tests, documentation, commits, push and CI.
2. **Before declaring a batch finished**, inspect the roadmap, acceptance gates, unresolved defects, current application behaviour, remaining unverified claims and technical debt. Generate concrete follow-on TODO IDs with priority, dependencies, acceptance evidence and expected user-facing capability. The next batch need not be prewritten by the owner.
3. If no READY task exists, **derive at least one useful safe READY task** from R0–R7 and unmet acceptance evidence, rather than ending because the board is empty. Examples: independent OOS metric audit, trade-count denominator validation, split/dividend benchmark treatment, leakage regression tests, multi-instrument risk/correlation validation, dashboard verification, local recovery/UAT and isolated paper-order lifecycle simulation. Do not manufacture busywork solely to keep cycling.
4. A BLOCKED_EXTERNAL or BLOCKED_OWNER dependency **blocks only actions needing that dependency**, not independent offline engineering. Explicitly separate engineering readiness from genuine data acceptance and execution release. Do not repeat failed provider attempts or silently relax acceptance conditions.
5. After each CI-verified commit, update TODO with the next READY batch and resume it **in the same session** if execution capacity remains. Keep milestones short and factual. Do not ask the owner to paste a newly drafted task prompt after each batch.
6. Stop only when: (a) all meaningful safe independent work is exhausted and remaining substantive work genuinely requires outside evidence/approval, (b) a hard safety boundary would be crossed, or (c) the current execution session has actually reached its technical/context limit. In case (c), leave a resumable TODO with the next READY task and exact commands/paths; never claim autonomous background continuation.
7. When owner approval is needed, present **one bounded, actionable request** specifying endpoint/provider or broker, purpose, exact scope, request/cost caps, and risks. Continue unrelated safe work first. Never infer that an earlier read-only approval permits a fresh request, model spend, account read or order.

**Immediate queue after SD-021:** SD-022 independent robustness review is READY. It must audit reported passing strategy screens against completed round trips rather than ambiguous transaction counts; independently reproduce IS/OOS equity, trade accounting, fees and benchmark conventions; check corporate-action/dividend provenance, SPY/QQQ overlap and risk controls. Record downgrade/rejection as a valid result. When completed, **self-generate and execute the next safe engineering work package** without awaiting another ChatGPT-to-Codex instruction.

**Autonomy limitation:** Steering files direct a running Codex session; they do not schedule unattended execution or automatically start a new session. Never conceal that limit or report work not actually performed.

## 10. First Demo Trade Completion and Autonomous Execution Transition (owner directive 2026-10-22)

**Highest-priority current milestone:** SideDeck's first genuine broker-connected eToro **Demo**
buy-and-close lifecycle — the reviewed SD-053 MSFT pilot — executed, reconciled and
independently audited. Tracked as SD-055…SD-063 at the top of `TODO.md`.

**Pinned pilot (never regenerated or altered silently):** eToro Demo only; MSFT instrument 1004;
BUY 0.09 units; 1×; limit IOC; signed max limit USD 552.56; ≤ USD 50; actual limit
min(signed max, fresh ask × 1.005) with the ask ≤ 60 s old; Fri 2026-10-23 10:00–11:30 ET;
≤ 12 HTTP requests, ≤ 2 order writes, no write retries; close only the lineage-verified
SideDeck position. Digest `71e111b3a8806dc9b8e59d96ce1ef6e6a0b64dc2b00363465244acccaad09a62`.

**Owner signing:** key `$HOME\.ssh\sidedeck_approval`, principal `owner@sidedeck`; release
namespace `sidedeck-etoro-pilot-release` over `data\sd053-msft-pilot-intent.digest`; per-order
open/close approvals in `sidedeck-etoro-pilot-approval`. Codex/Claude never create, hold or use the
owner's private key and never bypass SSH verification. A signature alone does not enable trading.

**Release boundary:** the order-network lock lift and any authenticated order request require one
consolidated owner release covering broker/environment, instrument/account scope, notional,
quantity, limit, leverage, date/expiry, endpoint allowlist, request/write budget, baseline
invariant, kill-switch/recovery policy, signed-release verification and the exact start
command. This section is **not** that authorization. Host (Claude/Codex) safety restrictions are
never bypassed; the owner runs host-blocked commands personally.

**Execution rules once released:** run only inside the signed window and scope; refuse on any
failed gate (eligibility, currency, type, fractional size, minimum, fresh price); submit the open
once; persist request id, acknowledgement and order identity; resolve uncertainty only through the
approved lookup path; never repeat a write; any unresolved outcome trips the kill-switch and
keeps the true outstanding state. If the window lapses, stay NO_GO and prepare a new
owner-approved window — never roll authorization forward.

**After the pilot (do not stop):** SideDeck agents → validated strategies → qualified signals →
deterministic portfolio/risk engine → autonomous eToro Demo execution → exit management →
reconciliation → performance feedback. AI assistants are development tools, never runtime trade
deciders. Order-level signatures may be replaced only by a **separately reviewed and expressly
owner-released bounded autonomous Demo policy** with deterministic risk checks, durable expiry,
strategy admission, capital/drawdown limits, recovery, alerts and independent audit. No model
approves its own permissions; unproven agents/strategies are never auto-promoted.

## 11. Market-wide autonomous scanning and multi-track trading (owner directive 2026-10-22)

**Goal:** expand SideDeck from a few researched instruments to a market-wide, multi-strategy
paper-trading platform that discovers opportunities with its **own** agents, quantitative
strategies and deterministic decision engine. Architecture:
[docs/SD065_MARKET_WIDE_ARCHITECTURE.md](docs/SD065_MARKET_WIDE_ARCHITECTURE.md); work packages
SD-065…SD-075 in `TODO.md` (Milestone 1).

**Priority order:** (1) the SD-058 MSFT Demo pilot and its SD-059…SD-062 completion — never
change its signed intent, digest, unlock, request budget or execution path; (2) offline
market-wide packages in parallel; (3) SD-063/SD-064 before any general autonomous Demo execution.

**Rules (additive to §2):**
- Universe: point-in-time registry; historical tests use securities eligible *on each date*;
  snapshot lists are never used for history. Discovery eligibility never implies trading
  eligibility; execution needs an independently verified broker mapping. Do not invent coverage
  or assume an instrument is available on eToro Demo. Phase 1 US; UK (phase 2), EU and major FX
  (phase 3) are design-only until separately approved. **No cryptocurrencies.**
- Pipeline: broad deterministic scan → per-track quantitative shortlist → agent research on the
  shortlist only → deterministic decision engine (`ELIGIBLE`/`WATCHLIST`/`ABSTAIN`/`REJECTED`).
  Scores are ranking heuristics, not forecasts. Agent agreement is not proof of an edge; an agent
  never grants itself execution permission. Only a separately authorized SideDeck Demo execution
  service may submit an eligible order.
- Tracks DAY / SWING / POSITION keep separate capital, risk, horizon, exit rules and strategy
  identity. A signal from one track never authorizes another; positions are never silently
  converted between tracks. New tracks default to research-only/simulation-only. **DAY**
  supersedes the earlier "no intraday" preference in R4 only as research/simulation; autonomous
  DAY execution needs separate validation and release, and it is `BLOCKED_EXTERNAL` until an
  approved intraday consolidated data source exists.
- Scheduling: exchange calendar in America/New_York (never fixed UK clock times), holidays,
  early closes, DST; persisted, non-overlapping, restart-safe jobs; per-track enable/disable.
- Data and cost: capability matrix; free/approved sources first; never present delayed,
  single-venue or incomplete data as real-time consolidated coverage; provider-specific budgets,
  rate limits, retries and failure isolation. No authenticated polling or paid calls without an
  applicable owner authorization and enforceable budget. Research workers never receive eToro
  execution credentials or the owner's SSH private key.
- Strategy admission (G3) per horizon: point-in-time universe, no look-ahead/survivorship,
  execution timing, corporate actions, realistic costs, train/validation/locked OOS, walk-forward,
  parameter stability, regimes, enough independent trades, benchmark, correlation and drawdown.
  A single high-ranking experiment never promotes a strategy.
- Dashboard: scanner status, per-track views, candidates, agent opinions/disagreements,
  provenance/freshness, rejected/abstained candidates, risk by track, permission/lock state.
  The owner may configure research schedules and shortlist sizes without code; changing
  execution permissions, capital limits or autonomous scope still requires verified authorization.

**Final acceptance (G5 extension):** discover from a genuinely sourced broad universe; evaluate
per track; coordinate native agents, imported methodologies and quantitative strategies; reject
unreliable approaches reproducibly; size with deterministic risk controls; execute, monitor and
exit autonomously in eToro Demo under an owner-released policy; reconcile and attribute
performance to strategy and agent; run with no ChatGPT/Claude/Codex in live decisions.

## 12. Professional trading workstation UI (owner directive 2026-10-22)

The React/Tailwind frontend is SideDeck's operator workstation with seven workspaces: Overview,
Markets, Trading tracks, Agents, Strategies, Portfolio, Operations. Tracked as SD-083…SD-087 in
`TODO.md`.

**Rules:**
- Read-only by construction: GET-only typed contracts validated at runtime; a payload that fails
  validation is an error, never guessed at. No order, close, capital, permission or schedule
  control; no new broker write path from the UI. The MSFT pilot and every release stay CLI-only
  behind the existing signed mechanisms.
- Provenance is always visible and never upgraded: `Real data`, `Demo broker`, `Simulation`,
  `Synthetic fixture` or `No data`, encoded as a panel edge plus a badge. Mixed panels badge each row.
  Synthetic or fixture scans can never be written as `REAL_DATA` (enforced in SD-082).
- Never fabricate balances, positions, signals or performance. Missing data is shown as missing,
  with the owner action that would unblock it.
- Loading, empty, error and stale states for every panel; explicit instrument identity, exchange
  and data timestamps; source strategy, version and track on every signal.
- Accessibility (WCAG 2.2 AA), keyboard operation, light/dark themes, desktop/tablet/phone layouts;
  self-hosted fonts (no third-party requests from the loopback app).
- Verification per batch: TypeScript, production build, Vitest unit tests, Playwright E2E on three
  viewports with a mocked API, Python tests, Ruff, mypy, independent review, exact-HEAD CI.


## 13. UK Equity Integration and Multi-Exchange Operations (owner directive 2026-10-23)

SideDeck must support multiple exchange calendars, currencies, instrument identifiers and trading
tracks. The UK market must have independently validated research, portfolio and broker mappings
rather than inheriting US assumptions. Design and evidence:
[docs/SD088_UK_EQUITY_INTEGRATION.md](docs/SD088_UK_EQUITY_INTEGRATION.md); work packages
SD-088…SD-096 in `TODO.md` (Milestone 4). This section supersedes the "UK (phase 2) design-only"
wording in §11 for **discovery, research and simulation only**.

**Priority:** the SD-058 MSFT Demo pilot keeps precedence. UK work never edits the SD-053 signed
intent, SD-057 scope, the digest-specific unlock, the US pilot request budget or the original
protected eToro Demo baseline, and never uses the MSFT authorization for a UK instrument.

**Rules (additive to §2 and §11):**
- Calendars: every exchange has its own calendar, time zone, hours, holidays, half days and DST
  (XNYS America/New_York 09:30–16:00; XLON Europe/London continuous 08:00–16:30, half days 12:30).
  Never assume US and UK share hours or holidays. Uncovered years fail closed. Calendar tables
  need authoritative corroboration before G1.
- Identity: LSE TIDM + exchange + ISIN (check digit) where available; ticker changes as dated
  intervals; vendor symbols (e.g. `.L`) are not identity. Unsupported security types (investment
  trusts, preference shares, ETCs/ETNs, depositary receipts, …) are rejected, never guessed.
- Units: every UK listing declares its quote unit. GBX/`GBp` (pence) and GBP (pounds) are never
  confused; ambiguous labels are refused; research and accounting prices are normalised to GBP
  with exact Decimal arithmetic; suspected unit flips fail closed.
- Universe history: current FTSE constituent lists are snapshots and are never backdated; index
  membership for history needs dated review evidence.
- Scheduling: DAY/SWING/POSITION jobs are per exchange (`xlon.*` namespace), with per-exchange
  track controls; no overlapping or duplicate runs; execution modes cannot be configured.
- Data: only owner-supplied licensed files or a bounded owner-authorized request (SD-094). No
  assumption that Yahoo, Stooq, LSE or FTSE Russell pages grant reuse rights. UK DAY stays
  `BLOCKED_EXTERNAL` without approved intraday quotes/spreads.
- Execution: UK broker execution is **NOT** enabled. An eToro Demo UK order needs its own verified
  instrument ID, identity/currency, fractional/minimum rules, fresh price, endpoint allowlist,
  separate signed owner intent, separate authentication/execution authorization and independent
  security review and release (SD-095). Simulation results are labelled `SIMULATION`.
- Acceptance is two separate milestones: *UK research acceptance* (sourced instruments, LSE hours,
  units, horizon signals, auditable simulated trade) and *UK Demo execution acceptance* (approved
  broker buy-and-close with genuine broker evidence and reconciliation). Never conflate them.

## 14. Execution-First Demo Completion Controller (owner directive 2026-10-23)

Until SideDeck has completed one genuine eToro Demo stock lifecycle—broker-confirmed buy,
fill, full close, final reconciliation and a flat SideDeck position—this is the controlling
milestone. Engineering batches, tests, simulations, signed documents, CI and authorization
proposals are supporting evidence, not milestone completion.

The durable controller state is maintained in `TODO.md` and must always identify:

- current broker execution state;
- latest verified broker evidence;
- current blocking defect;
- next independently executable action;
- required owner authorization or operator action;
- next execution-readiness gate; and
- the actual success or failure outcome.

The operating cycle is: obtain bounded broker evidence → diagnose the actual failure → fix the
smallest verified defect → independent review and CI → prepare a fresh signed Demo pilot →
owner-operated execution → broker-confirmed buy/fill/close/reconciliation. A failure returns to
diagnosis; no broker request is automatically repeated and no expired authorization, signature,
budget or window is reused. Codex never signs on the owner's behalf and never enables eToro Real.

The current state is `ABORTED_PREFLIGHT` for SD-058: no order writes or SideDeck positions,
transport re-locked, and the original eligibility response is not locally available for
diagnosis. The standalone one-request diagnostic runner is now implemented and independently
tested offline. Its release state is `READY_FOR_OWNER_DIAGNOSTIC_AUTHORIZATION`: execution still
requires a fresh, separate owner-signed authorization and owner-operated command. It is not
executed, approved, or trade-ready, and no prior pilot signature or unlock may be reused.

### 14.1 Execution controller — complete the first Demo trade (owner directive 2026-10-23)

The controlling objective is one eToro Demo buy, broker-confirmed fill, complete close and final
reconciliation. Continue automatically through all safe, unblocked development and verification;
do not stop at engineering milestones. Only owner signatures, transport lock-lift approvals and
owner-operated runs wait for the owner. A real defect → investigate saved broker evidence →
smallest verified fix → test + independent review → continue. No unrelated scanning, dashboards,
autonomous strategies or architecture work until COMPLETE. Never reuse an expired or consumed
signature; if a window expires, preserve evidence and prepare the next session's fresh intent.

`NAIVE_AS_UTC` is a **limited operational assumption**, not a verified eToro convention: allowed
only for the supervised Demo pilot (`parse_fresh_quote(..., allow_naive_utc=True)` in the SD-046
preflight), only with the 60 s age / 5 s future-skew gate and the signed price limit, and only
with the owner's specific acceptance. Never for general market data, backtests or autonomous
execution. The audit records the timestamp's format shape (never its value).

**COMPLETE** only when eToro broker records prove: opening fill, closing fill, zero remaining
pilot position, final reconciliation MATCHED, protected baseline unchanged, transport re-locked.
Tests, documents, mocks and successful reads are not sufficient.

## 15. Autonomous Demo execution — verified versus blocked (owner directive 2026-10-23)

SD-063 passed an independent review (six passes) and offline remediation; SD-074's input boundary
is implemented offline. **No autonomous eToro Demo order is authorized.** The USD 1000 / 7-day
values are design ceilings, never an allocated budget. Never wire the policy into the SD-058 MSFT
pilot or change its reviewed execution behaviour. eToro Real is excluded permanently.

| Requirement | Status |
|---|---|
| Signed autonomous policy (Demo only, ≤ 7 days, ≤ USD 1000, DAY/SWING/POSITION) | VERIFIED offline (SD-063; execution still unreleased) |
| Grant re-verified on every call; runtime clock only | VERIFIED offline |
| Strategy evidence pinned by owner-signed SHA-256; decision engine run internally | VERIFIED offline |
| Exposure, cash, equity, loss limits from the ledger | VERIFIED offline |
| Concurrency (`BEGIN IMMEDIATE`), single-use references, kill-switch (entries only) | VERIFIED offline |
| Tamper-evident ledger; crash/tamper recovery quarantines, never trusts anchored rows | VERIFIED offline |
| Authenticated signals/quotes/fills (sealed envelopes, roles, replay protection) | VERIFIED offline (SD-074 + SD-108 adapters) |
| Unknown outcomes settled only by sealed broker reconciliation evidence | IMPLEMENTED offline |
| Protective-exit authority after expiry/revocation (reduce-only) | IMPLEMENTED offline |
| Incident report and runbook | IMPLEMENTED (`docs/SD074_OPERATOR_INCIDENT_RUNBOOK.md`) |
| Off-machine ledger/revocation anchoring | Verification building block IMPLEMENTED offline (`sd074_external_anchor`); real write-once remote store and wiring BLOCKED (owner provisioning) |
| SD-064 grants wired into the Demo order transport; send-time caps | VERIFIED in offline SD-107 simulator; production HTTP transport remains locked |
| Independent review of the full policy-to-transport lifecycle | BLOCKED on the wiring above |
| Owner release of a bounded autonomous Demo operating period | BLOCKED_OWNER |

## 17. Day Trader independent module (owner directive 2026-10-26)

The MIT-licensed `day-trader-skill` is an independent SideDeck module, not a replacement for the
central pipeline. Its installed version is pinned and verified before use; all eleven skills run,
if at all, in a credential-free, network-blocked sandbox. The module starts in `RESEARCH_ONLY` and
may use `SIMULATION_ONLY` for labelled offline acceptance. Its dedicated `DAY_TRADER_SKILL` book
is attribution only; it is not a second broker account or an execution permission.

The upstream broker component may render a ticket for inspection but must never forward a broker
connector payload. Day Trader output is untrusted input and becomes a SideDeck `ResearchSignal`
or proposal only after schema validation. SideDeck strategy admission, risk, portfolio allocation,
order journal and reconciliation remain authoritative. No Day Trader execution is released until
approved intraday data, independent locked-OOS strategy admission, a reviewed gateway path and a
separate owner release exist. Yahoo or other public feeds are never promoted to real-time or
execution data by this module. The Day Trader dashboard is read-only and exposes no order,
capital, permission or schedule controls.

## 16. Integration-first: one operational trading pipeline (owner directive 2026-10-26)

**Current offline engineering workstream (owner directive 2026-10-27):** the Day Trader module is
now connected to the policy-bound offline Demo gateway through SD-122/SD-123. Production broker
release remains separately blocked; keep the autonomous execution draft PR open and unmerged while
preserving every data, admission, review and owner-release gate below.

The former engineering priority was to integrate the existing components into one pipeline —
MARKET DATA → SCANNER → STRATEGIES → AI AGENTS → DECISION ENGINE → RISK ENGINE → PORTFOLIO
ALLOCATION → PAPER BROKER → FILLS → POSITION MANAGEMENT → EXIT → PERFORMANCE — rather than
adding isolated pilots or demonstrations. Entry point and evidence:
[docs/SD103_INTEGRATED_PIPELINE.md](docs/SD103_INTEGRATED_PIPELINE.md); work packages SD-103…SD-111
(Milestone 5 in `TODO.md`). The §14 Demo round trip remains the **broker-acceptance** milestone
(Stage 1); a manually chosen instrument (MSFT, BP) is a labelled connectivity test, never a
strategy recommendation. The UK BP pilot draft is parked (`parked-uk-bp/`, untracked).

**Rules (additive to §2, §10, §11, §15; nothing here relaxes them):**
- A trade starts from an **admitted** strategy. Admission = SD-022 robustness VERIFIED plus the
  SD-071 floor (≥ 30 locked-OOS trades) on genuine data. Admission is never relaxed to create a
  trade; changing the method (e.g. pooled cross-sectional OOS evidence) is an owner G3 decision.
- No qualifying trade → `NO TRADE` with the reason. Never manufacture an opportunity.
- Fixture admission overrides exist only for the acceptance harness, are refused for REAL_DATA
  and are labelled `FIXTURE_ONLY_OVERRIDE_NOT_EVIDENCE` everywhere they appear.
- Replays lock admission on data before the replay window; decisions at a close use bars up to
  that close; simulated fills happen at the next open and are `SIMULATED_LOCAL`.
- Agents may support but never qualify or authorize a trade; the engine works without them.
- Only the `SIMULATED_LOCAL` route runs. eToro Demo becomes an SD-103 route only through SD-074F
  (SD-064 grant + SD-063 runtime + SD-074 sealed inputs + send-time caps), an independent
  review of the grant-to-order path and a separate owner-signed policy release. eToro Real is
  permanently excluded. Per-order signatures are replaced only by that released policy.
- Report the gates ENGINEERING, REAL_DATA, STRATEGY_ADMISSION, AI_RESEARCH, BROKER,
  PAPER_EXECUTION and FORWARD_TESTING separately as VERIFIED / BLOCKED / FAILED / NOT_ASSESSED.
- **Pooled admission (owner direction 2026-10-26):** SD-112 is a *proposal-only* method
  ([docs/SD106_SD112_EVIDENCE_AND_POOLED_METHOD.md](docs/SD106_SD112_EVIDENCE_AND_POOLED_METHOD.md)):
  same fixed strategy version, shared chronological splits, sealed final holdout (one-time
  owner unseal), effective sample size for overlapping/correlated trades, multiple-testing
  adjustment, concentration, regimes, cost stress and benchmark; per-instrument failures stay
  visible. It never changes the production gate or admits a strategy; adopting it requires
  owner review of the method and results and a separate reviewed gate change.

## 18. Day Trader operational research boundary (owner directive 2026-10-26)

The Day Trader module has one runnable offline entry point:
`python -m sidedeck.application.sd114_day_trader run --fixture --db data/day-trader-runs.sqlite3`.
It invokes the pinned upstream scripts, persists a bounded sanitized report and remains
`RESEARCH_ONLY`. The read-only API may expose saved opportunities, plans, rejected candidates,
stage errors, scenario simulations and provenance, but it cannot create orders or alter portfolio
state. `SIMULATION_ONLY` and fixture evidence are never strategy admission or performance proof.

The current Python sandbox is acceptable only for the pinned, reviewed source. It is **NO-GO for
untrusted skill execution** because Python-level socket/subprocess patches and workspace copying
are not OS-enforced isolation. Any future untrusted execution needs a separately provisioned
low-privilege Windows sandbox/AppContainer or isolated VM with no network, inherited handles or
credential environment. The security review is `docs/SD114_DAY_TRADER_SECURITY_REVIEW.md`.

Genuine five-minute data remains an external owner/licensing gate. eToro Demo is the primary
broker and primary market-data candidate; Alpaca intraday acquisition is not the current plan.
The offline coverage-first request plan and fail-closed fixture parsers are in
`src/sidedeck/application/sd119_etoro_market_data.py`. No provider, endpoint, paid feed,
credential or authenticated request is implied by that code. The exact nine-GET review package is
`docs/SD115_INTRADAY_DATA_AUTHORIZATION_PROPOSAL.md`; it requires fresh owner authorization and
does not authorize orders or a transport unlock.

SD-120 is the prepared executable for that package. It is constrained to SPY/QQQ/MSFT discovery,
coverage and fixed five-minute samples, with SD-077 signature verification and persistent request
budgeting. It must stop on identity, entitlement, coverage or schema failure, and it must never
retry, paginate beyond the signed scope, read credentials before signature verification, or touch
the Demo trading transport. Review: `docs/SD120_ETORO_DISCOVERY_REVIEW.md`.

The Day Trader dashboard contract fix is a presentation/validation correction only. It does not
create research runs, genuine market evidence, strategy admission or execution authority. The
dashboard remains read-only; Demo execution remains governed by the separate SD-058 runbook and
transport gates.

## 19. Day Trader completion priority (owner directive 2026-10-27)

Complete the Day Trader research product before resuming autonomous gateway features. Scope:
build out its read-only dashboard and provenance-safe offline data pipeline; implement
research-only strategy backtests; provide a deterministic, synthetic end-to-end simulation
through scan, signal, SideDeck decision, authorized simulated order, fill, position management,
close and reconciliation; complete scheduling, restart recovery and audit trail; and fix the
Playwright CI installation stall without removing browser coverage. Retain all eleven installed
skills. Preserve `ETORO_DEMO NOT_RELEASED`, `RESEARCH_ONLY`, all existing kill-switch/HALTED
state and broker/data authorization gates. Synthetic simulation authorizations are confined to
offline acceptance and cannot produce a production permission or strategy admission. No
authenticated requests, provider spend, trades, or pilot checkout changes are in scope.


## 20. Continuous eToro Demo autonomy delivery loop (owner directive 2026-10-27; supersedes §19's sequencing)

**Primary objective:** finish one integrated, reproducible SideDeck path:
**licensed market data → qualified strategy → deterministic risk/portfolio decision →
signed bounded eToro Demo gateway → order acceptance → delayed/restarted broker
reconciliation → managed exits → protected-baseline and P&L reconciliation →
monitoring/soak**. An autonomous *development* loop is approved; autonomous
*broker order transmission* remains **NOT_RELEASED**. This directive supersedes
§19's instruction to complete every Day Trader UI task before advancing Demo
gateway engineering, but **does not override §§2, 7, 10, 15, 17, 18 or
`AGENTS.md` safety gates**. Avoid switching to new isolated apps, agents or
brokers when the integrated eToro Demo path can be improved offline.

### 20.1 Confirmed baseline — do not rediscover it

- **26 October 2026:** an owner-authorised MSFT **Demo** buy POST returned
  **HTTP 200** with an echoed reference ID and linked order ID. The owner saw a
  **0.09-unit** Demo position. The follow-up lookup by reference returned **404
  ~0.8 seconds after acceptance**; SideDeck **HALTED** and never automatically
  closed it. The owner subsequently closed the position manually.
- **27 October:** a separately owner-authorised read-only eToro Demo `/pnl`
  GET returned **200 / MATCHED**: all **four original protected positions**
  intact, no MSFT pilot position, no pending or unexplained positions. Closing
  price/P&L remain unverified; the historical pilot is **not** an automatically
  completed end-to-end trade. Pilot kill switch remains HALTED until the owner
  separately approves a recorded reset.
- Existing eToro key: **Demo environment, Read/Write permissions, expiry not
  defined**, reconfirmed by owner; canonical `ETORO_DEMO_TRADE_*` variable
  names, no legacy-name collision. **Do not ask to regenerate keys or repeat
  permission checks.**
- **AAPL market-data search alone** returned **HTTP 403** after a different
  signed one-GET diagnostic. Its two one-shot authorizations (earlier
  `FAILED:URLError`, later HTTP 403) remain **consumed**. Treat this as a
  **market-data endpoint/access issue**, not a failed Demo trading-key test.
  No repeat unauthorised probes; isolate a legitimately licensed feed.
- The historical supervised pilot's SD-105 delayed lookup and strict `/pnl`
  fallback are already implemented **offline**; SD-129/134/135 add separate
  transport-neutral recovery and close classification. Do not rebuild working
  contracts or mark offline simulation as live broker readiness.
- Current isolated engineering branch:
  `codex/sd122-etoro-data-autodemo-20261027`, draft PR #8. Reconcile actual
  branch HEAD and CI rather than assuming an older recorded SHA is current.

### 20.2 The run–verify–record–repeat algorithm

Within **each actively running Codex execution session**, repeat the loop
below without waiting for owner instructions between ordinary engineering
tasks. This is a deterministic **development workflow**, not an unattended
scheduler or permission to issue external orders.

1. **RECONCILE:** inspect `AGENTS.md`, this charter, the first "Autonomous
   eToro Demo delivery loop" section of `TODO.md`, the current worktree and
   branch, recent commits and exact-head GitHub Actions status. Read relevant
   SD-063/064/074/105/107/108/125/126/129/134/135 contracts before editing.
   Do not overwrite another worktree, credential file, consumed grant or the
   old pilot ledger. If a previously marked task has failed CI, reopen it.
2. **SELECT:** from TODO pick the highest-risk-reducing `READY` P0 task
   whose dependencies are verified. Select 2–5 related items per batch when
   practical, preferably a broker lifecycle task plus its failure-injection
   test/observability task. A queue item with unmet dependencies is not
   runnable even if queued `READY`. Never choose a `BLOCKED_OWNER` or
   `BLOCKED_EXTERNAL` task as if its external evidence exists.
3. **DESIGN:** write down pre/postconditions, durable identity, explicit
   broker-state transitions, request/write caps, quote freshness and exact
   rejection criteria. Add failing positive, negative, crash/restart and
   concurrency assertions first. Reuse existing SideDeck policy and adapters;
   do not make a parallel shadow execution stack.
4. **IMPLEMENT OFFLINE:** wire a narrowly typed adapter against **fake Demo
   transports**, sealed fixtures and disposable databases; no inherited API
   credentials, real network access, hidden fallbacks or principal impersonation.
   Keep real transport locked by default and refuse even an accidental order
   if owner release/grant/verified strategy/broker authority is absent.
5. **ATTACK THE IMPLEMENTATION:** test duplicate/replayed or lost POST,
   acceptance→404 lookup, by-orderId fallback, eventual fills, partial/multiple
   positions, out-of-order close, stale bid/ask, time-zone/DST/early close,
   quota exhaustion, service crash at every journal boundary, corrupt/tampered
   audit record, revocation, remote-anchor outage, incorrect portfolio
   attribution, unexpected baseline changes and Real-route injection.
   **No uncertainty may turn into a second write.**
6. **VERIFY:** focused tests, full pytest, Ruff, mypy, database migrations
   only on disposable SQLite/PostgreSQL, frontend typecheck/build/unit,
   relevant desktop/mobile Playwright, dependency/security and explicit
   locked-route tests. Record skipped unavailable infrastructure as
   `UNVERIFIED`, never `PASS`. Check the exact pushed commit in Actions;
   investigate red CI instead of using an older green run.
7. **RECORD:** make small reviewable commits on the authorized feature branch,
   push, link the exact successful CI run, and update TODO task status,
   acceptance evidence, negative cases and specific external blockers.
   Reconcile `SIDEDECK_STEERING.md`, `STEERING.md`, `AGENTS.md`, runbooks
   and PR description when requirements change. No merge to default branch,
   branch reset, force push, destructive cleanup or external deployment.
8. **REPEAT:** determine the next dependency-clearing batch and execute it
   **in the same active session** if tools/context permit. A green milestone
   is not an instruction to stop and ask "proceed." If one source is blocked,
   switch to a genuine unblocked workstream (durability, close safety, risk,
   data importer, strategy validation, UI or audits). Do **not** manufacture
   pointless work to create endless activity.
9. **HANDOFF:** at an actual session/tool limit or where all substantive
   remaining steps require owner/external action, leave an exact resumable
   TODO record with current branch/SHA/CI, what has been verified, next
   runnable task IDs, commands, locked permissions and **one consolidated
   bounded approval request** when necessary. Another Codex session may
   resume from the files without this conversation.

**Automatic stop conditions:** owner grants exhausted/expired/revoked;
unresolved orders or baseline drift; kill switch HALTED; missing genuine
data/admission; audit-anchor failure; strategy not admitted; uncontrolled
credential exposure; CI/security failure; unclear ownership/price; or
unauthorised broker/provider network access. Stop only the unsafe action;
continue offline work. Do not reset `.consumed` markers, journal rows, a
kill switch or a denied endpoint to make progress appear successful.

### 20.3 Dependency-directed delivery sequence (SD-136 through SD-151)

**Track A — Broker correctness, start now (offline; no user input):**
SD-136 audit the actual contracts, lock status and gaps; SD-137 connect
the SD-129/134/135 one-shot accepted-order recovery to the **durable**
SD-063/SD-074 journal across restarts; SD-138 implement the policy-bound
Demo-only transport adapter behind an invariant **hard network lock**,
independent SD-064 per-call signed grants, endpoint allowlists and durable
request/response reservation; SD-139 implement authoritative strict Demo
`/pnl` fill/close/attribution verification, no duplicate close and no
position ownership by ticker; SD-140 integrate exchange-session-aware
DAY/SWING/POSITION cycle scheduling, recovery and protective reduce-only
exits; SD-141 perform full crash/replay/partial fill/kill-switch and
cross-book/baseline threat testing.

**Track B — Data and strategy admission in parallel:** SD-142 build a
provider-neutral, licensed intraday importer and evidence contract (session,
timezone, bid/ask spread, volume, corporate actions, lag, gaps, adjustment
and provenance; no synthetic "live" bars). SD-143 identify/provision **only
by separately approved owner/provider scope** a genuine full-session
five-minute data feed; the eToro AAPL search 403 is not a reason to test
indefinitely. SD-144 perform leak-free walk-forward/locked-OOS strategy
admission (≥ 30 qualified locked-OOS trades for the current method, trading
costs, robustness, final holdout, no promotional fixture override). If the
genuine feed is absent, keep G1/G3 **BLOCKED** and fully exercise offline
schema and acceptance fixtures instead.

**Track C — Security and operations in parallel:** SD-145 connect grant-use,
policy ledger, revocation and order journal to fail-closed external
append-only/audited anchors in disposable tests; provisioning and
credentials for a real external store require a separate owner decision.
SD-146 review bounded release scopes, independent security report,
secret-safe telemetry, operator kill/reset/runbook, protective close under
expired entry grants and off-hours incidents. SD-147 build read-only Demo
readiness and reconciliation displays with actual broker status only when
the corresponding read has been authorised; synthetic runs remain
`SIMULATED_LOCAL`. SD-148 conduct restart/reconciliation operational
rehearsals and a multi-day **offline simulated** soak. Record degraded
outcomes, not just happy-path success.

**Track D — Explicitly external release and actual Demo:** SD-149 assemble
independently reviewed G0–G4 evidence, exact provider/data scope, signed
policy draft and per-route request limits; keep execution LOCKED.
SD-150 is the owner's **separate, specific, bounded, expiring eToro Demo
release** (virtual cash only, symbol/strategy/book/time/capital/order caps,
max-loss, end-of-day flatten, protective-exit authority, external audit
anchors, operator recovery); Codex cannot self-approve it. SD-151 is
owner-controlled, monitored limited Demo canary followed by the planned
one-month Demo soak, with signed scope renewals and an explicit stop on
ambiguity. No transition to eToro Real is permitted.

**Ordering discipline:** Finish dependency-unblocking A tasks while
building B/C offline. Don't ask for a Demo release before data, strategy
admission, code security, independent review and external anchors are
VERIFIED. A demonstration of Demo POST HTTP 200 from the historical MSFT
pilot is *access evidence*, not an autonomous go-live authorization.
`TODO.md` is the precise current assignment and owner of each gate.

### 20.4 One integrated lifecycle contract (definition of done)

Only the reviewed SideDeck decision/risk controller may promote an admitted
strategy proposal into a signed policy-bound order intent. Model/agent
recommendations never self-authorize. A production Demo route must:

- Persist `proposal_id → intent_id → referenceId → accepted_orderId →
  confirmed positionId → close referenceId → close orderId` with
  append-only provenance, monotonic transitions and reconciliation against
  real broker responses. Reconcile preexisting protected Demo holdings by
  fixed known baseline identifiers, never by ticker alone.
- Reserve before send, verify fresh planning **and send-time** quotes,
  instrument/side/leverage/fractional constraints, allowed order type,
  market-calendar window, virtual cash/exposure/position caps, time-limited
  owner signatures, strategy proof, grant revocation, ledger anchors,
  redaction and real-money prohibition on **every** request.
- An accepted POST is only `ACCEPTED`; follow up by bounded
  `referenceId` and linked `orderId` GETs (as observed, first referenceId
  404 may be transient), then a strict separately budgeted `/pnl` recovery.
  Unknown/partial/multi-position/contradictory cases remain `UNRESOLVED`,
  trigger halt and permit **read-only** investigation, never POST replay.
- A close is full **reduce-only**, uses only a broker-verified SideDeck-owned
  position and its independent protective authority. Broker close-info
  reporting FILLED is not proof of a flat reconciled portfolio; demand
  fresh `/pnl` (zero attributable position, no pending order, all four
  protected unchanged) and independently verified execution price before
  claiming net realised P&L. A manual operator close must never be
  fabricated as a SideDeck order.
- Enforce correct trading hours in `America/New_York` using exchange
  calendars, DST and early closes. DAY no-entry final 30 minutes and
  flatten 10 minutes before close; overdue overnight positions stop new
  entries and require an incident/recovery path. SWING/POSITION tracks
  retain their distinct approved holding horizons. No crypto, no leverage
  creep, no Real routes.
- On any uncertainty: no fresh entries, persistent HALTED incident,
  external alarm/visible operator status, fail-closed off-machine anchor;
  provide a separately recorded owner-authorised recovery or reset only
  after independent reconciliation.

**Release gates (not inherited from green tests):** G0 exact-HEAD CI and
security review; G1 licensed genuine 5m data validated; G2 evidence used
only as research unless its provider run is explicitly approved; G3
independently qualified strategy with costs and locked OOS; G4 signed
owner policy + grants + protective/recovery authority, verified 1:1
lineage and broker endpoints, immutable four-position baseline, durable
off-machine audit/revocation and independent acceptance tests; G5 monitored
Demo-only bounded canary and one-month soak. Each must be independently
marked `PASS`, `FAIL`, `BLOCKED` or `NOT_ASSESSED`; keep launch locked
until all prerequisites actually pass.

### 20.5 Machine-readable handoff convention (in TODO)

At the **top** of `TODO.md`, maintain a stable block with
`GOAL`, `REPO/BRANCH`, `LAST_VERIFIED_HEAD`, `EXACT_HEAD_CI`,
`BROKER_ROUTE`, `HISTORICAL_PILOT_KILL_SWITCH`, `G0–G5`,
`CURRENT_BATCH`, `NEXT_READY` and `BLOCKED_OWNER`/
`BLOCKED_EXTERNAL`. Reconcile it every cycle; never carry an outdated
SHA as "latest." Every SD-136…151 item requires priority, status, deps,
owner, acceptance, test/evidence, next action and whether real
provider/broker I/O is authorized. Keep existing TODO chronology intact.

**No background-work fiction:** this is a standing instruction for an
*active* Codex process. Writing steering/TODO does not schedule a worker,
start a daemon or grant continuous API access. To execute in another
session, the operator launches Codex in the authorised branch; the files
make that session self-directed without further routine conversation.
