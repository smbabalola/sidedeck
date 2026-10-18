# SD-12F — Alpaca PAPER order and FILL receipt reconciliation

**Status:** Offline code and injected fixture tests; not yet authenticated against
the user's paper accounts.

Alpaca's official *Trading API* exposes paper-account GETs:

- \`GET /v2/orders:by_client_order_id?client_order_id=...\`
- \`GET /v2/account/activities/FILL?order_id=...&direction=asc&page_size=100\`
  with bounded pagination.

SideDeck now has a transport-injected \`AlpacaPaperOrderReader\` and a
\`SideDeckPaperReceiptReview\` connecting its durable SQLite journal to these
read-only order/activity schemas. The latter loads an actual durable SideDeck
order, checks the corresponding owner-reported key slot, retrieves the broker
order and matching stable fill activity IDs, then returns the difference between
the broker's cumulative fill and SideDeck's durable ledger quantity.

**Explicit limitation:** The report cannot post a receipt to the ledger
automatically. Alpaca's legacy FILL activity schema does not independently
prove fees, all corrections/busts, or account ownership/vintage. Auto-posting
could fabricate fee=0 or overstate P&L. It is blocked until the fees, account
binding and corrected fill treatment can be authenticated and tested.

The reader rejects symbol, side, duration, limit price, size and strategy
identity mismatches, unauthorized routes, 401/403 responses, malformed/future
activity timestamps, duplicate/conflicting IDs, inconsistent cumulative totals
and incomplete pagination. Each order inspection is at most one order GET plus
three FILL pages, without retries, and **makes zero API requests in CI**.
It has no \`submit\`, \`cancel\` or broker write methods; it cannot contact
live brokerage hosts.

Later: add a deliberately approved local read-only acceptance run with both
paper key pairs and a user-reviewed source-safe reconciliation report.
Paper order placement remains disabled until separate owner authorisation
and verified account/risk/recovery gates.

Sources:
- https://docs.alpaca.markets/us/reference/getorderbyclientorderid
- https://docs.alpaca.markets/us/reference/getaccountactivitiesbyactivitytype-1
- https://docs.alpaca.markets/us/docs/account-activities
