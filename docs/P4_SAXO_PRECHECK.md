# Saxo SIM one-share AAPL order precheck — never submits

Verified user facts: Account 22866064 is EUR, 1,000,000 EUR virtual cash, with no open orders/positions; AAPL:xnas is Saxo Stock UIC 211, USD instrument. Saxo SIM's InfoPrices returns `PriceTypeBid=NoAccess` and `PriceTypeAsk=NoAccess`, so a fresh executable quote is **not** established.

Official Saxo endpoint: `POST /trade/v2/orders/precheck`, which Saxo explicitly distinguishes from the separate order-submission endpoint `POST /trade/v2/orders`. A precheck is not an execution. Saxo supports `FieldGroups: ["Costs"]`, estimated cash requirements, FX conversion rate, error responses and pre-trade disclaimers. See https://developer.saxobank.com/openapi/referencedocs/trade/v2/orders/post__trade__precheck and https://openapi.help.saxo/hc/en-us/articles/4418459141265-How-do-I-retrieve-trade-costs-for-orders

Only the immutable SIM host and **precheck** path are authorized. No live URL, broker order submit endpoint, background scheduler, or execution switch is present. This diagnostic has one operator-invoked precheck POST for one share AAPL:xnas (UIC 211), Market/DayOrder, and exits without placing an order. It doesn't require or imply market-data permissions, and a result of Ok **does not** override missing quotes, FX reconciliation, $1,000 per-agent limits or idempotency.

## Local diagnostic

After loading a valid `SAXO_SIM_ACCESS_TOKEN` into the current PowerShell process:

```powershell
git pull --ff-only
.\\.venv\\Scripts\\python.exe -m sidedeck.application.saxo_precheck_cli --expected-account-id "22866064"
```

The command prints only precheck result, coarse reason, and estimated broker cash/currency; never print tokens, AccountKey/ClientKey, order response payloads or account/user profiles. If the 24-hour token expired, replace it locally. Do not confuse an API access failure with an eligibility verdict.

### Gate

Until an independently verified quote or documented broker alternative, EUR/USD FX and costs, durable order idempotency, fill reconciliation and a specifically approved test order exist, external paper submission remains **NO-GO**. Live trading is strictly prohibited.
