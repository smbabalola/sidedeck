# SD-145 anchored audit journal

`sd145_audit_journal.AuditJournal` is an offline-capable append interface for
policy, grant, grant-use, order reservation, send, reconciliation, and revocation
events. It reuses SD-074 `Checkpoint`, `ExternalAnchor`, and compare-and-append
semantics. Each row is canonical JSON hashed onto the prior row; the latest
sequence and hash are published as an HMAC-authenticated checkpoint. Concurrent
local processes serialize with SQLite `BEGIN IMMEDIATE`; the external store also
must perform atomic compare-and-append.

Construction has no remote side effects. `initialize()` explicitly publishes
genesis. `append()` refuses if the local/external heads differ or the anchor is
unavailable, and only returns after local commit and external checkpoint
acknowledgement. The broker desk writes reservation and send events before its
transport boundary and reconciliation evidence before local state mutation when a
journal is configured. The still-locked autonomous route must require this journal
before it can be released; the legacy supervised pilot path remains intact. The
unlock authority can also be configured with the journal to anchor grant checks,
grant-use, and revocation; the legacy local grant ledger remains for compatibility
and does not itself satisfy SD-145 external anchoring.

## Failure and recovery

On an anchor outage, local append rolls back and the caller must not continue to
the consequential action. If the external checkpoint succeeds but the local
SQLite commit then fails or the process crashes, the external head is ahead and
the journal refuses further use. There is intentionally no automatic rewrite or
rollback of the independent checkpoint; operator-controlled evidence recovery is
required. This avoids silently erasing a published audit event. On restart,
`verify()` detects local tampering, truncation, missing genesis, or head mismatch.

## Provisioning gates (not completed)

`WriteOnceDirectoryAnchor` is a local deterministic stand-in, not an off-machine
immutable service. A production implementation must guarantee durable atomic
compare-and-append, prevent delete/truncate by the trading host, authenticate
callers, protect the audit verification key independently, expose availability
alerts, and provide operator recovery/export. Add multi-host/process tests and
deployment/retention/cost approvals before SD-145 can be marked verified. No real
endpoint, credential, storage account, or deployment is configured here.
