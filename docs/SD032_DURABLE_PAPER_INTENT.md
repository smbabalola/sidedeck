# SD-032 durable paper intent boundary

SD-032 adds a local SQLite append-only intent/event store. It binds each
intent to tenant, broker, environment, account scope, portfolio and
instrument identity; atomically rejects conflicting client-order IDs; and
survives a process restart. Its only submission acknowledgement is explicitly
`offline-simulated`. No broker transport, credentials, HTTP request or order
capability is present.

The outbox is engineering evidence for a future release, not a release of
paper execution. The SD-027/SD-030 gate remains `NO_GO`.
