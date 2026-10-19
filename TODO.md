# SideDeck P4 living TODO

## P4 execution-integrity remediation — 2026-10-19

- [x] Bind broker precheck evidence to the exact request, account, instrument,
  timestamp, response digest and instrument/account currencies.
- [x] Add versioned recovery and authorization persistence, deterministic
  execution event identities, conflict detection and restart recovery tests.
- [x] Require trusted market-data and human-approval verifier boundaries;
  synthetic labels and manually constructed approvals cannot authorize a
  submission.
- [x] Enforce account/order-scoped execution-history pagination and explicit
  instrument, account, price and fee currencies.
- [x] Run offline regression, migration and acceptance checks without Saxo
  credentials or broker requests.
- [ ] Obtain separately approved authenticated SIM quote, FX, precheck and
  execution-history evidence; no order was submitted in this batch.

## Verification record

- Branch: `feat/p3-readonly-batch`
- Baseline: `2b4823b50d1af96d581c39993a48b1b8434f7056`
- Current remediation commit: pending local verification and push.
- CI: pending push; no CI result is claimed here.
- Decision: `P4_DECISION=NO-GO` until authenticated evidence and a separately
  approved one-time operator authorization exist.
