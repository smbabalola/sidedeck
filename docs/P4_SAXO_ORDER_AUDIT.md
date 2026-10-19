# Saxo SIM order audit: account-level evidence only

Saxo documents `GET /cs/v1/audit/orderactivities` as order activity history (placement, execution, cancellation). This batch enables only **read-only**, SIM-host-only, account-scoped `EntryType=Last` with a maximum page size of 100 and `IncludeSubAccounts=false`. No live host or order-placement API is accessible.

The diagnostic reads the authenticated user's account identifiers and returns a **count only**. If a next page, invalid account, malformed response or unverified client appears, it fails closed. A __nextPoll marker is normal for Saxo's polling protocol and is not itself evidence of missing pagination; this CLI does not follow the poll link. A bounded snapshot is not complete fill history, and `ExternalReference` presence is not evidence of a fill.

```powershell
git pull --ff-only
.\\.venv\\Scripts\\python.exe -m sidedeck.application.saxo_order_audit --expected-account-id "22866064"
```

The existing durable lifecycle state journal is **not yet automatically connected** to Saxo audit events; full history paging, broker order ID evidence, executions and duplicate-submission recovery still require engineering. SOFI:xnas UIC 23241352 had a one-share precheck Ok at estimated EUR 41.03 but no broker order was placed. The independent price/FX and USD 1,000 agent ledgers remain execution blockers.

Official reference: https://developer.saxobank.com/openapi/referencedocs/cs/v1/audit-orderactivities/get__cs_audit_orderactivities

## Diagnostic correction

Earlier versions printed only a generic BLOCKED message. The corrected CLI reports sanitized HTTP status or validation reason and handles the documented `__nextPoll` field. HTTP 401/403 stays redacted as an authentication/access rejection. The result should not be interpreted as working historical fill reconciliation.
