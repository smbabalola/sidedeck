# SD-035 authorized Alpaca PAPER account-separation verification

The owner authorized exactly two authenticated `GET /v2/account` attempts on
the approved PAPER host, one with each configured credential pair. The
authorization is single-use and is consumed by the two attempts below.

Sanitized outcome:

| Pair | HTTP / schema | Result retention |
| --- | --- | --- |
| A (`ALPACA_API_KEY` pair) | 200 / VALID | identity never retained |
| B (`ALPACA_API_KEY2` pair) | 401 / NOT_VERIFIED | identity never retained |

Comparison: `UNVERIFIED`; attempts consumed: `2 of 2`. Pair B's failure was
consumed without retry. The result does not establish account separation and
does not authorize any further broker request.

Only HTTP statuses, schema outcomes, comparison (`DISTINCT`, `SAME` or
`UNVERIFIED`) and consumed-attempt count are recorded. Account identifiers,
credentials, headers, balances and raw responses never appear here or in CI.

Regardless of the comparison, `paper_release=NO_GO`,
`broker_execution=DISABLED` and `live_trading=PROHIBITED` remain mandatory.
