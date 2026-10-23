# SD-074 off-machine ledger and revocation anchoring — design (verification block implemented offline)

**Status:** verification building block implemented offline (`src/sidedeck/application/sd074_external_anchor.py`, `tests/test_sd074_external_anchor.py`: rollback, deletion, replacement, tampered checkpoint and unavailable store all fail closed against a write-once stand-in). No real off-machine store exists and nothing is wired into the runtime. **Autonomous execution stays blocked** until this is implemented and
independently verified (release blocker recorded under SD-064 and SD-063 residual R3).

## Problem

The SD-063 policy ledger and the SD-064 grant ledger are hash-chained SQLite files, each mirrored by
a local anchor file. Anyone who can rewrite **both** the ledger and its anchor on this machine can:

- roll back to an earlier consistent state (e.g. before a kill-switch or a revocation),
- delete both and start fresh (counters, single-use references and the kill-switch reset),
- replace them with a consistent forged pair.

Local anchoring detects partial or accidental tampering only.

## Goal

Detect deletion, rollback and replacement of either ledger using state the local machine cannot
rewrite, and fail closed (no entries, no new grant use) when the check cannot be completed.

## Design

1. **Checkpoint record** after every committed transaction (and at least every N minutes):
   `{ledger_id, policy_or_authority_digest, count, head_hash, prev_head_hash, revoked_ids_digest,
   at}`, signed by a device key held in the OS keystore (not in the repository or data folder).
2. **Off-machine log:** an append-only store the trading host can write to but cannot rewrite or
   delete: e.g. object storage with object lock / retention, a separate signing host, or a public
   transparency log. The owner holds the only deletion rights.
3. **Monotonic check at every open and before every authorized request:** fetch the latest remote
   checkpoint; require `local.count >= remote.count` and that the local chain contains
   `remote.head_hash` at position `remote.count`. A lower count, a missing head, a different
   policy digest or a missing local ledger with a remote record → **fail closed** and alert.
4. **Revocations:** written remotely first, then locally; a revocation present in either store is
   effective (union), as SD-064 already does locally.
5. **Unavailability:** if the remote log cannot be reached, allow only reduce-only exits under an
   existing authority for a bounded grace period, never entries or new grant use; alert the owner.
6. **Start of a policy:** the owner's grant signature also covers the remote log location, so a
   machine cannot silently switch to an empty log.

## Interface (for SD-074 integration)

```text
class ExternalAnchor(Protocol):
    def latest(ledger_id) -> Checkpoint | None
    def append(checkpoint: SignedCheckpoint) -> None      # write-once; never overwrite
```

The transport gate (SD-064 `authorize_request`) and `PolicyLedger.open` call `latest()` and refuse
on any inconsistency. An offline fake with write-once semantics is enough for unit tests; the real
store needs separate owner provisioning and review.

## Verification required before release

Rollback to an older consistent pair, deletion of both files, replacement with a forged pair, remote
unavailability, clock skew, concurrent writers, and revocation in only one store, each shown to
fail closed in tests and in an independent review.

## Hard requirements on the real store (from the independent review)

1. **No deletion or truncation**, even by the trading host: a deleted latest checkpoint leaves a
   valid prefix the keeper cannot distinguish from a shorter history.
2. **Compare-and-append:** accept a checkpoint only if the store's current latest equals the
   checkpoint's `prev` (atomically), otherwise refuse; concurrent publishers then retry instead of
   forking the chain.
3. **Atomic, durable writes:** a torn write must never become visible.
4. **One chain per policy:** the chain id is derived from the policy digest
   (`ledger_id_for(policy_digest)`), so a fresh restart under another id is impossible.
5. Preferably signing on a separate host: with the device key on the trading host, an attacker can
   add forged higher checkpoints (denial of service), not remove history.
