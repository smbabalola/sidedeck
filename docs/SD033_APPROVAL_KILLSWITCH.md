# SD-033 approval and kill-switch boundary

SD-033 provides a verifier-only approval store. The caller supplies an
externally provisioned public key and verification function; SideDeck never
generates, stores or prints signing secrets. Approval is bound to a SHA-256
intent/scope digest, requires requester/approver separation, has an expiry and
cannot be replayed.

The durable emergency stop survives restart and can only be cleared by a
different operator with an explicit confirmation. This is an offline control
boundary and does not authorize a broker order. Paper release remains
`NO_GO`; authenticated account reads and transport remain disabled.
