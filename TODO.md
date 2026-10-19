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
