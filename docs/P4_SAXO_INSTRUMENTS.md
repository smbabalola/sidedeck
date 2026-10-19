# Saxo SIM stock discovery — no execution

Saxo's `GET /ref/v1/instruments` searches instruments by `AccountKey`, `AssetTypes`, `Keywords` and bounded `$top`. See the [official instrument reference](https://developer.saxobank.com/openapi/referencedocs/ref/v1/instruments/get__ref).

This batch adds **only** a read-only, Saxo-SIM-only account-scoped stock search for an exact uppercase 1–6-letter ticker (default AAPL). Results are **candidates**; ticker matching alone does not confirm US exchange, USD denomination, eligibility or current trading price. CFDs are excluded. A result must be checked against detailed instrument data, account tradability, and live quote/session before any simulated order. The lookup cannot place, precheck or cancel an order.

## Local test

With `SAXO_SIM_ACCESS_TOKEN` already loaded in your PowerShell session:

```powershell
git pull --ff-only
.\\.venv\\Scripts\\python.exe -m sidedeck.application.saxo_instruments --expected-account-id "22866064" --ticker AAPL
```

Share only instrument UIC, symbol, description and status. Do not share access tokens or AccountKey/ClientKey. If SIM returns permission errors or unavailable data, report the limitation; do not substitute instrument identifiers from another account.

Next milestones: full instrument detail and Saxo prices; EUR/USD FX and costs; provider order precheck (Saxo uses `POST /trade/v2/orders/precheck`, separate from actual `POST /trade/v2/orders`); durable order lifecycle and explicit one-time operator approval. This branch still has no order POST capability and real-money execution remains excluded.
