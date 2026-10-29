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
