# P4 Saxo SIM broker order lifecycle

A local durable SQLite broker-order lifecycle is now implemented with atomic state transitions and unique broker order identifiers. The `UNKNOWN` state represents an indeterminate network submission outcome: it cannot transition to acknowledged/filled without broker evidence. Fills must have a broker order ID. Completed/terminated orders cannot be submitted again under the same lifecycle key.

This is preparation for future broker execution, **not broker order submission**. There is still no `POST /trade/v2/orders` integration, no fill-history retrieval, no verified external USD stock feed, and no validated EUR/USD conversion. The journal is not yet connected to `saxo_intents` or Saxo execution events; it must not be described as completed end-to-end reconciliation or idempotent HTTP submission.

Synthetic tests: `python -m pytest tests/test_saxo_order_lifecycle.py -q`.

The established candidate is SOFI:xnas Stock UIC 23241352, whose Saxo SIM one-share precheck was `Ok` at EUR 41.03. EUR amount is a broker estimate, not an execution price. Two SideDeck agent portfolios are each limited to USD 1,000 with conservative USD 200 position ceiling. Real-money trading remains disabled.
