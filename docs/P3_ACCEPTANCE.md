# SideDeck P3 read-only acceptance gate

Run the approved offline suite in CI. The account preflight is a separately invoked local-only procedure using SideDeckdemo credentials; GitHub Actions never receives those credentials. Confirm expected account identity independently before making a read request. Never include ID, keys, headers, balances or raw account/position data in screenshots or issues.

Acceptance criteria: (1) local credentials exist; (2) expected account ID matches returned identity; (3) account is active USD; (4) positions and cash reconcile to BOTH internal experiment portfolios; (5) no outstanding orders; (6) dedicated paper account confirmed; (7) read-only access is verified and no order endpoints used. An offline synthetic pass is not a real-account acceptance pass.

Current limitation: account, positions and orders are retrieved in separate requests, not an atomic snapshot. Order/paper execution must have a new point-of-use reconciliation gate; historical activities and pending settlements also need reconciliation before enabling execution.

On a local checkout with installed dependencies, set SideDeck's own environment credentials and invoke:
`python -m sidedeck.application.paper_preflight --expected-account-id YOUR_EXPECTED_PAPER_ACCOUNT_ID`

The preflight validates identity and open orders, but does NOT compare broker balances against the experiment ledgers. Do not claim P3 fully accepted solely from preflight success. No paper orders, scheduler or live-money capability enabled.
