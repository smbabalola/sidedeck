# SD-152 operator authentication and notification delivery integration contract

**State:** design-only, not an approved provider or a deployed integration. **Execution:** ETORO_DEMO_NOT_RELEASED.

## Trust boundaries

1. **Identity provider:** server-verified issuer, audience, signature, expiry and subject; map to an explicit operator role and tenancy. Free-text actor names, local SQLite acknowledgements, client-supplied roles and caller-defined `authenticated=True` are untrusted.
2. **Acknowledgement:** bind incident digest + authenticated subject + permitted role + tenant + issuance time + expiry + unique nonce. Recheck authorization at submission. Save an immutable audit record. This is evidence of *human acknowledgement only*: never incident resolution, grant signing, broker permission, or notification receipt.
3. **Outbox:** durable incident fingerprint and delivery intent, monotonic state transitions, idempotent dispatch key, retry budget and bounded backoff. Persist failed attempts and provider receipts separately. The existing outbox only records `NOT_CONFIGURED`; do not treat its observation counter as a delivery-attempt counter.
4. **Delivery adapter:** explicit provider-specific capability, server-owned credential, approved destination allowlist and sandbox endpoint, auditable send authorization, verified provider receipt. Never accept caller claims such as `SENT` or `provider_configured` as proof. The default transport remains `DisabledNotificationTransport`.
5. **Escalation:** a required, externally approved fallback for persistent errors; preserve unresolved incidents and surface the lack of verified delivery. Operator acknowledgement must not cancel delivery or escalation by implication.
6. **Audit:** externally anchored, tamper-evident grant/incident lineage and independent reviewer sign-off before release.

## Proposed interfaces (not implemented or authorized)

- Identity verifier: `verify(token, audience, clock) -> VerifiedPrincipal | Denial` (verification MUST happen on trusted server side).
- Authorizer: `may_ack(principal, incident, tenant) -> Decision`; deny unknown, expired, mismatched, revoked or inadequately scoped identities.
- Notification sender: `send(approved_intent, idempotency_key) -> ProviderReceipt | ClassifiedFailure`; only callable behind an independently reviewed release gate.
- Delivery reconciler: verify provider receipt authenticity, correct incident/destination, monotonic transitions, deterministic retry; never infer delivery from the local outbox.

## Minimum negative acceptance cases

- Forged issuer, audience, signature, timestamp; revoked principal, cross-tenant or cross-account operator; replayed nonce and stale session.
- Duplicate dispatch after timeout, response lost after send, provider 429/5xx, permanent 4xx, partial provider outage, credential rotation, restart between POST and receipt save.
- Forged receipt, mismatched destination or incident digest, delivery state rollback, backwards system clock, corrupted outbox, dead-letter escalation and capped retry budget.
- Protected baseline drift, unsigned owner release, historical HALT engaged, attempts to use acknowledgement/notification permission for trading: all must fail closed.

## Implementation sequence and gates

1. Independently select and approve identity issuer, roles, tenant model and operator identity storage boundary.
2. Select notification provider, destination/consent policy, privacy retention, credential ownership and sandbox/offline harness.
3. Implement adapters behind separately authorized capability flags, then fully offline fault-injection and integration testing.
4. Independent security review, authenticated sandbox qualification, operator UAT, signed owner decision and narrowly scoped production release (if approved).

**Until these gates are met:** no authenticated identity claim, no external notification, no broker GET/POST or trade release. Green offline CI is not independent security sign-off.
