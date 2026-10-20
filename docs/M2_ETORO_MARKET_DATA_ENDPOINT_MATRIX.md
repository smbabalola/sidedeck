# M2 eToro market-data endpoint matrix (offline documentation review)

Status: **DOCUMENTED, NOT ENTITLEMENT-VERIFIED**. No authenticated requests during this review.

| Purpose | Exact documented GET route | Verified access? | M2 usage / limitation |
| --- | --- | --- | --- |
| Instrument search | `/api/v1/market-data/search?internalSymbolFull=AAPL` | **YES**, only the prior AAPL one-shot HTTP 200 | Exact symbol + exchange identity required; related AAPL.RTH / 24-7 / EUR instruments are distinct |
| Closing prices | `/api/v1/market-data/instruments/history/closing-price` | **NO** | Response documents `officialClosingPrice` and daily/weekly/monthly closes; do not assume this is an exhaustive historical daily series, SIP consolidated, split adjusted, or entitled |
| Candle history | `/api/v1/market-data/instruments/{instrumentId}/history/candles/{direction}/{interval}/{candlesCount}` | **NO** | Candle semantics, aggregation, gaps, trading session, corporate actions and price source still require response and documentation verification |
| Demo portfolio | `/api/v1/trading/info/demo/pnl` | **YES**, owner-run reads | Baseline-protected read only; never use for historical price validation |
| Audited financial statements | No validated eToro endpoint | **NO** | SEC company filings remain accounting source; never treat market-data response as full issuer financial disclosure |

Official documentation:
- https://api-portal.etoro.com/api-reference/market-data/get-historical-closing-prices
- https://api-portal.etoro.com/api-reference/market-data/get-instrument-candle-history
- https://api-portal.etoro.com/guides/get-instrument-id
- https://api-portal.etoro.com/getting-started/authentication

### Safety boundary

This document is an **offline endpoint inventory**, not permission to probe. A future authenticated GET requires a separately explicit owner approval naming exact endpoint, instrument, and request count. No credentials or raw account payload in GitHub/CI. Do not widen `EtoroDemoReadClient`'s portfolio allowlist, grant writes, or change order execution. New market-data adapter must be independently sandboxed and GET-only.

### Valuation acceptance boundary

The term `officialClosingPrice` is **eToro's documented field name**, not SideDeck validation of a US consolidated/SIP-close benchmark. Do not approve MSFT/SOFI market cap or historical P/E before independently verifying the ticker/instrument, trading date, close type, share count date/classes, split basis, and original filing release time.

### MSFT candidate

MSFT is the proposed first non-financial research instrument. SEC coverage, TTM reconciliation, statement consistency and price validation **have not yet been established** in SideDeck. No local MSFT data file was available to this remote GitHub documentation audit; do not invent measured coverage. Review locally cached files before fetching any permitted public SEC dataset.

### Next offline implementation

1. Build synthetic fixture-backed, fail-closed parsers for documented candles and closing prices, separately from the Demo portfolio adapter.
2. Inspect the exact source documentation for required query/path parameters, candle and close adjustment semantics, completeness and timestamps.
3. Build MSFT SEC coverage reporting from existing SEC mapping with independent filed-quarter reconciliation; expose unavailable and non-applicable metrics.
4. Keep first real dual-agent run NO-GO until both frameworks, evidence, bounded model cost and explicit owner authorization pass.
