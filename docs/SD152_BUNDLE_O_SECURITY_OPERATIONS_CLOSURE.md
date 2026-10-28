# Bundle O security and operations closure checklist

**Decision as of 28 October 2026: OFFLINE ENGINEERING PARTIALLY VERIFIED; EXECUTION NO-GO.**
This is an engineering checklist, not an independent audit, broker reconciliation, owner authorization or release.

## Verified earlier CI evidence

| Control | Evidence | Boundary |
|---|---|---|
| Partial-fill policy and durable position cross-check | [40681729870](https://github.com/smbabalola/sidedeck/actions/runs/40681729870) | In-process fake broker, not account evidence |
| Offline acceptance scenarios | [40681158221](https://github.com/smbabalola/sidedeck/actions/runs/40681158221) | Simulated local only |
| UK/US DST, scheduler restarts, calendar isolation | [40682786686](https://github.com/smbabalola/sidedeck/actions/runs/40682786686) | No unattended deployed worker |
| Local watchdog and stale heartbeat test | [40683247411](https://github.com/smbabalola/sidedeck/actions/runs/40683247411) | No external alert transport |
| Local operator acknowledgement and outbox reporting | [40684150145](https://github.com/smbabalola/sidedeck/actions/runs/40684150145) | Actor label not authenticated, notification not delivered |
| Identity provenance truth fields | [40687153466](https://github.com/smbabalola/sidedeck/actions/runs/40687153466) | Always LOCAL_UNVERIFIED |

## Awaiting exact-head CI

- Negative operator authorization tests `b04dc82` and `03c90fb`. Unverified roles/signatures must be denied, never promoted to trusted identity.
- This checklist and any later modifications require CI on their **own exact SHA**, not merely an earlier green test.

## Outstanding acceptance work — do not close these as tested

1. **Operator identity/authentication:** choose trusted identity issuer and role model, bind a verified principal to acknowledgement with strong provenance and expiry. Test revocation, delegation, replay, tampering and incorrect tenant/account scope.
2. **Alert notification delivery:** independently scoped provider credentials and dispatch authorization; durable delivery attempts, receipts, error classification, retry/backoff, deduplication and escalation fallback. The current SQLite outbox records **intent only** and must not be labelled SENT.
3. **Audit evidence:** independent immutable off-machine alert/grant anchors and verifiable account/position baseline evidence; existing local journal alone is insufficient.
4. **End-to-end operations:** multi-day, multi-track, DST and early-close simulation with stale-heartbeat/outage, replay resistance, crash/restart, mismatched ledger and operator review, with reproducible results and no fake release claims.
5. **Independent review and rollout:** external security finding register, signed remediation evidence, operator runbook and UAT, deployment watchdog review and explicit owner acceptance. No merge/deployment is authorized.
6. **Owner-gated Demo validation:** separate scoped approvals for broker READ/WRITE, actual credentials and environment, recovery procedure, historical HALT, protected original four positions and a narrow owner-signed release. Until then authenticated calls remain blocked.

## Resolution criteria

Bundle O can be declared **offline engineering verified** only after all applicable implementation/tests/lint/mypy/front-end/DB gates pass on exact HEAD and the reviewer assesses the remaining open items. External delivery, verified operator identity and independent gates are **not** implied by green offline CI. Autonomous eToro Demo remains **NOT_RELEASED / NO-GO** with historical HALT unchanged.
