# SD-152 Bundle O — Offline acceptance review (28 October 2026)

**Decision: OFFLINE ENGINEERING IN PROGRESS / EXECUTION NO-GO.** This document is a developer evidence index, not a signed independent review or release approval.

## Verified on earlier exact heads

- Durable single-writer fencing and no duplicate synthetic POST after 20 service reconstructions: CI [40678905424](https://github.com/smbabalola/sidedeck/actions/runs/40678905424).
- Unresolved-worker, ambiguous-close and close-ledger discrepancy replay protection: CI [40679337253](https://github.com/smbabalola/sidedeck/actions/runs/40679337253), [40679490543](https://github.com/smbabalola/sidedeck/actions/runs/40679490543), [40679837164](https://github.com/smbabalola/sidedeck/actions/runs/40679837164).
- Read-only local fence/health and incident journal, restart/dedup soak: CI [40678123791](https://github.com/smbabalola/sidedeck/actions/runs/40678123791).
- Prior consolidated *fail-closed* acceptance variant: [40681158221](https://github.com/smbabalola/sidedeck/actions/runs/40681158221), superseded by the latest partial-fill fix.

## Pending exact-head evidence

- SD-152 partial-fill recovery bug: policy records `PARTIALLY_FILLED`, but the former read-only recovery dossier required `FILLED`. Targeted implementation `8006072`, lifecycle test `a79ef04`, suite `fa4cdfd`. Await exact-head CI. Earlier `a79ef04` failure was due to an intermediate acceptance-suite test-name mismatch, **not proof of a runtime regression**; the suite reference was repaired in the next commit.
- The current acceptance entrypoint reuses nine offline integration scenarios. Verify the latest implementation and documentation heads; no result should be promoted from an earlier commit.
- All tests use in-process simulated broker responses and local SQLite. No provider-authenticated proof of order status, holdings or baseline integrity is established.

## Remaining engineering gates

1. Full multi-day/multi-track SWING and other supported tracks with market hours, DST/early closes, protective grants, restart and partial-fill fault injection in one independently reproducible qualification.
2. Real immutable audit/authorization/evidence anchors and independent review of recovery provenance (Bundle R prerequisite).
3. Operator-facing incident acknowledgement/delivery, durable notification outbox and error/escalation tests. Local incident journal is **not** delivery.
4. Production-like watchdog/deployment, operator runbooks and independent security findings (Bundles O/G).
5. Reconcile protected four-position baseline with genuinely authenticated broker evidence under separately approved READ scope; no auth action is implied here.

## Unchanged safety gates

`ETORO_DEMO_NOT_RELEASED`; historical HALT remains engaged. No authenticated broker GET/POST, owner signing, transport unlock, HALT reset, merge or deployment is authorised by this review. No LIVE/Real account execution. Release remains **NO-GO**.
