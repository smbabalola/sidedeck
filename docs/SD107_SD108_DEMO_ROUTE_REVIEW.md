# SD-107 / SD-108 / SD-074F offline execution review

**Review date:** 2026-10-26  
**Reviewed head:** `1ab31918f45241342e789a98144c6aedad1d64a2`  
**Scope:** signed permission checks, duplicate execution, reconciliation lineage, restart recovery,
protective exits, and the DAY-track gate. This review covers the deterministic local simulator and
offline adapters. It does not validate any production broker transport.

## Findings

| Severity | Finding | Resolution / evidence |
|---|---|---|
| High, fixed | The simulator kept accepted orders and positions only in memory. After a process interruption, the caller could not recover the accepted reference and order state. | Simulator now persists open/close orders and positions in SQLite. Unique order references make repeated simulator writes idempotent. `recover_entry` and `recover_exit` perform read-only reconciliation. Restart tests interrupt after durable open and close acceptance, restart the simulator, reconcile without a second write, and confirm the kill switch remains engaged. |
| No new critical/high finding | Ordinary and protective grants are checked for their own subject digest and request/write budgets. Writes require a fresh single-use reference; ambiguous outcomes are not retried. Entry requests match the durable proposal and undergo send-time quote, exposure, loss and order-cap checks. | `tests/test_sd063_autonomous_demo_policy.py`, `tests/test_sd064_unlock_grant.py`, `tests/test_sd074_trusted_inputs.py`. |
| Existing security decision preserved | Revoking the ordinary policy grant while its signed time window remains open must not trigger an automatic liquidation. A separate protective grant authorizes reduce-only exits after policy expiry. | The existing `test_revocation_never_triggers_a_protective_liquidation` regression remains green. No code path resets the kill switch during recovery. |
| Release blocker | The production grant-use ledger has no provisioned off-machine anchor. The local write-once directory only anchors the SD-063 policy ledger in tests. | No production route can be released until both ledgers have provisioned, independently verified off-machine anchoring. |
| Release blocker | Broker close-info lacks a validated execution price; multiple broker position IDs cannot be represented by the current ledger. | Such evidence remains `UNRESOLVED`; manual reconciliation is required. No fill is fabricated. |
| External gate | SD-063 rejects DAY policies without approved intraday data. The Day Trader skill emits research proposals and no native DAY strategy has passed independent admission. | DAY stays blocked. This change does not weaken the data or strategy-admission gates. |

## Permission, duplicate and reconciliation checks

- `ETORO_DEMO` remains `NOT_RELEASED`; no authenticated requests, broker orders, or pilot-state
  changes occurred.
- Broker acceptance is never treated as a fill. Fill envelopes bind proposal reference, order ID,
  response digest and (for fills) broker position ID. Close evidence must match that same position.
- Repeated/resolved entry proposals are refused before a second simulator write. The simulator
  enforces a SQLite unique constraint on order reference; recovery uses lookup-only methods.
- Failed, malformed or ambiguous results halt the policy and are not retried. Recovery can record
  a verified local simulated result without clearing the halt.
- Protective exits are full reduce-only closes of lineage-verified positions, require a separate
  signed grant, fresh quote and policy-ledger publish gate, and are available after policy expiry.

## Verification

- Local full suite: **1,677 passed, 3 skipped**, 3 existing SQLite datetime-adapter deprecation
  warnings.
- Focused SD-063/074/107/108 suite: **156 passed**.
- Ruff passed; mypy passed across 192 source files.
- Exact-head GitHub CI: [run 40382189385](https://github.com/smbabalola/sidedeck/actions/runs/40382189385)
  passed on the reviewed head. Existing runner warnings: Node.js 20 action deprecation and the
  announced `ubuntu-latest` migration to Ubuntu 26.

## Remaining independent evidence

The simulator tests establish only local deterministic persistence and recovery. Before release,
an independent reviewer must assess the full production transport, both external anchoring
mechanisms, broker idempotency for opens and closes, and operational recovery against a Demo
account. Owner-signed policy/release and DAY data/admission remain separate gates.
