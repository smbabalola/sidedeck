# P5 SEC/Alpaca valuation evidence report

Generate a read-only audit from locally verified inputs:

```powershell
.\.venv\Scripts\python.exe -m sidedeck.application.p5_valuation_evidence --fundamentals data/sofi-multimetric-v5.json --prices data/sofi-alpaca-iex-full.json --output data/sofi-valuation-evidence-v1.json
```

This consumes the previously downloaded **SEC annual diluted EPS** and **Alpaca IEX split-adjusted daily price** data without downloading anything or placing broker orders. It refuses to overwrite an existing audit.

It records the SEC annual EPS filing date and source accession, the first existing price within four calendar days beginning on that date, and the market bar source identifier. Individual observations are classified as:

- `PRICE_WINDOW_UNAVAILABLE`: no available market close in the date window
- `P_E_NOT_MEANINGFUL`: filed diluted EPS is zero or negative, but a matching close exists
- `P_E_VALIDATION_PENDING`: positive EPS and close exist, but price/EPS share basis is not proven

**A date match is not a validated valuation.** In particular, same-day prices may precede after-close publication, split-adjusted prices may not match filed per-share data, and IEX coverage is not SIP consolidated market history. The audit therefore always reports `historical_pe_validated=false`, `corporate_actions_verified=false`, `release_timing_verified=false`, `buffett_ready=false`, `assessment=NO_GO` and `broker_execution=DISABLED`. It emits **no numeric P/E**, even if a source JSON asserts verified corporate actions.

Acceptance work remains: obtain original filing release timestamps, corroborate trading-calendar prices, independently reconcile corporate actions and EPS share basis, validate Buffett quarterly metrics and both independent upstream agent inputs.
