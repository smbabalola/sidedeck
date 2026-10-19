# P4 Saxo SIM — single order safety gate (NO-GO)

The user has verified account 22866064 in Saxo SIM: EUR 1,000,000 virtual cash, no positions or orders, AAPL:xnas UIC 211, no market-data access (PriceTypeBid/Ask=NoAccess), and Saxo broker order precheck `Ok` with estimated requirement **EUR 364.02** for one AAPL share. No external order has been submitted.

This batch adds a *durable local staging journal* with a unique `order_key` and immutable payload hash, constrained to the two authorized agent portfolios. It never calls the broker, and staged intents never become orders. The first stage preserves duplicate and conflicting-ID handling across process restarts. Database file paths must be local and excluded from version control.

The conservative **single-order cap of USD 200 / EUR 200** makes the current AAPL 1-share candidate fail even if every other gate passed: Saxo estimated EUR 364.02. The USD 200 cap is aligned with the existing 20%-per-position default on a USD 1,000 experimental portfolio; the EUR 200 cap is an intentionally conservative additional ceiling, not a verified FX conversion. Do not reduce the cap or switch to arbitrary instruments solely to force a test execution.

Missing requirements: independent usable quote and its freshness, EUR/USD FX/fees and effective buying-power reconciliation, broker-scoped order status/fill API, network-uncertain submission idempotency and operator approval. Saxo's `Ok` precheck is valuable but not an authorization to trade. Even a perfect readiness result returns `sim_order_submission_not_implemented` until reviewed SIM-only order execution is built. Real-money trading is out of scope.

There is **no automatic agent execution** in the current branch. The next candidate must be checked for its Saxo precheck estimate against the $1,000 agent budget and concentration limits before testing a SIM-only broker order.
