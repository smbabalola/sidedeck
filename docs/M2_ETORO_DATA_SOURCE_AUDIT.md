# M2 data-source access decision — 2026-10-20

## Verified eToro capabilities (existing local evidence only)

| Capability | Status | Evidence / limitation |
| --- | --- | --- |
| Demo positions, status, cash and P&L parsing | VERIFIED READ-ONLY | Owner-authorized Demo GET and subsequent MATCHED refresh; dashboard withholds monetary amounts |
| v1 symbol / instrument lookup | VERIFIED FOR AAPL | Authenticated GET `/api/v1/market-data/search?internalSymbolFull=AAPL`, HTTP 200; normal AAPL distinct from .RTH, .24-7 and .EUR |
| Candles, historical OHLCV and consolidated closing prices | NOT VERIFIED | The symbol-search success is not evidence of access, bar completeness, SIP consolidation, or corporate-action adjustments |
| Issuer SEC filings / detailed financial statements | NOT VERIFIED FROM ETORO | No verified eToro fundamental statements endpoint or audited provenance mapping for the BuffettAgent contract |
| Demo/real order submission | NOT AUTHORIZED | All SideDeck execution remains disabled; P4 NO-GO |

**Correction to earlier verbal assessment:** an older v1/v2 AAPL probe failed HTTP 403 (Cloudflare 1010), but a subsequent transparent SideDeck User-Agent one-shot **v1** AAPL search returned HTTP 200. Do not collapse these into a permanent eToro market-data denial. Exact cause of earlier 1010 was not proven.

## Data-source policy for M2

1. eToro Demo is the source of *broker-side portfolio state*, under explicit owner-initiated GET authorization. Existing baseline positions remain protected. No broker call is part of research CI.
2. SEC Company Facts and original filings are the primary sources for issuer accounting metrics, with filing availability time, units, per-period reconciliation, share classes, and accounting interpretation tracked. Unapproved metrics stay excluded.
3. Alpaca IEX history is an existing market-price evidence source; its limitations for consolidated close, corporate actions, and valuation remain explicit. Do not mark an IEX-only close as verified SIP close.
4. eToro instrument search is a proven **optional reference for identity mapping**, not a substitute for price or issuer-fundamentals validation. A future eToro candle or fundamentals endpoint may be considered only after documentation, entitlement, response semantics, approved read-only probe, and independent reconciliation.
5. The first non-financial research acceptance candidate is MSFT, **candidate only**. Coverage is unverified. SOFI retains bank-profile NO-GO; supplementary borrowings/equity is not accepted as generic debt/equity. No provider model call is authorized.

## Follow-on engineering work (offline first)

- Produce an endpoint/permissions matrix directly from the eToro API portal and existing adapters, with version, HTTP method, auth requirements, pagination, historical coverage, data entitlement, adjustment basis, and explicit evidence status. Do not claim access from documentation alone.
- Design a *separate*, read-only, narrowly allowlisted market-data probe (never extend Demo portfolio client to arbitrary paths), initially offline fixtures. Any real authenticated probe requires an explicit owner approval for exact endpoint and request count.
- Check SEC MSFT coverage offline or obtain approved public SEC data separately with provenance; never invent dataset availability.
- Keep price-level valuation NO-GO until independently corroborated closes, share counts, corporate actions and publication timing are verified.
- Update TODO once implementation and tests actually run.

No authenticated eToro, model, Financial Datasets, Alpaca, or broker order request was made for this audit.
