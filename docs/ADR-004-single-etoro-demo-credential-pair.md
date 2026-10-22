# ADR-004 — One eToro Demo credential pair for monitoring and future approved execution

**Status:** ACCEPTED (owner decision, 2026-10-22) | **Supersedes:** the SD-042 two-key separation requirement and SD-044 prerequisite P1 as first drafted.

## Context

SD-042 originally required a Demo Read-only key for monitoring and a separate Demo Read/Write key for execution. The owner has one eToro Demo Read/Write pair, stored locally as `ETORO_DEMO_TRADE_API_KEY` / `ETORO_DEMO_TRADE_USER_KEY`. The owner decided not to create a second key and not to involve the Real account.

## Decision

1. SideDeck accepts **one** eToro Demo Read/Write pair, under the `ETORO_DEMO_TRADE_*` names, for both GET-only monitoring and any future, separately approved Demo execution.
2. The legacy names `ETORO_API_KEY` / `ETORO_USER_KEY` must **not** also be set. A duplicate copy of the secret, or an unknown second pair, is refused (`EXTRA_CREDENTIAL_NAMES_REFUSED`) rather than guessed between.
3. **R9** (a monitoring component holds a write-capable credential) is **owner-accepted** for the Demo-only pilot, with these compensating controls:
   - monitoring only through `EtoroDemoReadClient`: a single `/pnl` path, GET only, no write methods, guarded by SD-041 and SD-042 tests;
   - a signed owner approval for every order (SD-033 with the SD-045 OpenSSH verifier);
   - persistent request budgets;
   - verified position lineage;
   - the protected four-position baseline;
   - the kill-switch;
   - the Demo route allowlist, with eToro Real routes permanently refused.
4. No Real-account key is needed or accepted.

## Consequences

- `etoro_demo_portfolio` and `p5_demo_refresh` resolve credentials through `sd042_etoro_credential_roles.monitoring_credentials`. They still read the process environment only and never open `.env`.
- The consumed SD-038 one-shot runner keeps its historical legacy-name loader. Its budget is exhausted, so it cannot run again.
- This decision authorizes **no** authenticated request, order, capital allocation or release. `ETORO_DEMO_EXECUTION_RELEASE=NO_GO`, `broker_execution=DISABLED`.
