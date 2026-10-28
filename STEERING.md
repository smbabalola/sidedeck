# STEERING.md — SideDeck autonomous eToro Demo execution plan

**Active workstream:** build and verify the complete **autonomous eToro Demo trading application** in an iterative engineering loop. This is the concise entry point requested by the owner on **27 October 2026**.

**Authoritative policy:** [SIDEDECK_STEERING.md](SIDEDECK_STEERING.md), in particular **§20 — Continuous engineering loop** and **§21 — Demo GO-LIVE delivery contract**, together with [AGENTS.md](AGENTS.md). **Critical-path implementation plan:** [docs/AUTONOMOUS_DEMO_EXECUTION_PLAN.md](docs/AUTONOMOUS_DEMO_EXECUTION_PLAN.md) — deliver one complete offline broker-shaped SWING round trip before feature expansion. **Live task assignments:** the top **Autonomous eToro Demo delivery loop** block of [TODO.md](TODO.md). This entry point does not replace those documents or dilute their security rules.

## Current owner-priority bundle — finish the ORIGINAL Day Trader, no extensions (28 October)

This section sets execution priority within the existing rules; AGENTS.md and SIDEDECK_STEERING.md retain safety precedence. **Do not add modules, extensions, UI features, other trading strategies or separate brokers.** Do not interrupt the owner after every individual commit. Finish a coherent, verifiable batch before reporting. An active chat/agent session is not a background worker.

**One significant offline acceptance target:** the currently implemented five-minute ORB scanner consumes independently admissible source data, establishes a reproducible locked out-of-sample result (minimum 30 qualified OOS trades under the unchanged SD-071 gate), and passes a separately signed/admitted same-opportunity NATIVE_STRATEGY signal through the **existing** SD-154/074/063/126/107 pipeline: policy/risk-generated entry → simulated fill/owned position → stop or scheduled protective exit → final reconciled flat. Entry must not be manually constructed. Repeat/restart, stale/event-time, calendar/half-day, missing-bars, no-signal, forged admission, unknown/partial close, and protected-baseline tests must fail closed. Full exact-head CI is the acceptance evidence.

**Execute in this order, as ONE bundle:**
1. Reconcile current PR #8 head and full exact-head Python/browser CI. Fix actual regressions in current files and rerun; don't spin out unrelated tickets.
2. Inventory ONLY already-available, source-authorized five-minute historical data and existing SD-119/122/142/143 ingestion and SD-121 backtest evidence. Distinguish local files from GitHub-only access and actual rights from unverified owner text. Do not make provider calls or claim 1h discovery/daily SD-021 evidence is adequate.
3. When sufficient admissible data actually exists, run the **existing ORB** locked chronological/walk-forward + costs/spread/latency/slippage + robustness evaluation and independently reconcile >=30 genuine OOS closed trades. Record source coverage, rights, hashes and PASS/FAIL. Never auto-admit from synthetic/claimed performance.
4. Exercise the existing **qualified native ORB** → trusted sealed signal → admission/policy/risk → generated offline entry → exit/reconciliation integration, plus negative fault matrix. Do not manufacture production admission, signature, quote or P&L.
5. Commit reviewed code/test fixes only if required by steps 1–4, run complete Python/Ruff/mypy/migrations/frontend/browser verification, inspect exact-head GitHub Actions, and update the authoritative TODO **once per substantial bundle milestone** with evidence and remaining gates.
6. If genuine lawful five-minute coverage/permissions or independent OOS proof are absent, STOP the qualification portion as **BLOCKED_EXTERNAL / NO_TRADE**, stating precise missing artifacts. Do not fill missing data with fixtures, relax floor, or keep committing cosmetic safety tweaks to simulate progress. Request the one specific owner/provider decision that would unblock this bundle.

**Separate release boundary:** eToro Demo production transport remains `NOT_RELEASED`; historical HALT and the four protected baseline positions remain unchanged. No credentialed market/broker reads, order writes, grant signing, remote-anchor provisioning, kill-switch reset or Real activity is authorized here. After offline acceptance, independently reviewed evidence and a NEW scoped owner-signed Demo release are necessary; that is not covered by this bundle.

**Last confirmed HEAD:** `90d2a98e96e178b4abdb6f6f2f2cd2cddbcb8bf1` passed [CI 40729935762](https://github.com/smbabalola/sidedeck/actions/runs/40729935762). Synthetic SD-155 offline round trip passed previously. Genuine ORB data/OOS gate still BLOCKED_EXTERNAL.

## Mission

Deliver one integrated, reliable path from genuine licensed data and an independently admitted strategy, through signed deterministic risk and **eToro Demo-only** execution, to broker-confirmed entry, protective exits, reconciled closing positions, operator visibility and sustained Demo soak.

**Do not re-ask for confirmed eToro Demo key details.** The owner already demonstrated a successful supervised Demo **MSFT BUY HTTP 200**, then manually closed that position; a separate approved Demo portfolio GET returned **200 / MATCHED** with all four original holdings. A separate **AAPL market-data search** GET returned **403**. The latter is an endpoint-specific data-access issue, not proof the demonstrated Demo order capability stopped working.

## Active development loop

1. Read `AGENTS.md`, `SIDEDECK_STEERING.md` §20 and the active `TODO.md` loop board; reconcile actual HEAD, worktree and CI.
2. Choose the **highest-priority unblocked** TODO task with all dependencies verified; group related tasks and tests.
3. Implement against **offline fake broker transports / disposable stores**. Write failure-injection, replay, entitlement, market-session and protection tests. Reuse SideDeck's existing code; do not invent another trade engine.
4. Run focused and full suites, Ruff, mypy, disposable DB migrations, frontend unit/type/build, browser E2E and security/negative tests. Address red CI; accept only a green run on the exact pushed HEAD.
5. Commit/push isolated branch, log exact evidence and remaining blockers in TODO; update PR. Generate the next READY dependency-clearing batch and **repeat without waiting for a routine "proceed"** while the Codex session is active.
6. If blocked by data, entitlement, external audit infrastructure or owner signatures, stop only that action. Continue other safe offline tasks. Preserve a resumable handoff. A steering file **does not itself run in the background**.

## Current work allocation — multi-task bundles (28 October 2026)

**Execute larger coordinated batches, not one SD item per owner "proceed".** The authoritative full definitions, acceptance tests, dependencies, and stop rules are in [docs/SD153_BUNDLED_ENGINEERING_QUEUE.md](docs/SD153_BUNDLED_ENGINEERING_QUEUE.md). `TODO.md` remains the live status/evidence ledger. Use a **single writing owner per checkout/branch**, and verify the exact pushed commit after each testable integrated slice.

| Order | Bundle | Grouped work | Exit from offline engineering |
|---|---|---|---|
| **R — current** | Broker reliability + controlled recovery | **SD-138/139/141** with SD-145/152 checks | Fault/retry budgets, signed read-only operator recovery protocol, baseline + multi-ledger proof, no replay; independent security signoff **not self-claimed** |
| **O — next** | Autonomous operations + operator interface | **SD-140/152/147/148** | Multi-track session/DST/protective logic, single-writer offline service, read-only dashboard, multi-session chaos soak |
| **D — independent research** | Alpaca historical data + swing admission | **SD-143/144** with SD-142/014–022/071 | Reproducible lawful-data and out-of-sample `PASS/FAIL/BLOCKED`; never promote synthetic or insufficient research data |
| **G — independent gate** | Security review + unsigned release package | **SD-146/149** | Independent signed-off findings where actually verified, otherwise `NO_GO`; consolidate owner decisions |

**SD-150/151 are not bundled into autonomous engineering.** Demo release, external provider reads/deployment/spend, owner grant signature, historical HALT reset and any actual broker requests require **separate** scoped owner action. This work allocation grants none of them. Proceed to another unblocked offline bundle rather than asking for routine instruction when an external gate is pending. Each batch still requires green exact-head CI and an honest TODO update before claiming its verified code status.

## Five-lane GO-LIVE delivery sequence

Codex must progress **all dependency-ready offline lanes in parallel** (without asking for routine `proceed`), using the exact SD task IDs and evidence rules in [TODO.md](TODO.md):

1. **Data — SD-142/143:** provider-neutral validated full-session five-minute history, lawful feed rights and genuinely timely execution prices. Evaluate Alpaca as **data-only** alongside eToro/other suppliers; neither availability nor licence is presumed. Provider access or spend is separately owner-approved.
2. **Strategy — SD-144:** admit **one** reproducible genuine-data strategy with locked out-of-sample evidence, ≥30 qualified OOS trades under current rules and realistic costs. Only independently admitted strategies can propose executable intents.
3. **Broker — SD-137–141:** complete durable restart-safe Demo buy/fill/close, independent signed network policy, orderId recovery after transient 404, strict /pnl settlement, protected four-position baseline and crash/partial/duplicate fault tests. Keep transport LOCKED while building.
4. **Always-on safety — SD-145–149 and new SD-152:** off-machine audit/grant anchors, security review, read-only operator status, durable single-writer scheduler with alerts and safe restart, simulated multi-day soak and independently reviewed release dossier.
5. **Signed Demo launch — SD-150/151:** the human owner signs a bounded, expiring policy and any required kill-switch reset. Approved service executes **one** automatic Demo opening and full confirmed closing (not manual), verifies fresh /pnl and protected baseline 4/4, then completes a one-month Demo-only soak with separately approved renewals.

**Illustrative canary numbers, NOT approval:** $1,000 virtual allocation, $100 max notional, $10 daily-loss limit, one new entry/day, one strategy and symbol, one position, long-only 1×. Existing stricter ceilings and eToro minimums take precedence until reconciled and signed; do not activate the illustration. Prepare one consolidated owner decision package at real data, remote anchor, and execution release hinges only.

**Unattended means an engineered, externally released SD-152 service, not a perpetually running Codex/chat session.** Service must default to `NOT_RELEASED`, fence concurrent workers, respect market hours and never submit a duplicate request after an ambiguous outcome.

## Implementation phases / acceptance gates

| Phase | TODO IDs | Key deliverable | Release state |
|---|---|---|---|
| A: recover and execute safely | SD-136–141 | Verified durable Demo gateway, lookup-404 recovery, no duplicated POST, strict close + /pnl, DAY exit schedule, failure tests | Offline only |
| B: data/strategy | SD-142–144 | Licensed provenance-checked full-session 5m feed and independent locked-OOS qualified signals | External gates retained |
| C: security/operations | SD-145–148 | Off-machine anchors, risk/kill-switch audits, clear UI, restart simulation and soak | Offline until approved |
| D: release/canary | SD-149–151 | Independent review, signed narrow Demo-only owner policy, one fully autonomous reconciled canary, then one-month Demo soak | **Separate owner signature/approval required** |
| E: unattended runtime | SD-152 | Fenced single-writer service, signed-policy startup gate, durable restart/alerts, multi-session fake-broker testing | Offline only until authorised deployment |

## Non-negotiable status

- `ETORO_DEMO=NOT_RELEASED` / `broker_execution=DISABLED` until independent G0–G4 evidence and an explicit bounded owner release.
- **eToro Real NEVER**. No live, leveraged, unmanaged, paid, or unapproved account/network actions.
- Existing four Demo baseline positions protected; owner kill switch from the MSFT incident remains **HALTED** until a separately authorised reset.
- The two earlier AAPL signed diagnostic permissions are consumed; do not replay them or fabricate HTTP/price evidence.
- No duplicate writes, no simulated closing prices presented as broker P&L, no synthetic data silently promoted to strategy qualification, no grants signed by Codex.
- Do not merge default branches, touch other worktrees, or run destructive changes on personal/broker account databases.

**Start with Bundle R's unclosed work, not another SD-138 rebuild.** The basic fake broker round trip and SD-140/152 offline SWING first slice have already passed tests. Next complete the *remaining* SD-141 recovery budgets, operator-only dry-run evidence and independent-review finding register; then advance Bundle O's missing multi-track operations and Bundle D's lawful evidence in parallel as interfaces permit. [Bundled engineering queue](docs/SD153_BUNDLED_ENGINEERING_QUEUE.md) and [critical-path plan](docs/AUTONOMOUS_DEMO_EXECUTION_PLAN.md) govern scope, with current truth in TODO. No outside I/O, owner release, signed recovery action or HALT reset is authorised. Follow charter §§20–21, run exact-head CI, document evidence and continue through unblocked grouped slices during an active Codex session.

## ORB research batch acceptance (28 October 2026)

- Keep all verified SPY 5Min SIP files immutable and bound to their SHA-256; no synthetic bars may substitute for actual research performance.
- Existing `sd078` inspector checks exact NYSE session grids, executes existing native ORB rule, reports conservative next-bar entries, last-bar-open EOD proxy, range-low stop, stressed slippage/fees, R outcomes and chronological 60/40 holdout.
- A 5-session sample (4 completed historical trades) remains INSUFFICIENT_DATA; neither this sample nor gross-positive results authorize auto trading. Require at least 30 **out-of-sample** completed trades and independent validation of execution assumptions before reconsidering admission.
- Acquire larger sample only through new owner-signed, exact-scope, single-use Alpaca data authorization. Keep used authorization markers untouched; do not make unapproved requests. Existing eToro Demo execution stays DISABLED.
- Work in integrated batches (implementation, focused regression, full CI, evidence) and only request human input for the signing/external-account boundary.
