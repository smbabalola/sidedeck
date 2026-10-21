# SD-035 bounded Alpaca PAPER account-separation proposal

Status: `READY_FOR_SEPARATE_OWNER_AUTHORIZATION`. No request has been made
under this proposal.

## Exact scope

Use the approved PAPER host `https://paper-api.alpaca.markets` and perform
exactly one `GET /v2/account` per credential pair:

| Pair | Key variable | Secret variable | Requests |
| --- | --- | --- | ---: |
| A | `ALPACA_API_KEY` | `ALPACA_API_SECRET` | 1 |
| B | `ALPACA_API_KEY2` | `ALPACA_API_SECRET2` | 1 |

Maximum: 2 authenticated GET requests total, zero retries, zero redirects,
zero query parameters, no fallback host and no positions/orders/account
activity endpoints. The two responses are held in memory only. The verifier
compares the account identity values internally and emits only `DISTINCT`,
`SAME` or `UNVERIFIED`.

## Failure and privacy rules

Any missing credential pair, non-200 response, malformed identity, timeout,
unexpected redirect or schema mismatch yields `UNVERIFIED`; the other request
may proceed only if it remains independently within the two-request budget.
Never retry a failed pair. Never print, persist, upload or commit account IDs,
headers, balances, positions or raw responses. No expected account ID is
invented locally and no identity is inferred from key names.

This comparison would establish only whether the two returned identities match
or differ at that time. `DISTINCT` would not authorize orders, capital
allocation, monitoring or release. Paper execution remains `NO_GO` and broker
transport remains `DISABLED`; a new explicit owner authorization is required
before either request is attempted.
