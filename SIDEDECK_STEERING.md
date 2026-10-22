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

