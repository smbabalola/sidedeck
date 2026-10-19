# P4 Saxo external paper execution — first safety gate

Verified operator evidence: Saxo simulation user/account HTTP 200, SideDeck read-only preflight PASS against Saxo SIM account 22866064. Broker account is EUR; SideDeck's two ledgers are USD 1,000 each.

The initial P4 safety gate validates independently supplied account identity, account active flag, balance-currency consistency, finite nonnegative cash and exposure counts using offline injectable data. It always returns **orders_allowed=False**. EUR→USD conversion is **not** implemented, approved or assumed, and the broker account is **not** treated as two segregated $1,000 broker subaccounts.

Next required implementation batch: get account-specific balances via documented `/port/v1/balances?AccountKey=...&ClientKey=...` (only after verifying the expected keys), plus paginated positions and open orders, currency rate and settlement handling, durable idempotent order lifecycle, instrument reference validation and robust token renewal. Broker fill confirmations must be authoritative, with pending/partial fills differentiated. A reviewed SIM-only operator-confirmed tiny test order must precede unattended agent submission. Live endpoint must remain permanently blocked in this phase.

Do not call this acceptance complete just because the preflight passed. The validated SIM-only connector currently permits only read-only identity routes, and the P4 readiness module is offline-only. No external order submission exists.
