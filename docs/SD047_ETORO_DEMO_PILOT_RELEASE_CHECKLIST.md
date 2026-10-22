# SD-047 — eToro Demo pilot release checklist (2026-10-22)

**Status: NOT READY.** `ETORO_DEMO_EXECUTION_RELEASE=NO_GO`, `broker_execution=DISABLED`, eToro Real permanently prohibited.

This checklist governs the single pilot in [SD-044](SD044_ETORO_DEMO_PILOT_PROPOSAL.md). Every row must be ✅ before the owner is asked for the explicit, bounded pilot authorization. Ticking a row authorizes nothing.

| # | Gate | Status | Evidence |
|---|---|---|---|
| C1 | Demo credentials: single owner-accepted pair (ADR-004), legacy names absent | ✅ 2026-10-22 offline check `SINGLE_DEMO_PAIR_OWNER_ACCEPTED` | `sd042_etoro_credential_roles.py` |
| C2 | IP whitelist and expiry on the Demo key | ✅ owner-attested (cannot be verified offline) | Owner statement 2026-10-21 |
| C3 | Owner SSH signing key: `data/approval_allowed_signers` present; a test digest signed by the owner verifies | ❌ file not present | SD-045 verifier ready |
| C4 | Protected baseline 4/4 MATCHED at the last authorized read | ✅ SD-038 (2026-10-21) | `SD038_ETORO_BASELINE_RECONCILIATION.md` |
| C5 | Pilot orchestration is offline-tested. The 11-request / 2-write caps hold, every response is shape-checked, and an unconfirmed close is never `COMPLETE` | ✅ SD-046 (18 tests) | `sd046_etoro_demo_pilot.py`, `tests/test_sd046_etoro_demo_pilot.py` |
| C6 | Desk controls: lineage, write-ahead, lookup-only recovery, rate budgets, kill-switch, Real refusal | ✅ SD-036/037 | `sd036_etoro_demo_desk.py` |
| C7 | **HTTP Demo write transport** implemented per SD-041, reviewed, and replacing the no-transport guard with a single-transport guard. Still unattachable while the release is `NO_GO` | ❌ not built (by design until the owner approves building it) | `SD041_ETORO_DEMO_TRANSPORT_REVIEW.md` |
| C8 | One-shot pilot release switch: a signed, expiring, single-use owner pilot authorization that is the *only* way the desk accepts the C7 transport. A general `NO_GO` → `GO` toggle is not allowed | ❌ not built | — |
| C9 | Pilot capital: the owner allocates ≤ USD 50 of virtual Demo funds to `etoro-demo:tradingagents` | ❌ owner decision pending | R8 |
| C10 | Instrument chosen by the owner (a liquid US large-cap stock, not in the baseline) and its eToro instrument ID confirmed offline. Resolving the ID needs either an owner-supplied ID or a separately authorized market-data search | ❌ pending | — |
| C11 | Date window and US regular-hours timing agreed | ❌ pending | — |

## Owner actions remaining

1. C3: create the signing key and signers file, then sign the test digest Codex provides.
2. C9 to C11: confirm the pilot amount, the instrument (with its eToro instrument ID if known), and the date window.
3. Approve **building** C7 and C8 (code only, no requests). Codex then implements both offline, with tests, behind the guards.

The final step is a separate, explicit pilot authorization for exactly the SD-044 scope.
