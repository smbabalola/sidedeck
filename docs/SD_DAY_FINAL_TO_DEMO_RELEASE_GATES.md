# SideDeck — Offline DAY acceptance → eToro Demo release gates
Date: 2026-10-29. Branch: `codex/sd122-etoro-data-autodemo-20261027`. Draft PR #8.

## What has been proven
- Code `07006e3f4e4464ee1e5251ce6a83154837900105` passed [CI #40852549194](https://github.com/smbabalola/sidedeck/actions/runs/40852549194).
- Documentation-only follow-up `aaeb555990a87c3d9f3b724bd8d41d36aa37d255` passed [CI #40852985174](https://github.com/smbabalola/sidedeck/actions/runs/40852985174).
- Fixture-only DAY entry/fill/monitor/protective exit/flat; real child-process recovery of an open simulator position using distinct signed planning and execution quote envelopes; no-replay, crashed-fence fail-closed, bounded polling, and cross-session no-signal soak.
- No authenticated eToro call, live market data read, broker baseline read or HALT reset in this work. These tests do not qualify ORB or release Demo execution.

## Explicit independent Demo canary readiness snapshot

| Gate | Status | Evidence required to change status |
| --- | --- | --- |
| G0 exact-head CI | PASS for offline scope only | Independent security review and final release-head CI: BLOCKED/NOT_ASSESSED |
| G1 five-minute lawful and timely data | BLOCKED_EXTERNAL | Provider entitlement/usage rights and independent latency/instrument mapping evidence |
| G2 market-input admission | BLOCKED_EXTERNAL | Authorized signed provenance, point-in-time session integrity and executable fresh bid/ask source |
| G3 actual strategy qualification | BLOCKED_EXTERNAL | One non-fixture strategy with >=30 locked OOS qualified trades, costs/slippage and independent PASS |
| G4 owner policy/recovery/security | BLOCKED_OWNER + BLOCKED_EXTERNAL | Reviewed risk/protective scope, signed expiring grants, durable off-machine audit/revocation, independent security review, explicitly authorized HALTED recovery and immutable four-position Demo baseline |
| G5 restricted canary | NOT_RELEASED | Only after G0–G4 PASS and separate owner signed digest-specific scope; prove verified open/fill/close and fresh /pnl flat and baseline |

## No-go rules
- `ETORO_DEMO=NOT_RELEASED`, eToro Real permanently disabled; the prior pilot HALTED state is not reset.
- No authenticated network operations or market-data entitlements may be inferred from CI.
- Do not claim an installed daemon, independently licensed feed, or overnight production soak from the bounded offline test.
- Do not use fixture-admitted ORB to satisfy G3. User wants process verification now; real qualification is reserved for a separate later release gate.
- No grant creation, signing, baseline mutation, position close, or eToro POST without independent authorisation.

## Next autonomous engineering batch (offline-safe only)
1. Inventory and assess already-authorized source/data, strategy report, audit and security evidence without external account access or additional research purchases.
2. Produce a release dossier with explicit PASS/BLOCKED/NOT_ASSESSED per gate and no fabricated green status.
3. Prepare a single narrowly scoped owner approval proposal *only after* all independent prerequisites have been evidenced; until then remain NO-GO and do not ask for premature brokerage permissions.


## Evidence inventory — 29 October
This is a source-location review, not independent reproduction or provider approval.

| Lane | Existing evidence | Outstanding independent gate |
| --- | --- | --- |
| Market data | SD-021 historical SIP research snapshots; SD-142/143 importer and entitlement workstream | Rights for storage and broker automation, timely executable five-minute bid/ask, point-in-time mapping and fresh-quote proof |
| Strategy | SD-014–022 research and SD-071 qualification; SD-155 test-fixture ORB | Genuine independently qualified locked OOS >=30 trades, costs and final holdout. Fixture admission does not qualify G3 |
| Broker | SD-137–141 offline fake eToro-shaped lifecycle; DAY SD-126/152 CI #40852549194 | Real authorised broker lineage and protected baseline verified only under separately approved Demo release |
| Security | SD-145 local anchor fixtures, SD-146/149 review, SD-152 durable fence | External immutable host, independent security assessment and tested incident/on-call operations |
| Authority | SIDEDECK_STEERING.md §§20–21; SD-150/151 | Human signed expiring scope, explicit historical HALT recovery approval, narrowly bounded Demo canary |

### Engineering order, without owner micro-prompts
1. Freeze the CI-verified offline mechanical lifecycle; do not rebuild it or substitute new fixture tests for actual provider evidence.
2. Reconcile already authorised data rights, existing research, and audit/security documentation offline. Block real source calls until separately authorised.
3. Assemble one SD-149 release dossier with exact provenance, missing external proofs and reviewed release scope.
4. Request an owner decision only for a concrete, bounded external step, and only when its independently verifiable prerequisites are ready. eToro Demo remains NOT_RELEASED.

The four protected holdings have not been re-read in this batch. No live account, HALT reset, new signing grant, external audit-host deployment or Demo order was authorised.
