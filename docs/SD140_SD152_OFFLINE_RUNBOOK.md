# SD-140 / SD-152 — first offline SWING service slice and recovery runbook

**As of 28 October 2026**. Initial implementation `fbd992a` passed [CI 40654151962](https://github.com/smbabalola/sidedeck/actions/runs/40654151962) (1,888 passed / 2 skipped). Subsequent SD-141 adversarial tests exposed a missing protective-monitoring HALT; fix `2353635` passed [exact-head CI 40654988053](https://github.com/smbabalola/sidedeck/actions/runs/40654988053): **1,892 passed / 2 skipped**, Ruff, mypy (206 files), Alembic, frontend and browser E2E. **28 October continuation:** SD-152 durable heartbeat, read-only local incident inspection and corrupt-fence refusal through code/test `d0f36af97b5d718a3755cc7eb1f2c06e9cea0bf6` passed [exact-head CI 40656371495](https://github.com/smbabalola/sidedeck/actions/runs/40656371495): **1,899 passed / 2 skipped**, Ruff, mypy (206 files), Alembic and browser E2E. **Not a release approval.**

## Boundary

- `sd140_offline_swing_controller.OfflineSwingCycleController` accepts exactly SD-074 authenticated runtime and the SD-138 fake-only adapter, never an arbitrary broker transport. All policy, owner-test-grant, quote, order/position lineage and audit checks stay in their existing modules. It does not admit new strategies and does not generate trading opportunities.
- `sd152_offline_swing_runner.OfflineSwingScheduledService` uses SD-068's existing `XNYS` `swing_review` job and requires explicit **SIMULATION_ONLY** configuration at both track and exchange levels. `RESEARCH_ONLY` (the default) is refused before a cycle.
- The separate SD-152 durable SQLite single-writer fence binds a unique `slot` and `token` before claiming the SD-068 scheduler job. A second process cannot claim an already running cycle or repeat a previously completed slot. A process crash leaves `RUNNING`; an ambiguous or failed cycle leaves `UNRESOLVED`. Neither state has an automatic expiry or takeover. This is a **fail-closed first slice**, not production-grade liveness/recovery.
- **SD-152 health and operator visibility (28 October continuation):** `OfflineSwingRunFence.heartbeat(token, owner, at)` updates SQLite only for the *current matching* worker, rejecting forged tokens, changed owners and regressing clocks. `OfflineSwingRunFence.health(now)` flags stale RUNNING workers and unresolved incidents; it never grants lease takeover or authorises another trade. `OfflineSwingScheduledService.inspect(now)` reports local policy kill, pending/unknown durable order counts and SideDeck-owned positions. **This is NOT independently broker-verified account health.** Malformed idle/worker records fail closed. No external alerts, live broker calls or reset facility were added.
- SWING exits have priority over entries; only the verified SideDeck-owned, full reduce-only close is allowed. No new entry when an exit was due, open positions are still being monitored, risk alerts appear, the kill switch is engaged, or a fresh independently sealed send quote is unavailable.
- The adapter is **simulation only**. The historical eToro Demo release is `NOT_RELEASED`; the owner kill switch remains `HALTED`. No API keys, broker or market-data requests, network clients, remote deployment or actual Demo orders are used or authorised.

## Recovery / operator protocol (offline only)

1. Inspect the read-only `OfflineSwingScheduledService.inspect(now)` and `OfflineSwingRunFence.health(now)` status, along with SD-068 `SchedulerStore.history("swing_review")`, SD-063 incidents and SD-129/036 durable lineage. **Stale heartbeat means investigate, never take over**; the local status is not an eToro /pnl read and cannot prove broker flatness.
2. If fence is `RUNNING` on startup or `UNRESOLVED` after a failed cycle, **stop further ticks**. Confirm which prior OPEN/CLOSE POST, if any, reached the fake broker. Use only independently scoped, audited GET-only recovery, never another POST with the same or a new identity for an ambiguous intent.
3. Reconcile any open or pending positions, exactly four original protected baseline positions, grants, anchors, fill/close evidence and policy HALT. Do not automatically clear the kill switch or overwrite the original baseline.
4. This slice **intentionally provides no automatic recovery/clear-unresolved action**. A future independently reviewed operator-only reconciliation + signed recovery protocol is required before safe unattended restart/deployment; hand-editing the SQLite fence is prohibited as an operational procedure.
5. Do not interpret a green offline run as a genuine strategy qualification, real broker economics or a live pilot.

## Verified test matrix

- Default locked mode cannot start a trading cycle.
- First SWING schedule opens one fake eToro Demo position through actual SD-063/064/074/145 and SD-138/129/036 composition.
- Duplicate same-slot replay across separate service handles is refused.
- A second scheduled session closes the position automatically on a verified stop with two distinct signed planning/send quotes; no close-and-reopen churn; four original simulated positions reconciled.
- Crashed first worker persists its run fence; another worker cannot take over or POST, even after a restart.
- Missing send quote produces HALT and durable `UNRESOLVED`; a later cycle is refused.
- Off-session, non-SWING proposal and no-signal cases send no order.
- No simulated P&L is presented as broker-authoritative.
- SD-141 extension: concurrent workers allow exactly one durable fence claim; lost close POST acknowledgement HALTs and remains non-replayable; audit-anchor outage during protective monitoring of an open position now **durably HALTs** rather than reporting only ATTENTION_REQUIRED; XNYS early-close swing review uses 13:00 ET close (not 16:00).
- SD-152 continued health tests: read-only IDLE/RUNNING/UNRESOLVED status; stale heartbeat does not permit takeover; forged worker/token and backward clock refused; absent durable run row blocks safe completion; read-only operator snapshot detects open/unknown lineage after a simulated lost-close ACK without any additional HTTP; contradictory IDLE fence rows cannot authorise a new cycle.

## Open engineering work — do not mark SD-140/152 complete

- SD-140: DAY/POSITION scheduling integration, exchange DST/half-day adversity, protective expiry renewal/close continuity and clock-fencing against revoked grants at send time. The SD-125/126 DAY offline logic already exists and must be reused.
- SD-141: a complete production-shaped fake HTTP threat matrix including mid-cycle worker death, stale leader, accepted->404 delayed recovery, unknown/multi/partial fills, revoked grants, anchor loss and baseline mutation.
- SD-152: **heartbeat and local read-only inspection now have first offline implementations**, but still need a continuously supervised service/CLI, independent alert delivery, read-only broker GET recovery protocol, operational dashboard, multi-session soak, independent worker/leader security review and externally immutable anchor deployment. Never auto-clear an uncertain RUNNING or UNRESOLVED fence.
- SD-143/144: Alpaca lawful historical data and independent true point-in-time swing strategy admission. New authenticated reads and subscriptions still need separate approval.
- SD-146/149/150/151: independent security/ops review, complete release dossier, signed owner-only Demo canary and observed one-month Demo soak.

**Next Codex batch:** SD-141 end-to-end adversarial offline tests and SD-140/152 scheduling/restart hardening. Continue on the same draft PR; never loosen the release gates.
