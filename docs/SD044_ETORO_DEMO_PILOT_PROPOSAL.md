# SD-044 — Proposed first eToro Demo order pilot (DORMANT; not authorized)

**Status:** proposal only. Nothing here is approved or executed. `ETORO_DEMO_EXECUTION_RELEASE=NO_GO`, `broker_execution=DISABLED`, and eToro Real is permanently prohibited.

The owner's Demo **Read/Write** key permission (confirmed 2026-10-21) is a capability, not an authorization.

**Purpose:** prove, with the smallest possible footprint, that SideDeck can open one Demo position, recognise it by verified lineage, close exactly that position, and reconcile, without touching the four protected baseline positions.

## 1. Prerequisites (all must be true before the owner is asked to approve)

| # | Prerequisite | Owner / work | Status |
|---|---|---|---|
| P1 | Separate credentials: a Demo **Read-only** key for monitoring (`ETORO_API_KEY`/`ETORO_USER_KEY`) and the Demo Read/Write key under `ETORO_DEMO_TRADE_API_KEY`/`ETORO_DEMO_TRADE_USER_KEY`. `require_separated_execution_credentials` must pass (SD-042) | Owner (portal + local `.env`) | Not started |
| P2 | IP whitelist and expiry set on the Read/Write key (closes the rest of R2) | Owner (portal UI) | Unverified |
| P3 | Reviewed Demo write transport per `SD041_ETORO_DEMO_TRANSPORT_REVIEW.md`. It is only merged after the owner approves this pilot scope, because it replaces the SD-041 no-transport guard with a single-transport allowlist guard | Codex + owner code review | Not started |
| P4 | Real signature verifier for SD-033 approvals (for example, an owner-held Ed25519 key with the public key in config). The test lambdas are not acceptable | Codex (offline) + owner key | SD-045 READY |
| P5 | Pilot capital: an explicit owner allocation of a small virtual Demo amount to **one** book (R8) | Owner decision | Not allocated |
| P6 | Pre-flight `/pnl` read shows the baseline 4/4 MATCHED, with no pending orders | Within the pilot budget | — |

## 2. Proposed scope (values in **bold** are for the owner to confirm or change)

- **Book:** **`etoro-demo:tradingagents`** (the pilot is labelled, not a strategy decision).
- **Instrument:** one owner-chosen, liquid US large-cap stock. It must not be an instrument held by the four baseline positions, so a mistake cannot be confused with them.
- **Order:** buy, leverage 1, `limitIOC`, units-based, `limitRate` ≤ **+0.5 %** over the pre-flight reference price, notional ≤ **USD 50**. Placed during regular US market hours only.
- **Exit:** a full close of only the lineage-verified position, in the same session.
- **Approvals:** two signed approvals (open and close), each scoped to the exact `referenceId`, units and limit. Requester ≠ approver, and each expires within 15 minutes.

## 3. Hard request budget (persistent, reserved before each send, 0 retries for writes)

| Step | Endpoint | Max |
|---|---|---|
| 1 Pre-flight portfolio | `GET /api/v1/trading/info/demo/pnl` | 1 |
| 2 Open | `POST /api/v2/trading/execution/demo/orders` | **1** |
| 3 Open outcome | `GET /api/v2/trading/info/demo/orders:lookup?referenceId=` | 3 |
| 4 Post-open portfolio | `GET /api/v1/trading/info/demo/pnl` | 1 |
| 5 Close | `POST /api/v1/trading/execution/demo/market-close-orders/positions/{id}` | **1** |
| 6 Close outcome | `GET /api/v1/trading/info/demo/close-orders/{orderId}` | 3 |
| 7 Final portfolio | `GET /api/v1/trading/info/demo/pnl` | 1 |
| | **Total** | **11** (2 writes) |

No other endpoint is allowed: no Real, Agent Portfolio, market-data or SL/TP modification calls, and no cancels. If the open is rejected or not filled, steps 4–6 are skipped and only step 7 runs.

## 4. Kill criteria (any one halts the pilot; the kill-switch trips; no second open)

- Any baseline position missing or changed, or any mirror or unexpected position.
- An unknown open or close outcome. Recovery follows SD-036/SD-037: lookup by `referenceId` for opens, `/pnl` snapshot recovery for closes. Never resubmit.
- Any `response_shape_issues` finding (SD-043) on any response, any parser refusal, or a fill above the limit.
- Close-order status anything other than FILLED within the close-outcome budget.
- Rate-limit headers or HTTP 429, 401 or 403 on any request.

## 5. Success criteria and evidence

- Open FILLED, or a cleanly REJECTED with no executions. The lookup `positionExecutions[].openingData.orderId` equals the order, and exactly one new position is registered to the pilot book.
- Close FILLED for exactly that position. The final `/pnl` shows the baseline 4/4 MATCHED, zero SideDeck positions, and no discrepancies.
- Sanitized evidence only: statuses, counts, shape-check results and request budget usage. No IDs, prices, quantities or balances in git.
- A successful pilot does **not** release SideDeck execution. The next gate is SD-011 and the soak (SD-013).

## 6. What the owner would be asked to approve (later, in one message)

1. The P1/P2/P5 confirmations.
2. Merging the P3 transport after review.
3. Execution of exactly the scope in §2–§4, with the bold values filled in.
4. A fixed date window.
