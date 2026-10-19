# P5 historical price evidence contract (offline)

The historical price comparison is a **strict local JSON import**, not a connected market-data feed. SideDeck does not automatically source historical prices in this phase, and a claimed source URL or a `corporate_actions_verified` boolean does not independently prove authenticity. Review each input against an authorized data vendor before relying on it.

Example local price JSON schema:

```json
{
  "ticker": "SOFI",
  "currency": "USD",
  "price_basis": "split_adjusted_close",
  "corporate_actions_verified": true,
  "source": "https://YOUR-AUTHORIZED-MARKET-DATA-PROVIDER.example/",
  "records": [{"date": "2025-02-03", "close": 12.0, "source_id": "VENDOR_RECORD_ID"}]
}
```

Values shown above are **illustrative only**, not SOFI historical market prices. Never label synthetic examples as real investment evidence.

Run: `python -m sidedeck.application.p5_historical_prices --fundamentals data/sofi-multimetric-v5.json --prices PATH_TO_VERIFIED_PRICE_JSON`. The command returns a nonzero exit code because its output is **NO_GO**. It does not call providers or brokers.

The preliminary comparison uses a closing price at or within three calendar days after a *public annual EPS filing date*. It rejects future prices, duplicate dates, absent provenance, mismatched tickers or wrong currency. This is a diagnostic illustration, **not** a validated historical P/E: corporate-action adjusted price and EPS may be on different per-share bases, filing-day release timing and exchange trading calendars have not been reconciled, and the price feed has not been authenticated. The next work is source-integrated price acquisition, date-exact earnings release handling, and independently validated adjusted EPS.

The separate Buffett multi-quarter research acceptance gate remains NO_GO. All trading disabled.
