# STEERING.md — SideDeck autonomous eToro Demo execution plan

**Active workstream:** build and verify the complete **autonomous eToro Demo trading application** in an iterative engineering loop. This is the concise entry point requested by the owner on **27 October 2026**.

**Authoritative policy:** [SIDEDECK_STEERING.md](SIDEDECK_STEERING.md), in particular **§20 — Continuous eToro Demo autonomy delivery loop**, together with [AGENTS.md](AGENTS.md). **Live task assignments:** the top **Autonomous eToro Demo delivery loop** block of [TODO.md](TODO.md). This entry point does not replace those documents or dilute their security rules.

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

## Implementation phases / acceptance gates

| Phase | TODO IDs | Key deliverable | Release state |
|---|---|---|---|
| A: recover and execute safely | SD-136–141 | Verified durable Demo gateway, lookup-404 recovery, no duplicated POST, strict close + /pnl, DAY exit schedule, failure tests | Offline only |
| B: data/strategy | SD-142–144 | Licensed provenance-checked full-session 5m feed and independent locked-OOS qualified signals | External gates retained |
| C: security/operations | SD-145–148 | Off-machine anchors, risk/kill-switch audits, clear UI, restart simulation and soak | Offline until approved |
| D: release/canary | SD-149–151 | Signed narrow Demo-only owner policy, monitored canary, one-month Demo soak | **Separate owner signature/approval required** |

## Non-negotiable status

- `ETORO_DEMO=NOT_RELEASED` / `broker_execution=DISABLED` until independent G0–G4 evidence and an explicit bounded owner release.
- **eToro Real NEVER**. No live, leveraged, unmanaged, paid, or unapproved account/network actions.
- Existing four Demo baseline positions protected; owner kill switch from the MSFT incident remains **HALTED** until a separately authorised reset.
- The two earlier AAPL signed diagnostic permissions are consumed; do not replay them or fabricate HTTP/price evidence.
- No duplicate writes, no simulated closing prices presented as broker P&L, no synthetic data silently promoted to strategy qualification, no grants signed by Codex.
- Do not merge default branches, touch other worktrees, or run destructive changes on personal/broker account databases.

**Start now with the first `NEXT_READY` work items in TODO.** See the authoritative charter §20 for the precise lifecycle contract, dependency DAG, test requirements and stop conditions.
