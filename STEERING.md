# STEERING.md — SideDeck autonomous eToro Demo execution plan

**Active workstream:** build and verify the complete **autonomous eToro Demo trading application** in an iterative engineering loop. This is the concise entry point requested by the owner on **27 October 2026**.

**Authoritative policy:** [SIDEDECK_STEERING.md](SIDEDECK_STEERING.md), in particular **§20 — Continuous engineering loop** and **§21 — Demo GO-LIVE delivery contract**, together with [AGENTS.md](AGENTS.md). **Critical-path implementation plan:** [docs/AUTONOMOUS_DEMO_EXECUTION_PLAN.md](docs/AUTONOMOUS_DEMO_EXECUTION_PLAN.md) — deliver one complete offline broker-shaped SWING round trip before feature expansion. **Live task assignments:** the top **Autonomous eToro Demo delivery loop** block of [TODO.md](TODO.md). This entry point does not replace those documents or dilute their security rules.

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

**Start now with SD-138:** implement a real offline-only SD-063/064/074/145-to-SD-129/036 autonomous adapter plus one end-to-end, broker-shaped **fake** entry → identified position → reduce-only exit → final /pnl reconciliation, with exact grant/quote/audit checks and negative tests. **Then SD-139/140/141/152** as dependencies clear; progress SD-143/144, SD-146/147/148 in parallel. See [critical-path plan](docs/AUTONOMOUS_DEMO_EXECUTION_PLAN.md), which does not authorize data access or broker execution. Follow charter §§20–21, commit/test/verify CI/update TODO, and continue implementation without routine prompts while the Codex session is active.
