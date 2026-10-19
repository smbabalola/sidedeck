# Saxo SIM — account cash preview

The user has verified Saxo SIM account 22866064 is active and EUR-denominated, with no positions or open orders. The account-specific snapshot is operational. Saxo documents its account-scoped balance endpoint as `GET /port/v1/balances?AccountKey=...&ClientKey=...` and its `CashAvailableForTrading` field. This batch adds a **read-only cash and currency preview**; it is NOT a Saxo order precheck and does not validate instruments.

After setting `SAXO_SIM_ACCESS_TOKEN` in the current terminal, run:

```powershell
git pull --ff-only
.\\.venv\\Scripts\\python.exe -m sidedeck.application.saxo_order_preview --expected-account-id "22866064"
```

Expected for a valid EUR account: the observed broker-currency cash amount and `Execution status: BLOCKED (eur_usd_fx_not_approved)`. USD virtual SideDeck portfolio accounting has not been reconciled to Saxo's EUR balance. Neither broker orders nor live trading are supported. Do not interpret the availability of cash as trading authorization.

## Remaining external order work

Retrieve and validate market-specific instrument UIC and Stock asset type, account tradability, market quotes/session, EUR/USD and costs, order status/partial fills, price drift and spending limits. Build a durable submission ledger (idempotent local intents, reconciliation on ambiguous network outcomes) and implement Saxo SIM-only order precheck before any operator-approved simulated POST. Renewable authentication must precede unattended agents. No paid/live trading is permitted.
