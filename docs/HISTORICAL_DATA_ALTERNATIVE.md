# SD-11E — Five-year historical-data alternative (code-only)

**Reviewed:** 2026-10-18. **Status:** source identified and offline parsing in development; no third-party data feed is connected.

## Decision

Leave eToro's failed market-data API test in `LOCAL_ETORO_MARKET_DATA_403`. The owner says the eToro key pair came from the same active Main-account key setup, the Market Data — Read checkbox is enabled, and the previous one-shot live-read permission is exhausted. **No eToro retry, account query, order request, trading authorization or key rotation is permitted.** Prepare a support ticket via eToro's official Customer Service Centre: https://www.etoro.com/customer-service/ . Developer-specific queries may also be raised through https://builders.etoro.com/community . Never include credentials or full HTTP headers in a ticket.

## Candidate: Tiingo EOD stock data

Official documentation and terms:
- Free individual tier https://www.tiingo.com/about/pricing — claims **30+ years** price history, 500 unique API symbols/month, 50 calls/hour, 1,000/day, 1GB bandwidth/month. **Internal personal use only**, with no data redistribution. Different product's **screener** may have separate 5-year limits; do not confuse screener history with EOD API history.
- EOD API https://www.tiingo.com/documentation/end-of-day — `GET /tiingo/daily/{ticker}/prices?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD`, plus `GET /tiingo/daily/{ticker}` metadata. Raw OHLCV, adjusted OHLCV, `divCash` and `splitFactor` are documented. Publication/correction timing means a backtest may **not** assume today's retrospectively adjusted series is a point-in-time archived snapshot.
- Product/rights summary https://www.tiingo.com/products/end-of-day-stock-price-data — raw and adjusted price history. Data availability per AAPL/MSFT/SPY/QQQ, adjustments, API token eligibility and personal-use licensing must be verified by the account holder **before any data request**.
- Another candidate, Alpha Vantage, advertises 25+ years EOD but documents that `TIME_SERIES_DAILY?outputsize=full` is **premium-only**, so its free 100-row compact response cannot satisfy five years. Source: https://www.alphavantage.co/documentation/ .

## SD-11E tasks

1. Implement a **pure, credential-free, network-free parser/validator** for official Tiingo EOD JSON records. Approved tickers only AAPL, MSFT, SPY, QQQ. Validate all documented fields (raw/adjusted OHLCV, `divCash`, `splitFactor`); date ordering, no duplicates/future dates, Decimal finite values, OHLC relationships, zero-volume handling; fail closed. Require documented licence confirmation. Keep the original response only in local ignored `data/`, never commit any provider data.
2. Keep **a full historical daily-bar collection separate from `MarketBundle`**, which currently represents one decision-time snapshot per instrument. Add a safe point-in-time replay bridge later; do not present present-day corrected EOD bars as what an agent knew historically.
3. Assess a **five-year calendar coverage gate** with a verified external exchange-session calendar (NYSE/NASDAQ as applicable), weekend/holiday handling, corporate-action consistency, raw/adjusted schema, origin hash, and coverage unknown until actual legitimate data is available. No interpolation or weekly-as-daily substitution.
4. Prepare a **disabled-by-default** read-only Tiingo GET adapter only after owner accepts the free-tier personal-use terms, local key arrangement and exact request scope. Do **not** use or request any Tiingo token now. All tests offline.
5. Improve risk-aware offline historical replay: chronological train/validation/holdout splits, no lookahead across adjustment vintages, deterministic fees/slippage, benchmark (SPY/cash), walk-forward evidence. Backtest engine status must remain `NOT_VERIFIED` until price history obtained and assessed.
6. Continue independent work while waiting for eToro support; preserve `SideDeck-Blueprint/`, ignored `.env`, demo ledger and branch; keep PR #1 unmerged, real and Demo broker trading disabled.
