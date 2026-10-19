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
- [x] Reconstruct both POSTED and incomplete execution events into fresh
  ledgers; make repeated and concurrent recovery idempotent.
- [x] Support validated `$skip` pagination through the actual SIM allowlisted
  client while preserving host, account, client and order scope.
- [x] Reconcile cumulative execution quantity to the authorized order and
  reject overfills or incomplete FinalFill evidence.
- [x] Run offline regression, migration and acceptance checks without Saxo
  credentials or broker requests.
- [ ] Obtain separately approved authenticated SIM quote, FX, precheck and
  execution-history evidence; no order was submitted in this batch.

## Verification record

- Branch: `feat/p3-readonly-batch`
- Baseline: `2b4823b50d1af96d581c39993a48b1b8434f7056`
- Current remediation commit: `25a95919daceea9afaadd2561ae8ca3251841fd8`.
- Local evidence: `199 passed, 1 skipped`; Ruff passed; mypy passed with no
  issues in 51 source files; disposable Alembic upgrade and downgrade passed;
  offline acceptance passed with `P4_DECISION=NO-GO`.
- Latest correction evidence: `202 passed, 1 skipped`; Ruff passed; mypy
  passed; Alembic `0001` through `0006` upgrade/downgrade passed; offline
  acceptance passed with `P4_DECISION=NO-GO`.
- CI for this correction: [run 39250451185](https://github.com/smbabalola/sidedeck/actions/runs/39250451185),
  in progress when recorded; completion is not claimed.
- Decision: `P4_DECISION=NO-GO` until authenticated evidence and a separately
  approved one-time operator authorization exist.
