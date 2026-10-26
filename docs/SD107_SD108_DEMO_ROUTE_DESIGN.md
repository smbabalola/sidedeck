# SD-107 / SD-108 — eToro Demo as an SD-103 broker route (design, not built)

**Status:** DESIGN + offline contract tests only. No transport code changed; the MSFT pilot
path (SD-036/046/048/054, `etoro_demo_write_transport`) is untouched until the SD-105 run is
finished and the transport is re-locked. Nothing here releases execution.

## 1. Target flow (reusing what exists)

```
SD-103 decision_pass (admitted strategies only)
  └─ ELIGIBLE decision + order intent (PROPOSED_NOT_SUBMITTED)
      └─ sealed SD-074 signal envelope   (source role: native_strategy_runner)
          └─ SD-074 AuthenticatedRuntime.propose_entry
              ├─ re-verifies the SD-064 autonomous_policy grant (owner signature, window, revocation)
              ├─ runs SD-071 decide() itself on verified inputs (decision price = sealed ask)
              └─ EntryProposal (OFFLINE_PROPOSAL_NOT_SUBMITTED, single-use reference)
                  └─ NEW policy-bound Demo transport (SD-107)
                      ├─ UnlockAuthority.authorize_request(write=True, reference_id) before I/O
                      ├─ send-time caps from the ledger: per-order notional, open positions,
                      │  daily orders, gross exposure, cumulative loss
                      ├─ Demo route allowlist; eToro Real refused before any I/O
                      └─ POST open (limitIOC, 1x, long) → orders:lookup (lookup-only recovery)
SD-108 adapters
  ├─ rates GET → sealed broker_quotes envelope (≤ 60 s, 5 s skew, per-pilot time basis)
  └─ orders:lookup / close-info GET → sealed broker_reconciliation fill envelope,
     bound to reference_id and order_id (closes the open SD-074 fill-binding residual)
          └─ PolicyLedger.resolve / reconcile_unknown
Exits: AuthenticatedRuntime.plan_exits → close proposal → same transport (full close of a
lineage-verified position only) → close-info → final /pnl reconcile.
Protective exits after expiry/revocation: SD-074E reduce-only grant; never entries.
```

## 2. Decisions fixed now

| Topic | Decision |
|---|---|
| Transport | A **new** class bound to `UnlockAuthority` (grant kind `autonomous_policy`), not a change to `EtoroDemoHttpTransport`, which stays bound to the single signed pilot. |
| Lock | Its own lock, default locked; enabled only by the verified grant at every request (no source-constant unlock). |
| Caps | Grant caps (≤ 7 days, ≤ 2000 requests, ≤ 200 writes) **and** policy caps (≤ USD 1,000 total, ≤ USD 50 per position, SWING/POSITION only) checked at send time from the ledger, never from caller arguments. |
| Inputs | Only sealed envelopes reach the runtime; payload self-claims refused (existing SD-074). |
| Unknown outcomes | Kill switch + UNRESOLVED; settled only from sealed lookup evidence; never resubmitted. |
| Ownership | referenceId → orderId → positionId lineage only; the four baseline positions refused. |
| Real | Permanently excluded (route allowlist; no Real host or paths anywhere). |
| Off-machine anchor | Still a release blocker (SD-074D). Open SD-074F decision for the owner: whether reduce-only exits are exempt from publish-before-send when the store is unavailable. |

## 3. Build order (each step: tests, independent review, CI)

1. SD-105 completes; transport re-locked (`UNLOCKED_PILOT_DIGEST = None`).
2. SD-108 quote/fill envelope adapters over recorded broker payload shapes (offline fixtures
   from sanitized SD-105 schemas; no new request).
3. SD-107 policy-bound transport with a fake opener: restart, replay, tamper, revocation,
   duplicate, expiry and partial-fill tests; guard tests updated in the same commit.
4. SD-103 route `ETORO_DEMO` calls the runtime instead of the simulator; still
   `NOT_RELEASED` until step 6.
5. Independent review of the whole grant-to-order path.
6. Owner: signed SD-063 policy (SD-110) + SD-064 grant + explicit release. Only then may the
   route status change.

## 4. Pinned now by `tests/test_sd107_demo_route_contract.py`

SD-103 route `ETORO_DEMO` is `NOT_RELEASED` and refused; SD-103/104/112 **directly** import no
network module (transitive imports are not claimed) and SD-109 uses `socket` only for the host name; the MSFT transport lock is engaged;
SD-064 cap ceilings are the reviewed values; SD-063 proposals are
`OFFLINE_PROPOSAL_NOT_SUBMITTED`; pipeline order intents are `PROPOSED_NOT_SUBMITTED`.
