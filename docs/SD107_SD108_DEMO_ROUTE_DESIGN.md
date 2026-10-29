# SD-107 / SD-108 — eToro Demo as an SD-103 broker route (design, not built)

**Status:** DESIGN + offline contract tests only. No transport code changed; the MSFT pilot
path (SD-036/046/048/054, `etoro_demo_write_transport`) is untouched until the SD-105 run is
finished and the transport is re-locked. Nothing here releases execution.

## Current implementation status (2026-10-26)

The title and first status paragraph above are the pre-implementation design snapshot. This
status supersedes them. SD-107/108 now have an offline gateway and
adapter path on the isolated `codex/sd107-autonomous-demo-route-20261026` branch. The only
executable gateway is `OfflineDemoGateway`, which accepts `OfflineDemoSimulator` by exact type
and has no network client. `SD-103 ETORO_DEMO` stays `NOT_RELEASED`; the supervised MSFT pilot
transport is untouched. This work creates no execution release or broker request.

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

## 5. Offline implementation and remaining gates

- `sd108_broker_adapters.py` validates recorded rates, open acceptance, order lookup and close
  info. Quotes and fills are sealed by role-specific SD-074 signers; lookup responses are
  SHA-256 bound. A malformed lookup after acceptance is sealed as `UNRESOLVED` using the
  already-validated order id, so it cannot invent a fill or trigger a second write.
- Fill evidence now carries `broker_position_id` into the append-only SD-063 ledger. A single
  broker position can be managed by lineage. A lookup reporting multiple position ids becomes
  `UNRESOLVED`; the current ledger deliberately does not collapse distinct broker positions.
- A valid close-info response that reports closed units but has no execution price remains
  `UNRESOLVED`. The documented schema does not justify using the planned bid as a fill price.
  The local simulator has its own explicit close-price evidence and can demonstrate a complete
  simulated lifecycle.
- `sd107_demo_gateway.py` rechecks the signed SD-064 grant for every simulated write/read,
  matches proposals against the durable SD-063 ledger, consumes a fresh sealed quote, and checks
  position notional, aggregate exposure, daily order count, daily/cumulative loss, policy window,
  and kill-switch before an entry. It never retries an ambiguous outcome. Full reduce-only
  closes require the stored broker position id and a fresh sealed bid.
- The gateway calls SD-074D `publish` and `require_published` before each simulated request and
  publishes policy-ledger outcomes after resolution. Tests use `WriteOnceDirectoryAnchor` only.
  The SD-064 grant-use ledger is a separate local ledger and is not yet covered by an off-machine
  store; no real off-machine service is provisioned. Store failure refuses before simulator I/O.
- The deterministic simulator can persist orders and positions in SQLite. A repeated open/close
  reference returns its existing simulated order, and `recover_entry` / `recover_exit` perform
  read-only lookup and reconciliation after a simulated process interruption. Recovery preserves
  the kill switch; it never retries the write. This verifies local crash behavior only, not the
  durability or idempotency contract of any production broker transport.
- SD-074E's separate protective grant is wired to reduce-only closes after policy expiry. A
  policy or protective grant is re-verified against its own subject and request/write budget.
  Missing/expired protective authority or an unavailable anchor refuses the close; the operator
  must use the Demo UI under the current manual recovery runbook.
- A separately signed protective grant authorizes reduce-only exits after the policy window
  expires. Ordinary grant revocation while the policy window remains active does not trigger an
  automatic liquidation; the existing security regression keeps that behavior. It does not
  restore entry rights.
- The DAY policy is still intentionally absent: SD-063 refuses DAY until approved five-minute
  data and independent native-strategy admission exist. The Day Trader skill remains
  `RESEARCH_ONLY` / `SIMULATION_ONLY`; its advisory output cannot enter this route.

**Not verified / release blockers:** no real Demo transport is implemented or enabled; no
authenticated GET or order occurred; there is no owner-signed autonomous policy/release, no
provisioned off-machine write-once store for both policy and grant-use ledgers, and no independent
full-lifecycle review of the latest follow-up. Close-info without price remains unresolved.
Multi-position fills remain unresolved. DAY remains refused by SD-063 until approved intraday
data and independent native strategy admission are available; the Day Trader research module
cannot create an execution-qualified signal.
These are explicit blockers, not implied completion. The route may be integrated with SD-103
only after those items, the DAY data/admission gates where relevant, review, and separate owner
release are satisfied.
