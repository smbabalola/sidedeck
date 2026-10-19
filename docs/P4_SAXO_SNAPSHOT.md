# P4 Saxo SIM account exposure inspection

SideDeck's verified simulation account is 22866064 (EUR). The new client-wide inspection uses Saxo's documented **read-only** routes `GET /port/v1/balances/me`, `GET /port/v1/positions/me` and `GET /port/v1/orders/me`. It checks response shape, rejects first-page-only pagination and verifies counts against the balance response. These are **client-wide** reads: not proof of full account-specific reconciliation or a consistent atomic snapshot. Missing or mismatched counts fail closed. No POST, trade endpoint, or automatic agent submission exists.

Run locally from the inner checkout after loading the `SAXO_SIM_ACCESS_TOKEN` into PowerShell (see `docs/SAXO_SIM.md`):

```powershell
git pull --ff-only
.\\.venv\\Scripts\\python.exe -m sidedeck.application.saxo_exposure --expected-account-id "22866064"
```

Output includes only currency, position count and order count, not account identifiers, balances, personal data or tokens. An expired token blocks the check. A nonempty order or position count **does not** permit execution. The EUR-to-USD capital mapping remains unresolved and all broker order submissions remain disabled.

Next: account-scoped snapshot using independently verified AccountKey/ClientKey; safe pagination and consistent reconciliation; instrument UIC and USD instrument quote validation; EUR/USD conversion/cost accounting; idempotent order request and read-after-write semantics; operator authorization for a one-time Saxo SIM test fill. Live trading is excluded.
