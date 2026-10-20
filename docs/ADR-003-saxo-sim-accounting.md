# ADR-003 — Separate Saxo SIM execution accounting with per-strategy attribution

**Status:** Proposed (design only, not implemented). `P4_DECISION=NO-GO`.
**Date:** 2026-10-20. **Branch:** `feat/p4-claude-review` (PR #4, draft).

This ADR documents schema, reconciliation and migration implications *before*
any accounting code changes, as requested by the owner.

## 1. Context — what happens today

- `SaxoExecutionPipeline.apply_buy_fill` appends `BUY_FILL` events into the
  in-memory research `Ledger`. Its `portfolio_id` is one of
  `AUTHORIZED_PORTFOLIOS = ("tradingagents", "ai-trading")`, the same USD 1,000
  research portfolios used by the P1–P3 experiment and persisted in
  `journal_events`.
- `application/reconciliation.py` compares **Alpaca paper** broker positions
  with the *combined* `tradingagents` + `ai-trading` portfolio states.
- The Saxo SIM account is EUR-denominated with its own (large) SIM balance.
  The research portfolios are USD 1,000 virtual books.

Consequences if a SIM order were filled today:

1. The research experiment's cash and positions would change because of a
   Saxo SIM trade. Strategy performance would mix simulated research fills
   with broker-SIM fills.
2. Alpaca paper reconciliation would see a SOFI position in the research books
   that Alpaca does not hold, and report a mismatch. Worse, a matching Alpaca
   trade could appear to "explain" it.
3. EUR settlement, FX and broker fees would be forced into USD-only books with
   no record of the account-currency amounts.

None of this has happened: no SIM order has ever been submitted
(`SIM_SUBMISSION_RELEASED = False`), so no SIM fill rows exist.

## 2. Decision (proposed)

Introduce a **separate SIM venue ledger** with one *book* per strategy:

| Book ID | Purpose |
|---|---|
| `saxo-sim:tradingagents` | SIM executions attributed to the TradingAgents strategy |
| `saxo-sim:ai-trading` | SIM executions attributed to the AI-Trading strategy |
| `saxo-sim:unattributed` | Control book: broker activity without a SideDeck order key (pre-existing positions, manual trades, interest, unexplained fees). Never auto-assigned to a strategy. |

Rules:

- **No shared code path with the research ledger.** A new `SimLedger`
  (`domain/sim_accounting.py`) accepts only `saxo-sim:*` book IDs. The research
  `Ledger` keeps accepting only `tradingagents` / `ai-trading`, and additionally
  rejects any event whose idempotency key starts with `saxo:`. The pipeline's
  type changes from `Ledger` to `SimLedger`, so the separation is enforced by
  types and tests.
- **Attribution is fixed at approval time.** The strategy comes from the
  proposal, is written into the request and the operator-signed approval
  material as `book_id`, and is stored durably with the authorization. Fills
  are attributed through `order_key → authorization.book_id`, never from
  broker fields or caller arguments.
- **Currencies.** Book cash is in the **account currency (EUR)**. Positions and
  prices are in the **instrument currency (USD)**. Each fill stores the USD
  price and quantity, the EUR settlement amount (broker figure when available,
  otherwise USD × the request's validated FX rate, labelled as derived), the
  FX rate and its source, and the fee with its explicit currency. P&L is
  reported in EUR, with USD shown alongside.
- **Capital.** Each strategy book is opened with an explicit
  `SIM_ALLOCATION` event in EUR. The sum of allocations must not exceed the
  authenticated SIM cash balance observed at opening. The allocation size is an
  owner decision (see §7). The SIM account's remaining balance is not strategy
  capital.
- **Alpaca paper accounts and research ledgers are untouched.** Neither the
  existing tables nor `reconciliation.py` inputs change.

## 3. Schema (migration `0009_saxo_sim_books`, proposed)

New tables only; no change to `journal_events` or `proposal_audit`.

```text
saxo_sim_books
  book_id            VARCHAR(64)  PK        -- 'saxo-sim:tradingagents' | 'saxo-sim:ai-trading' | 'saxo-sim:unattributed'
  strategy_id        VARCHAR(64)  NULL      -- NULL only for the unattributed control book
  account_id         VARCHAR(100) NOT NULL  -- verified SIM AccountId (stored, never logged)
  account_currency   CHAR(3)      NOT NULL  -- 'EUR'
  opened_at          TIMESTAMPTZ  NOT NULL
  status             VARCHAR(16)  NOT NULL  CHECK IN ('OPEN','FROZEN','CLOSED')
  UNIQUE (account_id, strategy_id)

saxo_sim_journal
  journal_sequence   INTEGER      PK autoincrement
  event_id           CHAR(36)     UNIQUE NOT NULL
  book_id            VARCHAR(64)  NOT NULL REFERENCES saxo_sim_books(book_id)
  idempotency_key    VARCHAR(200) NOT NULL   -- 'saxo:<ExecutionId>' for fills
  event_type         VARCHAR(32)  NOT NULL   CHECK IN ('SIM_ALLOCATION','SIM_BUY_FILL','SIM_SELL_FILL',
                                                       'SIM_FEE','SIM_BASELINE','SIM_ADJUSTMENT')
  order_key          VARCHAR(50)  NULL
  broker_execution_id VARCHAR(200) NULL UNIQUE
  occurred_at        TIMESTAMPTZ  NOT NULL
  payload            TEXT         NOT NULL   -- canonical JSON: Decimal strings, explicit currencies, FX source
  payload_sha256     CHAR(64)     NOT NULL
  UNIQUE (book_id, idempotency_key)

saxo_execution_authorization   (existing, add)
  book_id            VARCHAR(64)  NULL      -- required for new rows; included in approval material

saxo_execution_recovery        (existing, add)
  book_id            VARCHAR(64)  NULL      -- recovery replays into SimLedger by book
```

`SIM_ADJUSTMENT` (manual correction) requires an operator-signed approval,
like orders, and is never generated automatically.

## 4. Reconciliation

Three separate, read-only checks; none of them submits or cancels anything.

1. **Per order** (exists today, kept): cumulative `FillAmount` equals the
   authorized quantity, `FinalFill` closes it, and the broker order ID matches
   the acknowledged lifecycle. Additionally, the book must equal the
   authorization's `book_id`.
2. **Per SIM account** (new): for each Uic,
   `Σ strategy book positions + unattributed position = broker position`
   from `/port/v1/positions`. Cash is reconciled as a *delta since baseline*:
   the EUR movement of attributed fills plus fees must match the broker cash
   change, with any remainder posted to `saxo-sim:unattributed` for review,
   never to a strategy. Mismatches freeze the affected books (`FROZEN`), and a
   frozen book blocks new SIM orders for that strategy.
3. **Baseline at opening** (new): when a book is opened, the authenticated
   positions and open orders are recorded once as `SIM_BASELINE` in the control
   book. Pre-existing exposure is never attributed to a strategy.

Alpaca paper reconciliation (`reconciliation.py`) keeps its inputs, the two
research portfolios. A regression test will assert that SIM books cannot be
passed to it and that a SIM fill leaves both research portfolio states
unchanged.

## 5. Migration implications

- **Forward (`0009`)**: create `saxo_sim_books` and `saxo_sim_journal`, and add
  nullable `book_id` to the two Saxo tables (SQLite via `batch_alter_table`,
  PostgreSQL directly). Seed the three book rows only when a verified account
  ID is supplied by the opening command, never inside the migration.
- **Existing data safety check**: the migration *refuses to run* if
  `saxo_execution_recovery` has any `POSTED`/`PENDING`/`RECOVERING` rows, or if
  `journal_events` contains an idempotency key starting with `saxo:`. Such rows
  would mean a SIM fill was already booked into a research portfolio. That needs
  owner review and a signed correction, not a silent move. With releases
  disabled, the expected count is zero.
- **Downgrade**: drops the new tables and columns only when `saxo_sim_journal`
  is empty. Otherwise it refuses, to avoid destroying accounting history.
- **Runtime DDL**: the `CREATE TABLE IF NOT EXISTS` statements in
  `saxo_execution_pipeline.py` / `saxo_sim_submission.py` will be updated in
  step with the migration, as was done for `0008`.
- **Verification**: disposable SQLite `0001→0009→base→0009`, the PostgreSQL CI
  round trip, a refusal test with a seeded `saxo:` research row, and an
  idempotent crash-recovery test replaying into `SimLedger`.

## 6. Implementation plan (after owner sign-off)

1. `domain/sim_accounting.py`: `SimLedger`, `SimBookState` (EUR cash, USD
   positions, fees by currency) with deterministic replay.
2. Research `Ledger`: reject `saxo:` idempotency keys (one-line guard plus a test).
3. Request, approval material and authorization gain `book_id`; the pipeline
   switches to `SimLedger` and reads `book_id` from the authorization.
4. Migration `0009` with safety refusals; runtime DDL parity.
5. Account-level reconciliation and the baseline command (read-only, injected
   transport; the live run needs separate Stage 2 permission).
6. Acceptance evaluator gate `SIM_ACCOUNTING_SEPARATED` (currently `MISSING`)
   turns `PASS` only when the pipeline is bound to `SimLedger`.

## 7. Owner decisions needed

1. EUR allocation per strategy book (for example EUR 200 each, matching the
   current USD 200 position cap) and whether allocations may be topped up.
2. Whether a reconciliation mismatch freezes only the affected strategy book or
   all SIM trading.
3. One SIM account with logical per-strategy books (proposed), or separate
   Saxo SIM accounts per strategy (stronger isolation; needs a separately
   verified second account).
4. Whether SIM results should ever be reported side by side with research
   results (proposed: separate reports, never merged totals).
