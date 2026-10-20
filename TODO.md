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
- [x] Replay recovery chronologically with deterministic tie-breaking and
  reject persisted event hash corruption.
- [x] Require acknowledged lifecycle broker-order identity before journaling
  any fill; bind account and authorized quantity durably.
- [x] Run offline regression, migration and acceptance checks without Saxo
  credentials or broker requests.
- [ ] Obtain separately approved authenticated SIM quote, FX, precheck and
  execution-history evidence; no order was submitted in this batch.

## P4 independent review — Claude Code, 2026-10-19 (`feat/p4-claude-review`)

- [x] Replaced self-generated approval with verify-only operator approval
  (OpenSSH signature, operator-held key; requester cannot approve).
- [x] Sealed SIM precheck evidence; fixture/hand-built prechecks cannot
  authorize. Broker EUR rate/cost/cash cross-checked against quote and FX.
- [x] Quote/FX freshness measured from submission time; request expires
  5 minutes after preparation; approval lifetime at most 10 minutes.
- [x] Submitter drives the broker lifecycle; malformed acknowledgement is
  UNKNOWN; read-only reconciliation of UNKNOWN without any retry.
- [x] Fills bound to the durable CONSUMED authorization (portfolio, account,
  broker order, quantity); naive timestamps and wrong Uic/side rejected.
- [x] Migration `0008_operator_approval_binding`; acceptance report now
  evaluates gates; added `SIM_SUBMISSION_RELEASED=False` release gate.
- [ ] **BLOCKED (permission):** Stage 2 authenticated read-only SIM account,
  instrument, quote, FX and precheck evidence; a trusted market-data verifier.
- [ ] **BLOCKED (owner):** operator key + `allowed_signers`; owner decision
  whether SIM fills post to the strategy ledger or a separate SIM ledger.
- [ ] **BLOCKED (approval):** release gate change and one signed SIM order.
- Code commit: `a608a79`. Local evidence: `228 passed, 1 skipped, 3 warnings`
  (skip = PostgreSQL, CI-only); Ruff passed; mypy passed (52 source files);
  disposable SQLite Alembic `0001`→`0008`→`base`→`0008` passed; offline
  acceptance `P4_OFFLINE_CHECK=PASS`, `P4_DECISION=NO-GO`, 0 broker requests.
- CI: **NOT RUN.** The workflow triggers only on push to `main`/`feat/p1-foundation`
  or on pull requests, and the agent token cannot create PRs. Owner action:
  open a draft PR `feat/p4-claude-review` → `feat/p3-readonly-batch` to run
  CI (including the PostgreSQL `0008` round trip).

## PR #4 follow-up — 2026-10-20

- [x] CI #452 (run 39301891078) passed on `7cd2595`.
- [x] Acceptance evaluator re-verifies evidence: sealed scope and request,
  sealed precheck bound to request, registered market-verifier type (registry
  ships empty), operator signature re-checked from `allowed_signers`.
- [x] Separate SIM accounting designed in `docs/ADR-003-saxo-sim-accounting.md`
  (schema, reconciliation, migration `0009` plan). **Not implemented**;
  evaluator reports `SIM_ACCOUNTING_SEPARATED=MISSING`.
- [ ] **BLOCKED (owner):** ADR-003 decisions (EUR allocation per strategy,
  freeze scope, one SIM account vs per-strategy accounts, reporting).
- Local: `234 passed, 1 skipped, 3 warnings`; Ruff and mypy (52 files)
  passed; disposable SQLite Alembic head→base→head passed; offline
  acceptance `P4_DECISION=NO-GO`, 0 broker requests.

## SIM accounting implementation — 2026-10-20 (ADR-003 accepted)

- [x] Owner decisions applied: EUR 1,000 per strategy book, no top-ups, USD 200
  per-position cap, one SIM account with three logical books, account-wide vs
  proven book-specific freezing, separate reporting, kill switch unchanged.
- [x] `SimLedger` + durable SIM journal (migration `0009`) with legacy/research
  refusal checks and downgrade protection; research `Ledger` and journal reject
  `saxo:` events; Alpaca modules and `reconciliation.py` unchanged.
- [x] Fills bound to the signed authorization's book, quantity and FX; atomic
  journal writes; deterministic, hash-verified recovery; concurrency tested.
- [x] Read-only reconciliation with fail-closed freezing and sealed-report
  release; baseline recording; per-strategy SIM performance report.
- [x] Acceptance: `SIM_ACCOUNTING_SEPARATED=PASS`; `P4_DECISION=NO-GO`.
- [x] Evidence: code `3494e8b`. Local `263 passed, 1 skipped` (skip = PostgreSQL);
  CI #457 (run 39378358142) **passed, 264 tests, 0 skipped**, including the
  disposable PostgreSQL upgrade through `0009` and downgrade. CI #456 failed on
  a real lifecycle race in concurrent duplicate delivery; fixed in `3494e8b`
  with a deterministic regression test. Ruff and mypy (56 files) clean;
  SQLite Alembic head→base→head passed.
- [ ] **BLOCKED (permission):** Stage 2 authenticated read-only evidence and a
  registered market-data verifier; real positions/order-activity reconciliation.
- [ ] Not implemented by design: sells, fee-only events, signed SIM adjustments,
  audited allocation top-ups.

## Reconciliation hardening and Stage 2 preparation — 2026-10-20

- [x] Reconciliation trust boundary closed (ADR-003 §10, migration `0010`):
  - only sealed, GET-only SIM account evidence can open books, reconcile, or
    lead to a release;
  - reconciliation reads the stored journal itself;
  - evidence is tied to the account, login, source, time and journal digest,
    and each evidence ID can be used once.
- [x] Missing cash evidence → `INCOMPLETE` (account freeze). Broker fills for
  approved orders that never reached the journal are flagged. `ACCOUNT` freezes
  are never downgraded.
- [x] Comparison, recording and freezing run in one IMMEDIATE transaction.
  Crash tests at three points leave no partial decision.
- [x] A release requires:
  - the latest MATCHED run;
  - evidence read after the freeze and no more than 5 minutes old;
  - an unchanged journal;
  - an OpenSSH operator signature.

  Releases are logged in `saxo_sim_freeze_releases`.
- [x] Stage 2 read-only infrastructure, offline only:
  - a sealed account-evidence collector;
  - a SIM reader and verifier for the SOFI quote and EUR/USD (Uic 21), bound to
    one account;
  - `verified_scope` now accepts only the exact SIM client.

  The verifier is **not** registered.
- [x] Acceptance: `SIM_RECONCILIATION_EVIDENCE_BOUND=PASS`,
  `STAGE2_SIM_ACCOUNT_EVIDENCE=MISSING`, `P4_DECISION=NO-GO`, 0 broker requests.
- [x] Local: `312 passed, 1 skipped` (the skip is PostgreSQL, CI only). Ruff
  and mypy (57 files) clean. A throwaway SQLite Alembic head→base→head round
  trip at `0010` passed.
- [x] CI evidence: code `378babc`, CI #461
  ([run 39389946214](https://github.com/smbabalola/sidedeck/actions/runs/39389946214))
  **passed: 313 tests, 0 skipped**, including the disposable PostgreSQL upgrade
  through `0010` and the rollback.
- [ ] **BLOCKED (owner permission):** one live, read-only Stage 2 run (account
  evidence, SOFI quote, EUR/USD, precheck). After review, register
  `SaxoSimMarketEvidence` in `TRUSTED_MARKET_VERIFIER_TYPES`.
- [ ] **BLOCKED (owner):** operator key and `allowed_signers`, and a
  separately approved change to `SIM_SUBMISSION_RELEASED` (still `False`).

## Verification record

- Branch: `feat/p3-readonly-batch`
- Baseline: `2b4823b50d1af96d581c39993a48b1b8434f7056`
- Current remediation commit: `a3dfacf03d32f2d4b937ff8ff0db56f7958d9d51`.
- Local evidence: `199 passed, 1 skipped`; Ruff passed; mypy passed with no
  issues in 51 source files; disposable Alembic upgrade and downgrade passed;
  offline acceptance passed with `P4_DECISION=NO-GO`.
- Latest correction evidence: `202 passed, 1 skipped`; Ruff passed; mypy
  passed; Alembic `0001` through `0006` upgrade/downgrade passed; offline
  acceptance passed with `P4_DECISION=NO-GO`.
- Final correction evidence: `203 passed, 1 skipped, 3 warnings`; Ruff and
  mypy passed; Alembic
  `0001` through `0007` upgrade/downgrade passed; offline acceptance passed
  with `P4_DECISION=NO-GO`.
- CI evidence: [run 39250451185](https://github.com/smbabalola/sidedeck/actions/runs/39250451185)
  completed successfully for the preceding implementation SHA. No newer
  Actions run for the final documentation tip was observed at handoff.
- Decision: `P4_DECISION=NO-GO` until authenticated evidence and a separately
  approved one-time operator authorization exist.
