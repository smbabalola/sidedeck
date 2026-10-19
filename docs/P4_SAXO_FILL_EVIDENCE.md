# Saxo audit fill-evidence validation (P4)

Saxo's official `OrderActivitiesResponse` schema documents `FillAmount`, `ExecutionPrice`, `FilledAmount`, `Status`, `LogId`, `AccountId`, `OrderId`, and `ExternalReference`. Its guidance distinguishes `EntryType=Last` (latest order state, which our current audit reader uses) from **`EntryType=All`** (full execution history).

This batch adds a pure validator for synthetic `EntryType=All` order events: only explicitly verified SOFI:xnas stock UIC 23241352, account 22866064, the expected one-share buy order, exact external reference and broker ID, and positive fill quantity and price are counted. Wrong instrument/account, duplicate LogIds, pagination, unknown status or fills exceeding one share fail closed. A mere `Placed` activity is not a fill.

**Important limits:** no authenticated `EntryType=All&OrderId=...` fetch has yet been enabled or tested. The validator does not write to the ledger or advance the broker lifecycle; an empty account audit snapshot is not evidence of successful fill retrieval. It does not submit orders. A real broker event must be independently validated against Saxo's actual response format before enabling execution.

Developer documentation:
- https://developer.saxobank.com/openapi/learn/audit-orderactivities
- https://developer.saxobank.com/openapi/referencedocs/cs/v1/audit-orderactivities/get__cs_audit_orderactivities/schema-models.orderactivitiesresponse

Test locally: `python -m pytest tests/test_saxo_fill_evidence.py -q`.

Outstanding: authenticated full audit paging, broker order response identity, quote/FX provenance, risk and per-agent ledger linkage, durable HTTP ambiguity recovery, controlled SIM-only placement. No live or automatic execution.
