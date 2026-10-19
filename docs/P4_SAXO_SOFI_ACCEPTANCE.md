# Saxo SIM: SOFI pre-execution acceptance report (NO-GO)

Known broker evidence: SOFI:xnas, Stock UIC 23241352, verified on account 22866064; one-share Saxo SIM precheck `Ok` with an estimated **EUR 41.03** cash requirement. INTC also prechecked `Ok` at EUR 114.87; PLTR broker precheck remains unavailable. Both SideDeck agent ledgers have USD 1,000, independent from Saxo SIM account EUR 1 million virtual cash.

```powershell
git pull --ff-only
.\\.venv\\Scripts\\python.exe -m sidedeck.application.saxo_sofi_acceptance --expected-account-id "22866064"
```

The command re-verifies SOFI's account-scoped trading identity, account currency, full current position and open-order collections, and a fresh single-share Saxo precheck. It prints specific NO-GO gaps, including price validation, account FX/cost conversion, real broker fill lifecycle, and SIM-only submit implementation. A successful broker precheck does **not** constitute order approval.

The fixed EUR 200 ceiling is intentionally conservative. EUR 41.03 cannot by itself establish compliance with the agent's **USD 200** per-position cap without FX and costs. The precheck response is a cash estimate, not an execution or verifiable bid/ask quote.

There is no broker submit/cancel implementation and no real-money trading. The CLI intentionally returns a diagnostic acceptance report rather than placing an order.
