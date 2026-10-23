# SD-074 operator incident runbook — autonomous eToro Demo policy

**Scope:** the SD-063/SD-074 autonomous Demo runtime. It is offline and **not wired to the broker**;
this runbook is written now so the procedures exist and are tested before any release. eToro Real
is never in scope. Nothing here authorizes an order.

## 1. Get the report

`AutonomousDemoRuntime.incident_report()` returns, without changing any state:

| Field | Meaning |
|---|---|
| `status` | `OK` or `ACTION_REQUIRED` |
| `kill_switch` | entries blocked for this policy (permanent; exits still run) |
| `policy_active`, `grant_valid`, `protective_exit_authority` | which authority can still propose exits |
| `open_positions` | positions recorded in the ledger (reference, instrument, units, stop) |
| `unresolved_*`, `quarantined_*` | proposals whose broker outcome is unknown |
| `unknown_quarantined_references` | references seen only in a recovered anchor |
| `owner_actions` | the concrete steps below, per item |

Every exit plan also writes alerts (`UNRESOLVED_ENTRY:…`, `QUARANTINED_ENTRY:…`, `EXIT_UNRESOLVED:…`,
`POLICY_EXPIRED_POSITION_OPEN:…`, `GRANT_NOT_VALID_POSITION_OPEN:…`, `KILL_SWITCH_ENGAGED`) to the
ledger, once per code per session.

## 2. Missing fill (entry UNRESOLVED or QUARANTINED)

The order may or may not exist at eToro. Its reservation stays counted and the kill-switch is on.

1. In the eToro **Demo** UI or through the approved lookup path, find the order by the SideDeck
   reference (`referenceId` → `orderId` → `positionId`).
2. Have the broker-reconciliation adapter seal what it found (outcome, units, average price, fill
   time, broker order id, SHA-256 of the lookup response) and call
   `AuthenticatedRuntime.reconcile_unknown(fill_envelope)`.
3. Operator approval alone never creates or removes a position: only sealed reconciliation
   evidence that passes the fill bands (entry price in (stop, limit], fill within 15 min of the
   proposal) is accepted.
4. If a position exists but no exit authority remains, close it manually in the Demo UI, then
   record that close the same way.

## 3. Unverified position (exists at the broker, not in the ledger)

Positions are owned only through verified order → position lineage, never by ticker. Do not attach
it to the policy. Close it manually in the Demo UI if it is not one of the four protected baseline
positions (which SideDeck must never touch), and record an incident note.

## 4. Interrupted close (exit UNRESOLVED or QUARANTINED)

No further exit is proposed for that position (a second close could double-sell).

1. Check in the Demo UI whether the close executed (fully, partly, not at all).
2. Record the result with `reconcile_unknown` from a sealed reconciliation envelope.
3. If the position is still open and the policy cannot exit it, close it manually.

## 5. Policy expired or grant revoked with positions open

Exits need an authority. Either sign a **protective-exit grant** (SD-064 `autonomous_policy` kind,
subject `protective_subject(policy)`, window starting no earlier than the policy, at most 7 days)
— it allows reduce-only exits and never entries — or close the positions manually.

## 6. Ledger will not open

- "does not match its anchor": run `PolicyLedger.inspect_recovery(anchor)`, read every row, then
  `recover_last_transaction(..., expected_head=<head you checked>)`. Recovery never trusts the
  anchored rows as state: it quarantines them and trips the kill-switch. Then follow §2–§4 for each
  quarantined reference.
- "triggers are missing", "hash chain is broken", "anchor exists without its ledger": treat as
  tampering. Stop the policy, keep both files, revoke the grant (`UnlockAuthority.revoke`), and
  reconcile every position from the broker by hand.

## 7. After any incident

The kill-switch stays on for the rest of the policy. Resuming entries needs a **new** owner-signed
policy and grant after the incident is closed.
