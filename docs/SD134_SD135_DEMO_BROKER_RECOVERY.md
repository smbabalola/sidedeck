# SD-134 / SD-135 — bounded eToro Demo acceptance recovery and close-info boundary

**2026-10-27 — OFFLINE ENGINEERING, NOT A BROKER RELEASE.** The exact
production DAY eToro route stays `NOT_RELEASED` and the historical
supervised MSFT pilot's kill switch remains HALTED pending separate owner
approval. There have been no new API calls or orders.

## Why this is necessary

On 26 October the owner-approved MSFT Demo buy POST returned HTTP 200,
referenceId echoed, accepted orderId recorded. An immediate
`orders:lookup?referenceId=` returned HTTP 404 around 0.8 seconds after
acceptance, even though the owner subsequently saw a new 0.09-unit position.
This is **not** evidence the order failed. The owner manually closed it and
a separate, authorised Demo `/pnl` GET later matched the four protected
original holdings. See `docs/SD105_OPEN_LOOKUP_404_INCIDENT.md`.

The SD-105 pilot-specific recovery already implements waits, orderId
fallback and strict `/pnl` lineage checks. This batch hardens the new
transport-neutral **SD-129 order port** for a future policy-bound gateway
without modifying that locked supervised transport.

## Implemented in SD-134

- `EtoroDemoOrderPort.submit_open` reserves the reference before the
  only permitted POST attempt, even when the transport later throws or the
  acceptance response is malformed. The same port refuses a second POST
  for that reference; this **does not** replace durable SD-063 outbox.
- A genuinely parsed open acceptance is bound to the port's local session;
  recovery refuses hand-crafted/untrusted acceptance and cannot resurrect
  acceptance after restart. Restart requires **durable signed lineage** from
  the production policy ledger, not re-signing fake objects.
- `recover_accepted_open` requires **two injected audit/schedule hooks**,
  one before the initial referenceId GET and one before an orderId fallback.
  Only an actual lookup HTTP 404 allows the second GET; there is a maximum
  of two read calls and **no additional POST**. No built-in sleeping,
  polling, retries, release or market-clock authority exists. The
  production runner must enforce measured 3/5/8-second wait intervals,
  scoped budgets and owner-signed request allowances.
- The returned state is explicitly `BROKER_CONFIRMED_OPEN`,
  `TERMINAL_NO_FILL`, `UNRESOLVED`, or
  `UNRESOLVED_NOT_VISIBLE`; no acknowledgement is ever called a fill.
  Nonterminal, closed-manually or twice-404 evidence requires external
  operator/strict `/pnl` reconciliation. Mismatched accepted orderIds
  fail closed.
- A newer order lookup invalidates prior session-local position evidence.
  The adapter refuses close using an older `ConfirmedOpen` after a newer
  lookup reports the position closed.
- A full reduce-only close may be **attempted only once per position in
  this adapter session**; unknown outcomes cannot be POST-retried.
  `lookup_close` now demands the actual close acceptance from this port.

## SD-135 closing distinction

The documented `GET /api/v1/trading/info/demo/close-orders/{orderId}`
provides an order status and closed units but **no execution price**.
SideDeck classifies its results conservatively:

- `BROKER_REPORTS_FULL_CLOSE_PENDING_PORTFOLIO_RECONCILIATION`
  when status is FILLED and reported units exactly equal the owned amount;
  this is **not** final flat, verified P&L or a complete cycle.
- `BROKER_REPORTS_NO_CLOSE` for terminal no-close outcomes;
- `UNRESOLVED_PARTIAL_OR_PENDING` for incomplete and pending outcomes.

Only a separate permissioned, fresh Demo `/pnl` snapshot may establish
baseline matching and a flat account; a valid broker execution-price source
is still needed for true realised P&L. Never use the planned bid as fill price.

## Tests / evidence

`tests/test_sd134_demo_order_recovery.py` uses an **offline fake-route
only**, covering accepted POST → referenceId 404 → accepted orderId lookup
→ position → full owned close → close-info, plus both-404, wrong orderId,
pending order, previously manual-closed position, forged acceptance,
crash/restart, attempted duplicate POST, failed close, duplicate close,
stale cached owner, partial close and absent broker settlement/P&L.

No credentials, eToro market data, account reads, sockets or order execution
are required by these tests. CI run for final code must be recorded in TODO.

## Not done: release blockers

This port is transport-neutral, not wired to an owner-signed production
gateway. Its guards are **in memory only** and cannot substitute for
restart-durable outbox/approval/position state, off-machine policy and
grant-use anchors, independently reviewed lifecycle and protective close,
signed bounded virtual-cash policy, strategy OOS admission or separately
licensed complete-session five-minute data. The four existing Demo holdings
remain protected by the existing gateway/portfolio policy (not by this
port's session-local cache).

eToro AAPL market-data search returned independent HTTP 403; earlier
supervised Demo trading POST and Demo `/pnl` GET both returned HTTP 200.
That market-data denial does not negate the demonstrated supervised trading
permission and does not authorise a new order.
