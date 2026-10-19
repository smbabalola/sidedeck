# Saxo SIM shortlisted stock broker precheck

Account 22866064 returned NASDAQ instrument candidates SOFI UIC 23241352, PLTR UIC 46019839, and INTC UIC 247. This command re-reads account-specific instrument detail, requires exact Stock/USD/NASDAQ identity and an account-key match in TradableOn, and requests **one-share** broker precheck independently for each eligible symbol.

It applies a provisional conservative EUR 200 estimate ceiling and prints the broker-reported estimate. Passing this ceiling is NOT proof of USD 200 compliance: independent USD pricing, FX, costs, $1,000 portfolio accounting, current risk approval, broker order/fill reconciliation and an approved SIM-only submit are not complete.

```powershell
git pull --ff-only
.\\.venv\\Scripts\\python.exe -m sidedeck.application.saxo_shortlist_precheck --expected-account-id "22866064"
```

The command can issue up to three `POST /trade/v2/orders/precheck` requests, which are non-executing validations. No `POST /trade/v2/orders` exists. Live trading stays disabled. The Saxo access token stays local. The fixed shortlist is an engineering test universe, not a stock recommendation.
