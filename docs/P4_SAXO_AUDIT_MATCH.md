# P4 Saxo SIM audit-to-journal evidence mapping

Saxo SIM order audit returned an empty account-scoped snapshot successfully on 19 October 2026. This batch implements **pure matching only**, without placing an order. It accepts only a unique audit record matching both the authenticated trading account ID and the local immutable external order reference, with an explicit broker OrderId. Missing, paginated and ambiguous records fail closed. The resulting lifecycle transition is **ACKNOWLEDGED**, never FILLED, because order activity alone is not evidence of executed quantity or price.

The mapper is not automatically connected to the CLI: no broker order or audit record currently exists to match. The Saxo audit schema must be validated against a genuine account-specific order-event response before using this matcher in production. We do not assume an empty audit history establishes fill-reporting capability.

Remaining: verified external SOFI quote and FX/cost provenance, actual Saxo broker transaction/fill records, recovery from uncertain network outcomes, and SIM-only single-order submission. Each SideDeck agent retains its separate USD 1,000 ledger and risk limit. No automatic or live trading.
