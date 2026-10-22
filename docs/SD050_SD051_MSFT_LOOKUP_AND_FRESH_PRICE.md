# SD-050 MSFT instrument lookup result, and SD-051 fresh-price / eligibility preflight (2026-10-22)

## SD-050 — authorized one-shot MSFT lookup: **FAILED_UNVERIFIED (ID still unresolved)**

| Field | Value |
|---|---|
| Authorization | Owner, 2026-10-22: one read-only lookup, no retry |
| Request | exactly 1 `GET https://public-api.etoro.com/api/v1/market-data/search?internalSymbolFull=MSFT&fields=…` (the documented `fields` parameter is required) |
| Credentials | single Demo pair (ADR-004), loaded in-process; never printed |
| HTTP status | **200** |
| Attempts | **1 / 1** (budget `data/sd050-auth-budget.sqlite3`, outcome `NO_EXACT_MATCH`) — **consumed; not retried** |
| Result | Refused by SideDeck's acceptance rule: "exact match is not a stock" |

**Cause:**
- The response contained a candidate that passed the exact-symbol, Nasdaq, valid-ID and not-delisted checks.
- It failed only the instrument-type check. Most likely `instrumentType` was absent from the returned fields or used a different label.
- The runner did not persist rejected responses, so the ID was not retained, and it is **not guessed**.

**Remediation (offline, tested):**
- On rejection, the runner now records sanitized diagnostics: field names, JSON types and the type and exchange labels.
- It rejects only a type that is *present and clearly not a stock*.
- Each owner authorization has its own id and one-attempt budget. `SD-050` was verified to remain exhausted, and a budget-path regression was found and fixed before use.
- **A new owner authorization is required for one more lookup.** Alternatively, the owner can supply the ID.

## SD-051 — fresh-price and eligibility preflight; revised 12-request budget

The owner authorized the MSFT pilot with a ceiling of 12 requests and at most 2 writes. The plan is now:

| Step | Endpoint | Cap |
|---|---|---|
| Portfolio pre / post-open / final | `GET /api/v1/trading/info/demo/pnl` | 3 |
| Eligibility (read-only POST) | `POST /api/v2/trading/info/demo/eligibility` | 1 |
| Fresh reference | `GET /api/v2/market-data/rates?instrumentIds=<id>` | 1 |
| Open | `POST /api/v2/trading/execution/demo/orders` | **1** |
| Open outcome | `GET /api/v2/trading/info/demo/orders:lookup` | 3 |
| Close | `POST …/market-close-orders/positions/{id}` | **1** |
| Close outcome | `GET …/close-orders/{orderId}` | 2 |
| **Total** | | **12 (2 writes)** |

- **Signed intent (C8 schema v2):** fixes the instrument, **units**, a **maximum** limit (≤ 5 % over the signed planning reference), units × max ≤ USD 50, the request caps and a ≤ 8 h window.
- **Preflight, which makes no write and aborts cleanly on any failure:**
  1. Baseline MATCHED, with nothing pending and no SideDeck position.
  2. **Eligibility:** open and close allowed; units-based; fractional allowed if the units are fractional; units ≤ `maxUnitsPerOrder`; a long 1× configuration exists; notional ≥ eToro's minimum (`minPositionExposure` and `minPositionAmount`).
  3. **Fresh quote:** exactly the pilot instrument; `quoteType=realtime`; sane bid/ask; at most 60 s old.
  4. **Limit** = min(signed max, ask × 1.005 rounded down to the cent), refused if the ask is above the signed max. **0.5 % over the fresh reference therefore holds by construction.**
- **Separate approval:** the owner then signs the SD-033 open approval for the exact derived request. The open is refused if the quote is more than 5 minutes old.
- **Layered enforcement:**
  - the desk requires units equal to the signed units and a limit ≤ the signed max;
  - the transport pins every open field, `limitRate` ≤ the signed max, the eligibility body and the rates query (signed instrument only);
  - market-data rates is the **only** non-`/demo/` route allowed (exact path, GET only).

Tests: SD-046 pilot (gates abort before any write: stale, delayed or too-high quote; whole-units-only; minimum size; open not allowed; amount-only; old quote at open), SD-048 (route exception exact and GET-only, parser failures, pinned query and body), SD-050 (lookup).

## Second independent security review (2026-10-22) and remediation

A separate read-only review of the SD-050/SD-051 changes found 1 HIGH, 2 MEDIUM and 4 LOW issues. All are fixed with regression tests:

| # | Finding | Fix |
|---|---|---|
| H | The lookup budget could be bypassed with id variants (a leading space, `SD_050`, `../`), a different working directory, or a deleted budget file | Ids must fullmatch `SD-[0-9]{3}` **and** be listed in reviewed code (`AUTHORIZED_LOOKUP_IDS`, currently empty). `SD-050` is refused unconditionally (`EXHAUSTED_LOOKUP_IDS`). Budgets are anchored to the repository `data/` directory |
| M | The 0.5 %-over-fresh-ask rule lived only in the runner | The desk now requires the `FreshQuote` and `Eligibility` evidence for any signed-release open. It re-checks the instrument, that the quote is ≤ 5 min old, ask ≤ limit ≤ ask × 1.005, the minimum size and fractional units |
| M | The lookup bypassed the network lock | `LOOKUP_NETWORK_ENABLED = False`. A future lookup needs a reviewed commit for a new owner-authorized id |
| L | Eligibility accepted any settlement type, `True` as leverage 1, or a missing currency | Requires `settlementType=real`, integer leverage 1 and currency `USD` |
| L | Permissive lookup acceptance | `isDelisted` must be exactly `False`, and the exchange label must be exactly `Nasdaq` |
| L | Proxy environment variables could receive auth headers | Both openers use `ProxyHandler({})` |
| L | Exception text on refusal | Only policy names and statuses; no credential values (confirmed) |

The reviewer confirmed sound: quote parsing and time handling, limit derivation, budget arithmetic (12 / 2 writes), the exact market-data route exception, pinned bodies and queries, halt handling, and no credential leakage.
