# SD-105 incident — eToro Demo MSFT buy filled, SideDeck halted on a lookup 404 (2026-10-26)

## Outcome

First broker-confirmed eToro **Demo** order from SideDeck. The BUY reached eToro and filled.
SideDeck did not recognise the fill, tripped its kill switch and never offered the close.
Result `UNRESOLVED_OPERATOR_INTERVENTION_REQUIRED`. No second write, no retry, no close by
SideDeck. Transport re-locked (`7ef0997`, CI green).

## Evidence (offline; `data/sd054-evidence-20261026-1722`, SHA-256 per file recorded in TODO)

| UTC | Step | Result |
|---|---|---|
| 17:14:52 | `/pnl` | 200; 4 protected positions; baseline MATCHED |
| 17:14:53 | eligibility | 200 |
| 17:14:53 | rates #1 | 200; quote 83.6 s old → stale-only re-read (Option B) |
| 17:15:09 | rates #2 | 200; fresh |
| 17:17:45.82 | **open** POST (limitIOC, 0.09 units, limit 533.68) | **200**; `orderId` 3905…2302; `referenceId` echoed our `x-request-id` → lineage `ACCEPTED` |
| 17:17:46.61 | **lookup** `orders:lookup?referenceId=` | **HTTP 404** (`TransportNotFound`; body not captured) |
| 17:17:46.62 | kill switch | `HALTED`: "accepted order missing from broker lookup" |

6 requests of 15, 1 write of 2. Owner (eToro UI, after the run): open MSFT LONG 0.09 units,
average open 530.65, value ≈ USD 47.75; five assets (four protected + MSFT). Fill 530.65 is
within the 533.68 limit; notional ≈ 47.76 ≤ USD 50.

## Defect

1. **Lookup fired 0.8 s after acceptance**, with no wait (`sd046` open loop).
2. **A 404 for an order whose acceptance was verified was treated as final**
   (`sd036.refresh_open`: "broker no longer reports an accepted order") — halting on the first
   attempt and abandoning the two remaining signed lookups. eToro documents 404 only as
   "Order not found" and gives no consistency guidance; the owner-observed position shows the
   order existed and filled. Whether the 404 was a visibility delay or a `referenceId`-specific
   miss is **not determinable** from the evidence (the 404 body was not kept).
3. **No fallback identity:** the lookup supports `orderId` (documented), which SideDeck held
   but never used; `/pnl` carries `orderID` per position and was not consulted.
4. **Evidence gap:** the 404 ProblemDetails body was discarded.

This was not a response-parsing failure: the acceptance parsed and the lineage
(`referenceId → orderId`) was correct.

## Fix (offline; transport stays LOCKED)

- Open lookups wait **3 / 5 / 8 s**; the first uses `referenceId`, any after a 404 use the
  linked `orderId`. A 404 for a linked order raises `AcceptedOrderNotVisible` (no halt) in the
  pilot path; the generic `recover()` path still halts.
- If the order is never visible: **strict `/pnl` recovery** — exactly one position whose
  `orderID` equals the linked order, same instrument, long, 1×, not mirrored,
  0 < units ≤ requested, `openRate` ≤ limit, not a protected position; anything else halts.
  It also refuses if the order is still pending at the broker or the whole snapshot does not
  reconcile (protected positions MATCHED, nothing unexplained). It runs only for a never-seen
  accepted order, and only if the signed `/pnl` cap leaves room for recovery + close + final.
- An interrupt (Ctrl-C) during the lookup waits trips the kill switch before re-raising.
- 404 ProblemDetails (`status`, `title`, `detail`; bounded; UUIDs and 5+ digit runs masked;
  `instance`/`traceId` dropped) kept in the audit.
- `/pnl` `openRate` parsed (optional).
- Tests: `tests/test_sd105_open_lookup_recovery.py` (34). Independent review (Fable,
  2026-10-27): no blocker; 2 medium (pending orders, whole-snapshot reconcile) and 3 low
  (explicit reason, interrupt, identifier masking) fixed with tests. Full suite 1695 passed /
  1 skipped; ruff, mypy, alembic clean.

## Owner decision needed (not applied)

With today's signed allocation (`pnl` 3, `lookup` 3) the `/pnl` recovery cannot also leave
room for the close, so it **refuses** and stops. Enabling it needs the `pnl` ceiling raised
3 → 4 and `lookup` 3 → 2 in a newly signed intent (totals unchanged: 15 requests, 2 writes).

## Current position (not reconciled by SideDeck)

SideDeck lineage: open `ACCEPTED`, no owned position, kill switch `HALTED`. The broker
position is **owner-observed only**; SideDeck has not read it. Reconciling it needs either
(a) one owner-approved read-only `/pnl` GET, or (b) the owner's manual close in the eToro UI
plus its confirmation. Neither is assumed. The kill switch stays halted until then.
