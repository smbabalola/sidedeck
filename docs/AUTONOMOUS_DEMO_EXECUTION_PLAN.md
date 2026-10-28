# SideDeck — Critical-path plan to autonomous eToro Demo

**Plan date:** 2026-10-28  
**Branch:** `codex/sd122-etoro-data-autodemo-20261027` | **draft PR:** #8  
**Baseline:** verified offline SD-136/137/142/145; SD-138 IN_PROGRESS; SD-152 QUEUED; last inspected HEAD `ae47e56e9e38c18003d0b0483c78f0856f244a15` and [CI 40563563249 PASS](https://github.com/smbabalola/sidedeck/actions/runs/40563563249).  
**Authority:** subordinate to `AGENTS.md`, `STEERING.md`, `SIDEDECK_STEERING.md` §§20–21 and the live `TODO.md`. This plan **does not** grant network access, data entitlements, kill reset, trading authority or an autonomous background Codex session.

## Current execution allocation superseding initial "NOW" steps (28 October 2026)

This document records the **original critical path**, including its initial SD-138 fake round-trip objective, which is now **implemented and CI-verified offline**; it should not send Codex back to rebuild that objective. The current coordinated work allocation is [SD-153 bundled engineering queue](SD153_BUNDLED_ENGINEERING_QUEUE.md), controlled by [STEERING.md](../STEERING.md) and live [TODO.md](../TODO.md):

- **R first:** SD-138/139/141 signed recovery fault coverage and independent-review readiness.
- **O next:** SD-140/152/147/148 multi-track offline operations, read-only UI and soak.
- **D independent:** SD-143/144 Alpaca lawful-data and genuine out-of-sample swing qualification, no new reads.
- **G independent review:** SD-146/149 security/release evidence; human-only SD-150/151 remain separately blocked.

Last confirmed code/test evidence at bundle creation: `419e324` [CI 40664791594 PASS](https://github.com/smbabalola/sidedeck/actions/runs/40664791594), 1,932 Python passed / 2 skipped. Do not confuse an offline green test or this work allocation with broker/market-data permission, owner kill-switch reset or autonomous deployment. **Treat the subsequent "Concrete next Codex batch" below as superseded historical instructions**, while retaining its security expectations and lifecycle contract.

## Decision: deliver ONE vertical slice before broad feature expansion

**First delivery target:** one end-to-end **offline** broker-shaped, automated **SWING** trade (not an intraday scalper): one admitted-strategy fixture → policy and signed-grant test fixtures → *distinct* sealed planning/send quote → durable reserve → exactly one fake eToro Demo OPEN POST → accepted-order lookup and verified owned position → stop/horizon/expiry-driven full reduce-only CLOSE POST → broker close-info plus independent fresh /pnl → flat SideDeck position, original 4/4 baseline positions unchanged, all counters and audit checkpoints verified, and honest simulated economics. Repeat with restarts, 404 fallbacks, revoked grants, partial/unknown fills and audit outages. **This is a simulator acceptance gate, not strategy admission or actual Demo brokerage evidence.**

After that, qualify a real data/strategy path and a locked unattended runner before preparing any actual Demo order release. Avoid writing another trading engine or treating the old supervised `PilotRelease` as an autonomous SD-064 grant.

## Work packages and critical path

| Milestone | Work | Parallelism / owner | Hard acceptance evidence | Status until evidenced |
|---|---|---|---|---|
| **M1. Integrated fake broker round trip** | **SD-138 + SD-139:** wire `SD-063/064/074/145` into the typed `SD-129` durable `SD-036` broker port. Separate autonomous route, Demo-only endpoint allowlist and locked production adapter; no use of old supervised `PilotRelease`. Broker-owned OPEN, reduce-only CLOSE, strict independently read /pnl, no simulated P&L promoted to broker-confirmed. | Codex now; no external I/O | Executable single-path integration test, one POST per intent over restart/concurrent worker, 4 baseline IDs immutable, exact ref/order/position IDs, grant budget/expiry/revocation, sealed quote, audit checkpoint BEFORE each send, fresh final /pnl. | SD-138 IN_PROGRESS; SD-139 awaits full M1 |
| **M2. Controlled autonomous runner** | **SD-140 + SD-152:** one durable leader, calendar-aware SWING review cadence, persistent schedule, safe restart and kill-switch recovery, protective stop/exit prioritisation, alerts, and default-locked startup. DAY/POSITION lanes must not bypass their own gates. | Codex after M1 contract; scheduler unit tests may start in parallel | Fake multi-session run without a human-triggered step; no duplicate sends after crash; closed/unknown positions clearly distinguished; no broker call during import/startup/healthcheck. | QUEUED / offline |
| **M3. Real data + one admitted strategy** | **SD-143 + SD-144:** use existing Alpaca SIP research evidence first, verify entitlements/rights and broker-specific execution-price path on eToro Demo; retrieve new data only under a narrow approved scope. For first SWING canary, formally decide whether daily bars suffice for strategy admission and fresh eToro rates suffice for execution; if changing existing mandatory 5m gate, require reviewed track-specific policy change and fresh negative tests—**never silently bypass** current requirements. Lock OOS and demonstrate ≥30 qualified OOS trades under current approved rule, costs and sensitivity. | Codex offline comparison and fixture validation in parallel with M1/M2; owner/provider approval before API reads or spend | Versioned licence/entitlement and timestamps, lawful storage/cross-broker use, independently replayable adjusted bars, quote-freshness test, immutable strategy hash and independent OOS PASS. If no qualified strategy: NO_GO. | BLOCKED_EXTERNAL until verified |
| **M4. Security/operational release readiness** | **SD-141 + SD-146/147/148/149:** adversarial whole-lifecycle fault matrix; independent review; read-only ops dashboard; external append-only audit deployment (SD-145 design already VERIFIED_OFFLINE, deployment not); multi-session offline soak and unsigned release dossier. | Offline tests/UI in parallel; audit-host provisioning owner decision | Exact-head green CI with full Python, type/lint, migrations, dashboard/browser; documented red/green fault matrix, independent reviewer findings closed, 4/4 baseline invariant, incident runbooks, off-machine anchor proof and signed scope draft. | NO_GO until complete |
| **M5. One actual Demo canary** | **SD-150 + first SD-151:** owner reviews a single restricted eToro Demo-only release, separately authorises required credentialed reads, off-machine audit host, grant/signature and any HALTED reset; approved operator monitors first automatically OPENED **and automatically CLOSED** position. | Owner controls approval; never Codex self-sign | Real broker order/position/close IDs, independent execution price and fee proof if available, final fresh /pnl flat + zero pending + 4 protected positions unchanged; unknown result = UNRESOLVED/HALT, not success. | BLOCKED_OWNER |
| **M6. Monitored trial** | Remainder of **SD-151:** one-month Demo-only soak; new grants for each expiring window; incident review, real-vs-sim separation and return statistics. | Approved operator + owner | Observed broker/audit evidence, compliance with caps and runbooks; final GO/NO_GO review. No eToro Real. | NOT_STARTED |

### Primary order of implementation

1. **NOW — SD-138 integration:** create a *production-shaped but offline-only* `AutonomousDemoRoute` composition around existing SD-107 gateway/SD-063 policy, SD-064 authority, SD-074 verified inputs, SD-145 external anchor and SD-129/036 lineage. Reuse implementations and exactly one durable outbound intent identity. Identify and fix any split-brain between policy-ledger and order-lineage reservations. Test an autonomous signed-grant **fake** POST and assert zero unsanctioned HTTP capability.
2. **THEN — SD-139 close safety:** accept only identified SideDeck-owned `positionId`, mandatory reduce-only full units, close-info + independently sourced final /pnl, unknown executions remain fenced, no invented realized economics.
3. **THEN — SD-140/152 unattended service:** complete one market-session-aware SWING workflow with persistent single-writer fencing and logged incidents across a fake restart. For SWING holds beyond seven calendar days, **resolve the current seven-day owner grant maximum** through separately approved renewals and protective-close continuity BEFORE entering a longer-lived position. No silent expiry extensions.
4. **THEN — SD-141 and offline multi-session soak**, while SD-143/144 data source and genuine strategy qualification, SD-147 dashboard, SD-145 deployment design and independent review proceed as dependency-ready parallel work.
5. **FINALLY — SD-149 release dossier → owner SD-150 → one actual eToro Demo canary SD-151 → observed Demo-only trial.**

### Concrete next Codex batch (not a status-only session)

- Inspect `sd107_demo_gateway.py`, `sd129_etoro_demo_order_port.py`, `sd036_etoro_demo_desk.py`, `sd063_autonomous_demo_policy.py`, `sd064_unlock_grant.py`, `sd074_trusted_inputs.py`, `sd145_audit_journal.py`, `sd048` supervised transport and existing contract tests.
- Implement a **separate strictly locked autonomous route** with real SD-064 grant enforcement and an audit checkpoint before every fake broker call, avoiding passing `PilotRelease` as a stand-in. The fake route must test the production-shaped order body and GET/POST allowlist, but cannot create a real urllib client or get credentials.
- Use exactly one deterministic fixture with OPEN → acceptedId → linked positionId → exit → close-info → final /pnl; persist and assert referenceId/orderId/positionId chains and baseline preservation.
- Add negative tests **before** expanding: no/revoked/expired grant, changed signed policy, stale/missing sealed quote, unauthorized side/Real path, no audit anchor, crash between reserve/send/ACK, competing workers and post-restart replay. Assert zero fake opener POST for refusals and one maximum for ambiguous sends; never clear HALTED automatically.
- Run focused/full suites, Ruff, mypy, disposable migrations and browser E2E; commit/push, inspect **exact-head** CI, record proof in `TODO.md`, and continue SD-139. If complete integration is too large for one batch, commit a small test-backed code slice with precisely specified next method/interface, **not another review-only commit**.

### Decision log — what the owner must approve, and when

| Decision | Trigger | Do not infer |
|---|---|---|
| **A. Data and pricing scope** | SD-143 provider terms and exact instrument/time/endpoint/read budget ready | Prior Alpaca SIP evidence or eToro Demo keys do **not** grant new API reads, paid calls, storage/redistribution or cross-broker rights. Prefer approved existing Alpaca historical data; ask whether a daily-bar SWING path can be formally qualified without upgrading to paid 5m/live SIP. |
| **B. External audit/operations** | Tested SD-145/152 external immutable storage and operator proposal ready | Local directory fixture is not external immutable proof; no deployment/credential/spend permission. |
| **C. Narrow Demo canary** | All engineering, genuinely admitted strategy, operational review and audit gates independently PASS | Existing supervised MSFT buy, manually closed position, earlier diagnostic grants, owner credentials and current `HALTED` state are **not** an autonomous release. Owner signs exact scope and separate protective-exit authority. |

### Non-negotiable stop conditions and status truth

- `ETORO_DEMO=NOT_RELEASED`, `NETWORK_TRANSPORT_ENABLED=False`, historical kill-switch `HALTED`, four original Demo positions untouchable. Never send to eToro Real.
- A broker POST HTTP 200 is **acceptance**, not fill. `/pnl` absence or reduction is **observation**, not proof SideDeck executed a close or its realized price/fee/P&L.
- No live provider or broker GET/POST without a new specific approval; no self-signed grant, unauthorized deployment or repeated denied AAPL market-data endpoint.
- Failure cases must halt only unsafe actions while offline engineering can continue. Never reopen an ambiguous close by resubmitting it.
- The term **AUTONOMOUS_DEMO_READY** may be used only after M1–M4 gates, independent security verification, genuine strategy admission, and complete owner-reviewable release package. **AUTONOMOUS_DEMO_TRADING** only after owner-signed M5 activation and actual broker evidence.

**Engineering loop:** in each active Codex session RECONCILE HEAD/CI → SELECT highest-impact ready slice → IMPLEMENT offline → ADVERSARIAL TEST → FIX → FULL VERIFY → COMMIT/PUSH → EXACT-HEAD CI → UPDATE TODO/PR → CONTINUE. The steering text does not run Codex in the background.
