# Saxo SIM AAPL details and info price

Confirmed from the Saxo paper account: `AAPL:xnas` is Stock UIC 211, with `AAPL:xmil` UIC 15777171 an unsuitable alternative for this US equity test. This batch adds read-only instrument detail and **indicative** info-price lookups via Saxo's official SIM endpoints. The result is **not** an executable quote, order precheck, authorization or fill.

With a valid token in the current PowerShell process:

```powershell
git pull --ff-only
.\\.venv\\Scripts\\python.exe -m sidedeck.application.saxo_instrument_readiness --expected-account-id "22866064"
```

Saxo may return restricted/missing trading status or delayed/unavailable quote data. Fail closed; do not infer permission or a fresh tradable price from these results. Account 22866064 is EUR, while both SideDeck ledgers are USD 1,000. FX rate, costs, instrument eligibility and quote freshness must be verified before any order. There is no POST or order API in SideDeck; live trading remains disabled.

Official endpoints: https://developer.saxobank.com/openapi/referencedocs/ref/v1/instruments/get__ref__details_uic_assettype and https://developer.saxobank.com/openapi/referencedocs/trade/v1/infoprices/get__trade .
