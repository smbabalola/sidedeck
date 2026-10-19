# P4: Saxo account-scoped read-only snapshot

Saxo's official account-specific balance and exposure paths accept `ClientKey` and `AccountKey`. SideDeck now derives both opaque identifiers from the authenticated SIM user and the verified account `22866064`; it never accepts arbitrary URLs or switches to LIVE.

Use with a valid local SIM token in your PowerShell environment:

```powershell
git pull --ff-only
.\\.venv\\Scripts\\python.exe -m sidedeck.application.saxo_account_snapshot --expected-account-id "22866064"
```

Only a successful account-specific inspection is evidence of the linked account's reported positions/orders. Even after success, EUR account-to-USD experiment FX conversion, open-order semantics, pagination, reliable net exposure/cash checks, instrument identification and market-data permissions require additional verification. SideDeck never executes broker orders in this milestone.

Reference: https://developer.saxobank.com/openapi/learn/account-details and https://developer.saxobank.com/openapi/learn/orders-and-positions .
