# SD-049 — MSFT eToro Demo pilot: release checklist and blockers (2026-10-22)

**Status: NOT READY.** Updated 2026-10-22 after SD-050/SD-051: B3 and B4 are now automated pre-order gates; B1, B5 and the owner's intent signature remain. `ETORO_DEMO_EXECUTION_RELEASE=NO_GO`, `broker_execution=DISABLED`, `NETWORK_TRANSPORT_ENABLED=False`. This checklist was prepared fully offline. The owner's selection of MSFT is not authorization to send an order.

## Owner-selected configuration

| Parameter | Setting |
|---|---|
| Broker | eToro Demo only |
| Instrument | MSFT (Microsoft), eToro instrument ID **unresolved** |
| Book / capital | `etoro-demo:tradingagents`, ≤ USD 50 virtual (owner-confirmed 2026-10-22; closes C9) |
| Order | Buy, 1×, `limitIOC`, limit ≤ +0.5 % over a **verified, fresh** reference |
| Positions / exit | 1; full close of only the lineage-verified position |
| Requests | 11 total, 2 writes (current signed plan) |

## Offline evidence gathered

| Check | Result |
|---|---|
| C3 owner signing key | ✅ `data/approval_allowed_signers` holds 1 valid `ssh-ed25519` key. The owner's signature over test digest `cabc8db0…fb4a` **verifies**; a tampered digest is rejected. Pilot releases use the separate namespace `sidedeck-etoro-pilot-release` |
| Credentials (C1) | ✅ single Demo pair policy (ADR-004) |
| Baseline (C4) | ✅ 4/4 MATCHED (SD-038, 2026-10-21) |
| C7/C8 | ✅ built, locked and security-reviewed (SD-048) |
| Indicative sizing (planning only) | The last local MSFT SIP split-adjusted close is 2026-10-20 at **$531.87** (Alpaca SIP, research-only). A +0.5 % limit ≈ $534.52 gives **≈ 0.093 units ≈ $49.7**. This is stale and **not** a verified reference |

## Blockers (each must close before the owner is asked for the signed release)

| # | Blocker | Why | Proposed resolution |
|---|---|---|---|
| B1 | **MSFT eToro instrument ID unknown** | Orders and the baseline check are by ID. Only AAPL = 1001 is verified locally; guessing is not allowed | **Bounded read (needs owner authorization):** exactly 1 `GET /api/v1/market-data/search?internalSymbolFull=MSFT`, no retry, exact-symbol match (Nasdaq, USD) required. Alternatively, the owner supplies the ID from a trustworthy eToro source |
| B2 | MSFT must not be a protected baseline instrument | Pilot rule; a mistake must never touch the 4 positions | Automatic once B1 resolves: `PilotScope.validate` and C8 refuse any baseline instrument. Codex also checks offline against the baseline DB and reports yes/no only |
| B3 | **No verified fresh reference price** | The 0.5 % cap needs a reference taken at execution time, and local data is stale | Owner decision: either (a) add 1 rates read to the pilot preflight (12 requests, still 2 writes; needs an offline code change to caps and allowlist plus re-review), or (b) the owner enters the eToro-displayed price at signing time and the limit is derived from it. **Recommendation: (a)**, because it keeps the reference broker-sourced and logged |
| B4 | **Minimum order size and fractional step for MSFT unknown** | ≈ 0.093 units may fall below eToro's minimum or step, giving a rejection or a different fill | The owner confirms in the eToro Demo UI the minimum amount and whether fractional MSFT is allowed. Codex then fixes `units` to the confirmed step. If $50 is below the minimum, the pilot is redesigned rather than the cap raised silently |
| B5 | Trading window | `limitIOC` needs an open market; signed window ≤ 8 h | Owner picks a date. Recommended **10:00–11:30 ET** on a regular US session (away from the open and close auctions) |
| B6 | Network lock | Must stay `False` until release | A separate, reviewed commit flips it immediately before execution, and only after the signed C8 release |

C9 (capital) is closed by the owner's configuration. C10 is partially closed: MSFT is chosen, but its ID is pending (B1). C11 is B5.

## Exact next owner decisions

1. **Authorize B1:** one read-only MSFT search GET. Alternatively, supply the instrument ID yourself.
2. **Choose B3 (a) or (b).**
3. **Confirm B4** from the eToro UI: the minimum amount and fractional availability for MSFT.
4. **Pick B5:** a date in the recommended window.

After these, Codex prepares the canonical MSFT `PilotIntent` (exact units, limit, window) and its digest for the owner to sign. The final, separate step is the explicit pilot authorization together with the reviewed lock-lift commit.

## Update 2026-10-22 (SD-050 / SD-051)

| # | Status |
|---|---|
| B1 instrument ID | **OPEN.** The authorized SD-050 lookup returned HTTP 200 but SideDeck's type check rejected the candidate; the ID is not retained and not guessed. **The owner must authorize one new lookup**, which is enabled only by a reviewed commit with a new id and a temporary lock lift, or supply the ID |
| B2 baseline conflict | Automatic once B1 resolves |
| B3 fresh reference | **Implemented (SD-051):** a realtime rates read in the preflight (≤ 60 s); limit = min(signed max, ask × 1.005); re-checked by the desk |
| B4 minimum and fractional | **Implemented as a pre-order gate (SD-051):** a Demo eligibility read in the preflight. If fractional units, minimum size, units-based orders or a long 1× real-stock configuration are not allowed, the pilot aborts **before any order**. No separate request is needed |
| B5 window | **OPEN.** Owner to pick a date; 10:00–11:30 ET recommended |
| Intent signature | Pending B1 and B5: Codex will prepare the canonical schema-v2 intent and digest for the owner to sign (namespace `sidedeck-etoro-pilot-release`) |
| Request plan | 12 requests / 2 writes (owner ceiling), enforced by the signed caps, the transport ledger and the pilot budget |
