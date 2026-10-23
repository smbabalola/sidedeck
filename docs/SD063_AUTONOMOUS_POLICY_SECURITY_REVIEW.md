# SD-063 autonomous eToro Demo policy — independent security review

**Status:** remediated offline; **not released**. The USD 1000 / 7-day figures are design
ceilings, not an authorized allocation. No autonomous broker execution exists: SD-063 holds no
transport, credentials or network access, and it is not wired to the order path (SD-074).

| | |
|---|---|
| Reviewed commit | `11fc7a7` (SD-063 v1) |
| Remediated in | SD-063 v2, policy schema `sidedeck-autonomous-demo-policy/2` |
| Reviewer | separate read-only reviewer agent (no repo writes, no network, no `.env`) |
| Method | source and interface inspection, executed repro scripts, re-verification of the fixes |
| Code | `src/sidedeck/application/sd063_autonomous_demo_policy.py` |
| Tests | `tests/test_sd063_autonomous_demo_policy.py` (84; regression tests `test_f*`, `test_n*`) |

## Summary

v1 validated the policy document well but trusted nearly every runtime input: decisions,
admissions, positions, equity and time came from the caller; no SD-064 grant was checked; the
ledger had no concurrency control or tamper evidence; exits stopped under the kill-switch.
v2 is a runtime object (`AutonomousDemoRuntime`) that re-verifies the signed grant on every call,
runs the decision engine itself, derives positions/exposure/equity from its own hash-chained
ledger and serialises every operation.

## Findings and status (after re-verification)

| ID | Sev. | Finding (v1) | v2 status |
|---|---|---|---|
| F1 | CRITICAL | Revoked/expired/absent SD-064 grant did not stop proposals; caller-supplied `now` | **FIXED** — `UnlockAuthority.check` + `check_grant_binding` (issuer, kind, digest, equal window) on every call; runtime clock only |
| F2 | CRITICAL | Decision, admission and NATIVE signals forgeable by the caller | **PARTIALLY FIXED** — SD-063 runs `decide()` itself; strategy counts only if its evidence file (inside `evidence_root`) hashes to the owner-signed SHA-256 and an ADMITTED admission cites it. Residual R1 |
| F3 | HIGH | No exposure accounting; USD 1000 not enforced at runtime | **FIXED** — positions, fills, pending + UNRESOLVED reservations, cash, realized P&L from the ledger; open + pending ≤ track capital; one position per instrument |
| F4 | HIGH | TOCTOU race across workers | **FIXED** — `BEGIN IMMEDIATE` around every operation; integrity re-verified in the transaction; 3-worker test |
| F5 | HIGH | Exits trusted caller positions; repeat exits after a fill | **FIXED** — exits only for ledger positions, units = filled − exited; pending exit blocks a duplicate |
| F6 | HIGH | Kill-switch blocked protective exits | **FIXED** — blocks entries only; reduce-only exits continue with an alert |
| F7 | HIGH | Positions stranded at weekend/holiday expiry; entries inside flatten window | **FIXED** — flatten from 1 h before the last full XNYS session close inside the window; entries stop at that session's open; window without a full session refused; post-expiry alert |
| F8 | MEDIUM | No tamper evidence; deleting rows/file reset the kill-switch | **FIXED** — hash chain + separate anchor file; dropped triggers, edited/deleted rows, deleted ledger, stale anchor fail closed. Residual R3 |
| F9 | MEDIUM | Caller-trusted equity; no cumulative loss limit | **PARTIALLY FIXED** — equity from ledger + marks, `max_loss_pct`, missing mark refused. Residual R2 |
| F10 | MEDIUM | No stop/horizon/ask sanity; numeric crashes | **FIXED** — stop ≤ 25 % below limit, horizon within track bounds, ask within 2 % of decision price, min notional; numeric errors → refusal |
| F11 | LOW | Calendar gap suppressed a stop | **FIXED** — stop evaluated before calendar math |
| F12 | LOW | Unsanitised references in audit log | **FIXED** — reference format validated; details JSON-encoded |
| F13 | LOW | Protected set could be empty | **FIXED** — must be non-empty |
| F14 | PLAUSIBLE | Anyone with a ledger handle can resolve a live entry | **OPEN** — residual R4 |

New issues raised by the re-verification of v2:

| ID | Sev. | Finding | Status |
|---|---|---|---|
| N1 | MEDIUM | Reconciliation fill price/time unbounded | **FIXED** — entry fill in (stop, limit] within 15 min of the proposal; exit fill within 10 % of the planned bid; resolution never before the proposal |
| N2 | MEDIUM | Crash between anchor write and COMMIT bricked the ledger | **FIXED (after third pass)** — the anchor holds a write-ahead copy of the last transaction's rows; owner-run `recover_last_transaction` takes the write lock, checks the rows chain from the ledger head to the anchor head, **replays** them (multi-row transactions included) and trips the kill-switch. The third pass had shown that a first version (discard and accept "one append ahead") could hide a deleted last row and could not recover multi-row transactions (N2-A/N2-B/N2-C); deleting the last transaction now restores it (`test_n2_deleted_last_transaction_is_restored_not_hidden`) |
| N3 | LOW-MED | Caller marks can hide unrealized loss | **OPEN** — residual R2 |
| N4 | LOW | Daily-loss baseline taken late; marks grew the ledger on every call | **FIXED** — first mark per session written before the decision; further marks only on a new high |
| N5 | LOW | UNRESOLVED exit or revoked grant leaves only alerts | **BY DESIGN** — the order may have executed / privilege was removed; owner close runbook required (R5) |
| N6 | LOW | Evidence checked by hash only, read fully each call | **OPEN** — residual R1 |

Sixth independent pass (on `d13024b`): **N2-D FIXED** — anchor-only forgeries stay inert data;
no position, fill, exit or P&L can be forged; the kill-switch cannot be cleared; malformed
quarantine content did not break `state()`. Remaining (accepted for the offline stage, tracked):
- **R8 (MEDIUM) Lost fill → QUARANTINED entry is alert-only**, not stop/flatten-managed. Accepted
  fail-safe (trusting the anchored fill is exactly the N2-D forgery); bounded by
  `max_position_notional`, the ≤ 7-day grant and the unwired transport. Required before release:
  owner-facing notice (not only ledger alerts) and runbook R5; optional owner-confirmed protective
  close proposals for quarantined entries.
- **R9 (LOW-MEDIUM)** an owner-confirmed recovery can be aimed at genuine pending references,
  leaving them reserved/unresolvable for the policy; needs an owner-run, broker-checked
  `resolve_quarantined` operation.
- **LOW:** a second recovery after deleting the quarantine transaction loses the earlier
  quarantine marks (proposals revert to pending, still reserved); `inspect_recovery` raises on a
  non-object anchor; very large `last_rows` cost disk/time. Alert rows growing on every poll was
  **fixed** (each code logged once per session; `test_polling_exit_plans_does_not_grow_alert_rows`).

Fifth independent pass (on `7ca1864`): row-by-row validation of replayed rows was **not
sufficient** — phantom entries/fills outside the policy scope (HIGH), forged exits with an
arbitrary planned bid (HIGH), a malformed row bricking `state()` (MEDIUM), naive timestamps (LOW);
plus a small `resolve` behaviour change (reverted). **Redesigned:** recovery never turns anchor
content into ledger state. It records the anchored rows verbatim inside one `RECOVERY_QUARANTINE`
event (data only), marks any of our own pending proposals they name `QUARANTINED` (reserved like
`UNRESOLVED`, alerted on every exit plan, owner must check the broker and close manually), alerts
unknown references, and trips the kill-switch. Forged rows therefore cannot create positions,
fills, exits or P&L (`test_n2d_anchor_only_forgeries_never_become_state`); a deleted last
transaction is quarantined and alerted, not hidden. Trade-off: a genuine crashed transaction is
not replayed either — its proposal was never returned or sent, so nothing is lost; a deleted fill
leaves that entry QUARANTINED for the owner's manual reconciliation (runbook R5). Not yet
re-reviewed.

Fourth independent pass (on `b8c9f32`): N2-A, N2-B, N2-C **FIXED**; kill-switch clearing,
multi-transaction deletion and racing a live worker all fail closed. New **N2-D (MEDIUM)**: the
unkeyed chain let an anchor-only edit plus an owner-run recovery inject a forged row (e.g. a fill
at USD 1). **FIXED:** recovery needs the owner to inspect the rows (`inspect_recovery`) and pass
the exact `expected_head`; every replayed row is validated with the same rules as live writes
(known events, well-formed details, the `resolve` fill bands); the anchor is fsynced before the
rename (LOW: power-loss truncation). `test_n2d_anchor_only_edit_cannot_inject_a_forged_fill`.
Not yet re-reviewed. Any recovery leaves the kill-switch on permanently (runbook R5).

Third independent pass (on `4f3decc`): N1 FIXED, N4 FIXED, N2 PARTIALLY FIXED → reworked as
above. Remaining LOW notes: in-band false fill reports (≤ 25 % of notional on entry, ≤ 10 % of the
bid on exit) are accepted (bounded; see R4); a single inflated mark can raise the recorded peak,
which only makes the drawdown gate fire earlier (a trusted-caller denial of service, not a bypass).
The reworked N2 recovery has not had a fourth independent pass.

## Residual risks (must be closed or accepted before any release)

- **R1 Authenticated research inputs.** Signals, admissions (`oos_*` fields) and `MarketContext`
  are still caller-built; a forged NATIVE signal for an in-scope strategy and instrument can pass.
  Bounded by the owner-signed strategy/instrument scope, evidence digest, notional caps and risk
  gates. Close in SD-074 by sourcing signals from the in-process native strategy runner and
  deriving admission from the hashed evidence content.
- **R2 Authenticated quotes and marks.** Marks, entry asks and exit bids come from the caller.
  SD-074 must take them from one authenticated broker quote path and cross-check marks against
  exit quotes.
- **R3 Ledger + anchor deleted together** resets local state (same residual as SD-064). Bounded by
  the signed window and the SD-064 caps; an off-host anchor is a release blocker for autonomous
  trading (already recorded under SD-064).
- **R4 Who may resolve.** `resolve` must be callable only by the broker reconciliation path
  (SD-059-style lookup evidence), not by research workers.
- **R5 Owner runbook** for UNRESOLVED exits, revoked grants and positions open after expiry
  (manual close in the eToro Demo UI, then record the outcome).
- **R6 Send-time caps.** SD-063 does not consume SD-064 request/write caps; the transport must call
  `UnlockAuthority.authorize_request(write=True, reference_id=proposal.reference_id)` before every
  send (single-use reference, persistent caps).
- **R7 Fees/financing** are not modelled in ledger P&L.

## Release position

G4 remains **NOT_ASSESSED / NO_GO**. Next steps (after the SD-058 MSFT pilot and re-lock): SD-064
grant wiring into the transport, R1/R2/R4/R6 closed in SD-074, independent review of the full
grant-to-order path, end-to-end simulated autonomous run, then a separate owner release for a
bounded Demo operating period. Nothing here activates the USD 1000 allocation.
