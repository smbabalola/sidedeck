# SD-034 authorized Alpaca PAPER read-only verification

On 2026-10-21, the owner authorized one bounded operation of exactly three
authenticated GET requests against `https://paper-api.alpaca.markets`, using
only the local `ALPACA_API_KEY` / `ALPACA_API_SECRET` pair. The verifier used
an exact host/path allowlist, no redirects, no retries, finite timeouts and a
persistent three-attempt budget. The authorization is now consumed and will
not be reused.

Sanitized result:

| Endpoint | HTTP | Schema | Evidence |
| --- | ---: | --- | --- |
| `/v2/account` | 200 | VALID | Account reported `ACTIVE` and `USD`; identity withheld |
| `/v2/positions` | 200 | VALID | Zero positions returned; no ownership inference |
| `/v2/orders` | 200 | VALID | Zero orders returned; no unresolved orders observed |

No account identifier, balances, position/order identifiers, quantities,
prices, credentials or raw response was persisted or printed. Account
separation remains `UNVERIFIED`: an active USD response from the approved
PAPER host does not independently prove the intended account mapping or
distinctness from any other configured account. No second account comparison
was authorized.

The paper release remains `NO_GO`, broker execution remains `DISABLED`, and
live trading remains prohibited. No order, cancellation, monitoring loop,
eToro request or paid call occurred.
