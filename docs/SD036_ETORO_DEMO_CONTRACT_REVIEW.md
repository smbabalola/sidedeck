# SD-036 — eToro Demo integration review, contract comparison and offline desk (2026-10-21)

**Status:**

- Offline desk: `IMPLEMENTED`, offline-tested.
- `ETORO_DEMO_EXECUTION_RELEASE=NO_GO`.
- `broker_execution=DISABLED`.
- eToro Real: `PERMANENTLY_EXCLUDED`.

**Network activity in this work:** public documentation pages on `api-portal.etoro.com` and `builders.etoro.com` were read unauthenticated. There were **zero** authenticated eToro requests, no credential reads and no orders.

## 1. What already works (evidence-backed)

| Capability | Status | Evidence |
|---|---|---|
| Demo `/pnl` authenticated read | **PASS (once, 2026-10-20)** | `ETORO_DEMO_READ_2026-10-20.md` (HTTP 200, 4 positions) |
| Strict Decimal `/pnl` parser, cash and P&L rules | VERIFIED offline | `domain/etoro_demo.py`, `tests/test_etoro_demo.py` |
| Immutable four-position baseline | **PASS: captured and MATCHED on 2026-10-20** | `P5_ETORO_DEMO_BASELINE_ACCEPTANCE_2026-10-20.md`; local `data/etoro_demo.sqlite3` |
| Read-only GET-only client | VERIFIED offline | `infrastructure/etoro_demo_client.py` (single path, no redirect, no retry) |
| Three logical books, reconciliation and close protection | VERIFIED offline | `domain/etoro_demo_books.py` |
| Market-data v1 AAPL search | historical HTTP 200; later v1/v2 403s | `ETORO_V1_MARKET_DATA_PROBE_2026-10-20.md`, AGENTS.md |

The baseline has been reconciled exactly once, at capture time. Whether the four positions are **still** unchanged is `NOT_VERIFIED` since 2026-10-20.

## 2. Comparison with the current official Demo API

| Concern | Official docs (2026-10-21) | Before SD-036 | After SD-036 |
|---|---|---|---|
| Portfolio read | `GET /api/v1/trading/info/demo/pnl`; 60 req/60 s | Matches | Unchanged |
| Open | `POST /api/v2/trading/execution/demo/orders`. 200 = *accepted*, not executed. Open only; `buy`/`sellShort`; USD only | Absent | Body builder: long only, leverage 1, `limitIOC` by units with `limitRate`, USD |
| Idempotency | `x-request-id` GUID per order, echoed as `referenceId`; lost response → lookup by `referenceId` | n/a | `referenceId` is the outbox `client_order_id`, written ahead and never reused. Recovery is by lookup only |
| Outcome | `GET /api/v2/trading/info/demo/orders:lookup`: `status.id` 1–12, `positionExecutions[].positionId`, `openingData.orderId` | Absent | Strict parser; each execution must be opened by this order, on the requested instrument, at leverage 1, ≤ limit and ≤ units |
| Close | `POST /api/v1/trading/execution/demo/market-close-orders/positions/{positionId}`, body `InstrumentID`, `UnitsToDeduct` (null = full) | Absent | Protected close: never a baseline position; needs lineage plus a matching fresh `/pnl` row |
| Close outcome | `GET /api/v1/trading/info/demo/close-orders/{orderId}` (`statusID`, `positions[].units`) | Absent | Parser refuses any position SideDeck did not name |
| Write rate limit | 20 req/60 s, shared across write endpoints | n/a | Not yet enforced (residual risk R4) |
| Keys | Each key is for **one environment** (Demo or Real) and has Read or Write permission | Not recorded | Owner UI check required (§6) |
| Per-position `mirrorID` | Present on `/pnl` positions | **Ignored (gap)** | Parsed. A non-zero value is a reconciliation discrepancy |
| Deprecated v1 open by-amount/by-units | Deprecated / not in current Swagger | n/a | Refused by the allowlist |

## 3. SideDeck-owned position isolation

Each step must succeed before ownership exists:

1. Signed approval for the exact scope (`book:instrument:units:limit:referenceId`), kill-switch clear, and owner policy: instrument allowlist, notional cap, maximum open positions per book. The policy has **no default**.
2. Write-ahead: an outbox intent (`broker=etoro`, `account_scope=etoro-demo`) plus a lineage row `PENDING_SUBMIT`, both written before the transport call.
3. The acceptance must echo `referenceId`. The `orderId` is linked once; a changed or duplicated `orderId` is refused, and so is any baseline `orderID`.
4. The lookup proves `positionExecutions[].openingData.orderId == orderId`. Only then is `positionId` registered to the book. A baseline `positionId` trips the kill-switch.
5. Reconciliation runs `reconcile_demo` plus lineage checks:
   - a SideDeck position missing at the broker;
   - a closed-local position still open at the broker;
   - unit drift;
   - a SideDeck-order position without lookup lineage;
   - mirror children.

   Any discrepancy trips the kill-switch.

A manually opened position in the same instrument stays in `etoro-demo:unattributed` and cannot be closed (tested).

## 4. Offline desk

`application/sd036_etoro_demo_desk.py` ties together outbox, approvals, kill-switch, lineage and a transport. The only acceptable transport is `OfflineEtoroDemoSimulator`, which is deterministic and labelled `OFFLINE_SIMULATED_NOT_BROKER_EVIDENCE`. Any other transport raises `BrokerExecutionDisabled`.

Rehearsal (no network):

```powershell
.venv\Scripts\python.exe -m sidedeck.application.sd036_etoro_demo_desk --rehearse
```

Expected output:

- `open_submit=OUTCOME_UNKNOWN` (lost response);
- `recovery=["FILLED"]` (by `referenceId`, exactly one POST);
- `baseline_close_refused=true`;
- `close=FILLED`;
- reconciliation `MATCHED`;
- `authenticated_requests=0`.

Tests: `tests/test_sd036_etoro_demo_desk.py` (61 cases) cover:

- the Real and agent-portfolio route refusal;
- the unlisted Demo routes;
- body shape and exact-Decimal refusal;
- 13 adversarial lookup payloads;
- foreign close positions;
- simulator-only attachment;
- approval scope exactness;
- policy caps;
- lost and never-received responses with no resubmission;
- restart recovery;
- rejected and partial outcomes;
- a broker naming a baseline position;
- `referenceId` reuse;
- all four baselines unclosable;
- same-instrument non-ownership;
- stale and tampered snapshots;
- over-unit closes;
- partial→full close;
- a lost close response;
- missing positions;
- mirror children;
- AST checks that there is no network import, Real path or credential access.

## 5. Agent Portfolios evaluation: `NOT_ADOPTED_PENDING_EVIDENCE`

What the docs say:

- `POST /api/v2/agent-portfolios` creates a portfolio funded by `investmentAmountInUsd`, which is *deducted from the caller's account balance*. Positions are mirrored proportionally, as a copy trade with a `mirrorId`.
- `GET /api/v1/agent-portfolios` lists bearer scopes `etoro-public:real:read/write` or `agent-portfolio:*`.
- The docs do **not** state whether an agent portfolio is Demo or Real, or that it is isolated from the parent account.

Assessment:

- **Real-money risk.** The documented scopes are Real-account scopes, and creation moves funds. That conflicts with the permanent Real exclusion.
- **It is not isolation.** The result is a copy/mirror inside the parent account. SideDeck's parser treats mirrors as unsupported discrepancies (now also per position).
- **It is a write.** Creation is a funded write that issues new user tokens. That is outside every current authorization.

Verified lineage on the direct Demo account gives the isolation needed without these risks. Re-evaluate only if eToro documents a Demo-only, non-mirrored agent portfolio. Route refusal is tested.

## 6. Residual risks

| ID | Risk | Mitigation / status |
|---|---|---|
| R1 | Baseline unchanged since 2026-10-20 is unverified | Bounded read (§7) |
| R2 | Key environment (Demo/Real) and permission (Read/Write) unverified | Owner UI check in the eToro API portal, no API call. A Real or Write key must not be used for reads |
| R3 | A lost **close** response cannot be recovered by order ID; operator `/pnl` reconciliation is needed | Kill-switch trips; `refresh_close` refuses until reconciled. Docs suggest `orders:lookup` may cover close orders, but this is unverified |
| R4 | Shared write rate limit (20/60 s) not enforced client-side | Must be added before any release |
| R5 | No HTTP transport exists for Demo writes; key scoping and `x-request-id` idempotency are unverified live | Intentional. A release needs a reviewed transport and owner G4 approval |
| R6 | Lookup field casing differs in doc examples (`positionId` vs `positionID`) | Parsers are strict; a live schema check is needed before release |
| R7 | Owner manual changes to baseline positions halt SideDeck | Fail-closed by design; documented |
| R8 | No capital allocated to strategy books | `NOT_ALLOCATED` until an audited owner decision |

## 7. Proposed bounded owner decision (not authorized, not executed)

**SD-038: one owner-run, read-only eToro Demo baseline re-reconciliation.**

- **Endpoint:** exactly one `GET https://public-api.etoro.com/api/v1/trading/info/demo/pnl`.
- **Tooling:** the existing CLI, *without* `--capture-baseline`:
  `.venv\Scripts\python.exe -m sidedeck.application.etoro_demo_portfolio --confirm-owner-demo-read --db data\etoro_demo.sqlite3`
- **Request cap:** 1. No retry, polling or second path.
- **Credentials:** `ETORO_API_KEY`/`ETORO_USER_KEY`, loaded by the owner into the session. Preferably a **Demo-environment, Read-only** key (confirm in the portal UI first; R2).
- **Purpose:** confirm that the four protected baseline positions still match, that no unattributed or mirror positions appeared, and that the key still works. This closes R1.
- **Output:** counts and statuses only. No balances, IDs or raw response.
- **Not included:** orders, closes, lookups, agent-portfolio calls, Real endpoints, or capital allocation.

Demo order release (SD-011) remains a separate, later decision that requires R2–R6 to be resolved first.
