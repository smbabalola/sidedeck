# Saxo broker-side open exposure check

This batch adds read-only account-scoped enumeration of *current open orders and positions* with pagination fail-closed validation. It does **not** establish fill-level execution history or full reconciliation of historical orders. This is one input toward a future broker execution system, not a trading authorization.

```powershell
git pull --ff-only
.\\.venv\\Scripts\\python.exe -m sidedeck.application.saxo_broker_reconcile --expected-account-id "22866064"
```

The observed AAPL 1-share Saxo precheck returned `Ok` but an estimated EUR 364.02, which exceeds the current conservative EUR 200 single-order cap. It also lacks independent quotes (`NoAccess`) and approved EUR/USD exchange rate and fee reconciliation. The two USD 1,000 agent portfolios remain separate in SideDeck; Saxo SIM EUR 1 million is not spendable SideDeck strategy equity.

Next: instrument candidate selection within risk limits, authenticated account-specific broker order/fill history, immutable client-to-broker idempotency mapping, a reviewed SIM-only submit and broker-confirmed fill path. Do not use this account snapshot as proof of historical fills or actual executions.
