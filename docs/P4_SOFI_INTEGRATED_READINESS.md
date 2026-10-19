# SOFI Saxo SIM integrated execution readiness

Known acceptance evidence from user-run SIM commands: SOFI:xnas Stock UIC 23241352, broker precheck Ok for one share, EUR 41.03 estimated requirement, positions=0, open orders=0. This is a broker precheck, **not** a submitted order or proof of execution.

Added independent pure accounting checks: timestamp-aware USD quote freshness (maximum two minutes), strictly positive EUR→USD conversion, explicit fees, broker-estimated EUR cash conversion, per-agent USD 200 concentration ceiling, separate agent USD 1,000 portfolio cap, and refusal to infer account FX from the precheck alone. Invalid/non-finite data fail closed; even valid synthetic inputs do not authorize execution without independently verified data provenance and fill lifecycle. No new broker network calls or live-money trading are included.

The result intentionally remains NO-GO until external quote + FX data with provenance, official Saxo order/fill identifiers, idempotent unknown-response handling and explicitly approved SIM-only order submission are all implemented and verified.

This batch does not change Saxo credentials, account permissions or the simulated funds. Test with `python -m pytest tests/test_saxo_sofi_costs.py`. Nothing in this batch submits any broker order.
