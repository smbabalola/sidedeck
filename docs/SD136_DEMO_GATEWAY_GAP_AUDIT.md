# SD-136 — eToro Demo gateway contract and gap audit

**Scope:** offline source audit of branch `codex/sd122-etoro-data-autodemo-20261027` at baseline `c6aea5ec87810cbc004870b7cd34f17464fec2cb` (27 October 2026). **No broker or provider I/O; this report is not an independent security assessment or a release.** Read this with `STEERING.md`, `SIDEDECK_STEERING.md` §20 and the authoritative `TODO.md` board.

## 1. Current route inventory (do not conflate designs)

| Boundary | Code and verified behaviour | Production authority |
| --- | --- | --- |
| Scanner/research/decision | `application/sd103_trading_pipeline.py`, `sd071_decision_engine.py`, `sd123_day_demo_integration.py`: strategy research and proposed intents. `sd103.BROKER_ROUTES` refuses eToro Demo and permanently excludes Real. | No broker execution. |
| Signed budget and position policy | `application/sd063_autonomous_demo_policy.py`: `AutonomousDemoPolicy`, `AutonomousDemoRuntime`, append-only SQLite `PolicyLedger`, entry/exit proposal reservations, send-time cash/exposure/day-loss logic in offline gateway. A separate on-disk anchor detects divergence but is not an off-machine release ledger. | Policy proposals are `OFFLINE_PROPOSAL_NOT_SUBMITTED`. |
| Signed request grants | `application/sd064_unlock_grant.py`: `UnlockAuthority.authorize_request`, grant revocation and monotonic request/write reservation in `GrantLedger`. A signed grant is tied to its subject and expiration; local anchor is separately stored. | Implemented for offline gateway, **not wired to a genuine autonomous HTTP route**. |
| Authenticated input evidence | `application/sd074_trusted_inputs.py`: source registry, MAC'd envelopes, durable nonces, broker quote and fill verification. | Proven offline, not a live quote/fill provenance qualification. |
| Anchoring | `application/sd074_external_anchor.py`: `AnchorKeeper` publishes policy checkpoints and verifies them before simulated calls; `WriteOnceDirectoryAnchor` is a test stand-in. | **No provisioned independent off-machine grant-use/revocation/order anchor.** |
| Offline policy gateway | `application/sd107_demo_gateway.py`: `OfflineDemoGateway.__init__` insists on exact `OfflineDemoSimulator` type; `submit_entry` and `submit_exit` apply send-time checks, call signed grant authority, and publish policy head before the simulator. `BROKER_ROUTES['ETORO_DEMO']='NOT_RELEASED'`. | `SIMULATED_LOCAL` only; no network transport dependency. |
| Broker response contracts | `domain/etoro_demo_orders.py`, `application/sd108_broker_adapters.py`: strict Demo-only endpoint allowlist, order ID/position ID lineage and verified response envelopes. HTTP 200 acceptance is **not** a fill. | Parsers/adapters only; never grant send authority. |
| Typed Demo port | `application/sd129_etoro_demo_order_port.py`: `EtoroDemoOrderPort` wraps injected `DemoRoute`, accepted-order lookup with bounded referenceId→orderId 404 fallback, and reduce-only close of the currently confirmed position. | **Transport-neutral, NOT a gated production adapter.** Its `_open_attempts`, `_accepted_orders`, `_verified_positions` and `_closing_positions` are process-local and lost on restart. |
| Prior supervised transport | `infrastructure/etoro_demo_write_transport.py` and `application/sd054_pilot_operator.py`: previously built owner-signed, intent-bound supervised pilot route, persistent release request caps, strict Demo host/routes, injected test openers. `NETWORK_TRANSPORT_ENABLED=False`, `UNLOCKED_PILOT_DIGEST=None`. | Historical one-off pilot, **not an autonomous policy-to-transport bridge**. No current network unlock. |
| Baseline and completed-state check | `application/sd036_etoro_demo_desk.py`, `sd038_etoro_baseline_reconcile.py` and `domain/etoro_demo_books.py`: baseline snapshot/position ID matching and one-shot budgeted Demo `/pnl` read. | Earlier 27 Oct owner-approved 4/4 MATCHED is historical evidence, not permission for new calls. |

## 2. Lifecycle state machine: existing vs missing

1. **Propose:** strategy with admitted evidence → signed policy → `ENTRY_PROPOSED` in `PolicyLedger`; track budgets and risk/protected instruments checked. This stage is offline.
2. **Reserve before any write:** a *production* durable intent must atomically record `policy_digest`, `intent_id`, canonical symbol and resolved instrument, `referenceId`, request-body digest and one-shot send state; a separate signed grant-use reservation and external anchor must be confirmed before the HTTP boundary. Policy proposals and the typed port's in-memory `_open_attempts` are **not sufficient** by themselves.
3. **Open acceptance:** an allowed Demo-only POST may return `referenceId` and `orderId`. Parse/validate, durably bind to the original intent, but never label `FILLED` on acceptance.
4. **Recovery:** after an audited delay, read-only GET by `referenceId`; only a 404 may switch to bounded GET by accepted `orderId`; subsequent `/pnl` requires its *own* signed, counted grant. A restarted worker must read accepted IDs from a durable ledger rather than invent trust from an in-memory object. Unknown POST result, both 404, partial/multiple/mismatched fills or missing anchor → `UNRESOLVED/HALTED`, **never repeat POST**.
5. **Ownership:** only broker-confirmed `openingData.orderId` linked to our accepted order and a unique `positionId` can establish SideDeck ownership. Symbol/instrument alone cannot. The four original baseline positions are protected by their original IDs.
6. **Close:** independently granted, full reduce-only close uses the verified position ID and a durable one-shot close reference. Handle close acceptance and close-info as **reported status**, not realised cash/P&L or flat account. If the close POST is uncertain, halt and investigate by reads; never send a second close.
7. **Final reconciliation:** fresh authorised and budgeted `/pnl` plus pending-order evidence must prove attributable position absent, all four protected positions unchanged and no unexplained side effects. Broker execution price, fees and realised P&L must be separately evidenced. The earlier manually closed MSFT pilot is **not** an autonomous broker round trip.

## 3. Pre-I/O enforcement truth table

| Check | Implemented where | Gap for unattended eToro Demo |
| --- | --- | --- |
| Real prohibition, Demo endpoint allowlist | `domain/etoro_demo_orders.require_demo_route`, locked `etoro_demo_write_transport`, `sd103.require_route` | Keep default DENY in the new adapter, test every bypass path. |
| Explicit owner policy and unexpired independent per-request grant | `sd063` + `sd064` checked by `sd107._authorize` before simulator call | Bind to a reviewed HTTP route, revocations and close-specific grants. |
| Cash, risk, quote freshness and per-track caps | `sd063`, `sd107._validate_entry_at_send`; `sd074` signed quotes | Broker-confirmed cash/fill/partial logic and real feed freshness not integrated. |
| Durable one-shot write reservation and link chain | SD-032 `DurablePaperIntentStore` exists for paper; signed supervised pilot has own outbox; `sd129` is memory-only | **SD-137 P0**: unify without a shadow engine, reserve before send with crash/restart/multiprocess fencing. |
| Request/write counters | `sd064.GrantLedger.reserve_use` and supervised `_ReleaseLedger.reserve` | No comprehensive policy+transport+route budget before an autonomous HTTP operation. |
| Off-machine audit anchor | `sd074.AnchorKeeper` protocol and disposable directory implementation | **SD-145**: immutable independent storage provisioning and grant-use/policy/order atomicity remain absent. |
| Broker snapshot and protected baseline | SD-036/038 strict baseline logic, SD-129 strict order position linking | **SD-139**: authorised final /pnl and pending-order reconciliation not wired. |
| Release state and incident recovery | `sd103`, `sd107`, supervised transport lock; persistent policy kill events | SD-138 and independent review/owner release still required; historical pilot HALTED must not be reset. |

## 4. Ordered gap register and owners

| ID | Severity | Missing proof / required fix | Owner / TODO |
| --- | --- | --- | --- |
| G136-01 | Critical | Persist write-ahead intent/reference/order/position/close lineage; on crash treat potentially sent writes as unknown; concurrent workers cannot double-submit. | Codex offline SD-137 |
| G136-02 | Critical | One policy-bound *hard-locked* HTTP gateway for Demo only, with signed request budgets, true sealed send-time quote and no raw SDK/CLI bypass. | Codex offline SD-138 |
| G136-03 | Critical | Independent attested off-machine grant-use/revocation, intent and policy checkpoints; fail closed on anchor outage. | SD-145 offline; provider provisioning owner |
| G136-04 | Critical | Strict authoritative /pnl and pending-order reconciliation linked by immutable IDs; never mutate four baseline IDs; no close-info-only flat/P&L. | Codex offline SD-139 |
| G136-05 | High | Crash, duplicate/404/partial/multi-fill, stale data, calendar and kill-switch fault injection across the *integrated* gateway. | Codex SD-140/141/146/148 |
| G136-06 | External | Lawful, complete intraday bars and locked out-of-sample strategy admission; current eToro AAPL search 403 applies to market data, not previously proven supervised order access. | SD-142–144, provider/owner signoff |
| G136-07 | Release blocker | Independent review, a new bounded owner-signed Demo-only grant, monitored canary and one-month soak. | Owner/external SD-149–151 |

## 5. Reviewable verification and red lines

- Existing regression suites: `tests/test_sd107_demo_route_contract.py`, `test_sd074_external_anchor.py`, `test_sd064_unlock_grant.py`, `test_sd129_etoro_demo_order_port.py`, `test_sd134_demo_order_recovery.py`, `test_sd041_no_demo_write_transport.py`, `test_sd038_etoro_baseline_reconcile.py`. SD-136 adds `tests/test_sd136_gateway_gap_guards.py`.
- Exact-head CI must pass after these commits. A green docs/contract audit does **not** mean SD-137, the external ledger, real feed or live trading are ready.
- Never read .env, issue an authenticated GET, POST an order, reset `HALTED`, merge PR #8 or edit a consumed authorisation during this audit.
- **Next:** SD-137 should extend existing authoritative ledgers with durable correlated identifiers, atomic send reservations, strict GET-only recovery, crash/fencing tests and optional PostgreSQL disposable CI. Do not simply make `EtoroDemoOrderPort` hold a new in-memory map.
