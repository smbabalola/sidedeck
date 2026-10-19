# Saxo SIM — read-only SideDeck connector

The user verified two direct Saxo SIM GETs returned HTTP 200:
- `GET https://gateway.saxobank.com/sim/openapi/port/v1/users/me`
- `GET https://gateway.saxobank.com/sim/openapi/port/v1/accounts/me`

This evidence validates temporary token access from the user's machine, **not** a SideDeck connection or broker execution.

The connector only allows these two GET routes, uses only `SAXO_SIM_ACCESS_TOKEN` from the process environment, enforces the exact Saxo SIM host and rejects redirects. It does not implement POST, orders, real trading, portfolio sync or token refresh. Never commit or paste the token.

## Local verification

In the **inner** SideDeck checkout, save the token to your git-ignored `.env`. Load it into the current PowerShell session without printing it:

```powershell
Get-Content .env | ForEach-Object {
    if ($_ -match '^\\s*SAXO_SIM_ACCESS_TOKEN\\s*=(.*)$') {
        $env:SAXO_SIM_ACCESS_TOKEN = $Matches[1].Trim().Trim('"').Trim("'")
    }
}
```

Read the account response using Saxo OpenAPI Explorer to find the **simulation AccountId**; do not use the account's secret `AccountKey` in CLI arguments. Supply the expected AccountId independently:

```powershell
.\\.venv\\Scripts\\python.exe -m sidedeck.application.saxo_preflight --expected-account-id "YOUR_SIM_ACCOUNT_ID"
```

This verifies only a selected **active simulation account identity**, not its currency, cash, holdings, order capacity, entitlements or fills. Never mark external order execution accepted until these are reconciled. Account access can expire when the 24-hour test token expires; unattended automation needs reviewed OAuth and rotation.

## P4 external paper execution acceptance (not yet implemented)

Pin an expected SIM account ID and AccountKey, verify currency and account details, market data, explicit instrument identifiers, broker instrument permissions, quote freshness, available funds, order size, separate experiment allocation, idempotency and complete open-order history. Enforce SIM-only account and transport, block LIVE host and any mismatched identity. Submit one operator-approved *paper-only* order, read broker-reported status and fills, reconcile cash and positions with SideDeck's durable ledger; test duplicates, partial fills, network uncertainty, token expiry and retry safety. Automated agents remain disabled until the full gate passes.
