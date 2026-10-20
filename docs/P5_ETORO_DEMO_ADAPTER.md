# P5 — eToro Demo read-only portfolio adapter (2026-10-20)

**Status:** built and tested offline, against synthetic fixtures only. **No** additional authenticated eToro request was made while building it. Demo and real-money order execution do not exist in this code.

Builds on [`ETORO_DEMO_READ_2026-10-20.md`](ETORO_DEMO_READ_2026-10-20.md): one owner-run Demo `/pnl` read returned HTTP 200 with 4 positions and empty order and mirror lists.

## Modules

| Module | Purpose |
| --- | --- |
| `domain/etoro_demo.py` | Strictly parses `clientPortfolio` into Decimal values, then works out available cash and unrealised P&L (see below). |
| `domain/etoro_demo_books.py` | The three logical books, the baseline, matching by `positionID` and order ID, and read-only reconciliation. |
| `infrastructure/etoro_demo_client.py` | A GET-only client for exactly `https://public-api.etoro.com/api/v1/trading/info/demo/pnl` (details below). |
| `infrastructure/etoro_demo_store.py` | Local SQLite store for the one-time baseline and the strategy attributions. |
| `application/etoro_demo_portfolio.py` | An owner-run CLI that does nothing without `--confirm-owner-demo-read`. It reads keys from the process environment, never `.env`, and prints only counts and statuses. |
| `migrations/versions/0005_etoro_demo_books.py` | Creates the baseline, capture and attribution tables. Rollback refuses while any of that history exists. |

**Parser checks.** These make the parse fail:
- a missing collection;
- a duplicate `positionID`;
- units or amount that are zero or below, NaN or not numeric;
- a timestamp without a timezone;
- a malformed ID.

**Cash and P&L.**
- **Available cash:** follows eToro's documented formula, `credit - Σ ordersForOpen.amount (mirrorID 0) - Σ orders.amount`. `bonusCredit` and P&L are never counted as cash.
- **Unrealised P&L:** the sum of the P&L eToro reports for each position. It shows as UNAVAILABLE if any position lacks one or if copy/mirror positions exist.

**Client restrictions.**
- Any other path, including the real-money account, is refused before any network activity.
- GET only: no redirects, no retries, a 15-second timeout and a 5 MB response cap.
- An honest `SideDeck/0.1` User-Agent.
- Errors report only a classification (`AUTH_REJECTED`, `ACCESS_DENIED`, `CLOUDFLARE_1010`, `RATE_LIMITED`, …) with the CF-Ray ID and request ID. Keys never appear in errors or `repr`.

## Rules enforced

1. **Books:** `etoro-demo:tradingagents`, `etoro-demo:ai-trading` and `etoro-demo:unattributed`, kept separate from Saxo SIM, Alpaca paper and the research ledgers. Totals are never combined.
2. **Baseline:**
   - Captured once, and immutable. An empty account still counts as captured. A different baseline is refused, and capture is refused after any attribution exists.
   - All four existing positions sit in the unattributed book.
   - `require_sidedeck_owned` refuses every baseline position, so SideDeck can never close them.
3. **Identity:**
   - A strategy owns a position only through a recorded SideDeck order ID that matches that position's `orderID`.
   - Positions in the same instrument are never attributed by ticker.
   - Any unexplained position or pending order is a discrepancy shown in the unattributed book; nothing is concealed.
4. **No capital:** every book reports `NOT_ALLOCATED: requires an audited owner decision and verified Demo funds`. Saxo's EUR 1,000 rule is not imported.
5. **USD only when the response says so:** `accountCurrencyId = 1` is adopted as USD (owner decision 2026-10-20, based on two independently published eToro API references). Cash is computed only when the live response itself reports `1`. Any other value, or a missing one, makes cash UNAVAILABLE: no conversion and no assumption. Cash is also UNAVAILABLE when `credit` is missing or a pending order lacks its amount or `mirrorID`.
6. **Hardened baseline capture.** `capture_baseline` takes the raw response and checks everything before writing:
   - the live field types, strictly, using `field_type_issues`. Numbers must be JSON numbers and IDs must be integers. The check reports only field paths and types, never values;
   - a full parse of the response;
   - the position count must equal the owner-confirmed `--expected-positions`, currently 4.

   It then writes in a single transaction, so a failure leaves nothing behind. An existing baseline is never overwritten, and an identical repeat changes nothing.
7. **Staleness:** a snapshot older than 5 minutes, or dated more than 5 seconds in the future, is refused.

## Tests (`tests/test_etoro_demo.py`, 52, synthetic only)

- Decimal parsing.
- The cash formula: pending-order deductions, the mirror exclusion, zero cash, unconfirmed currency, missing inputs.
- P&L unavailable with mirrors or missing values.
- 11 malformed-data cases: duplicate IDs, negative, zero, NaN or boolean quantities, naive timestamps, etc.
- Stale and future-dated snapshots.
- The baseline staying read-only and unattributed.
- Attribution by order ID rather than instrument.
- Discrepancies: a baseline position closed or changed, unknown pending orders, mirror positions.
- Per-book reports with no combined totals and no values in the summary.
- Store idempotency and protection.
- Concurrent baseline capture: exactly one write wins.
- The client's path allowlist, GET only, no retries, sanitised 401/403/1010/429/500 results, and no write methods.
- The CLI sending nothing without its flag or keys, and printing only counts.
- The `0005` round trip and refused rollback.
- Hardened capture:
  - field-type issues report paths, never values;
  - a count mismatch, string numbers, a string currency ID, a duplicate ID or an invalid expected count is refused with nothing written;
  - a failure partway through the write leaves no partial baseline;
  - the CLI requires `--expected-positions`, and refuses a mismatch or a type failure without writing.
- USD only when the response reports ID 1.

## Verification

- Local: `388 passed, 1 skipped` (the skip is PostgreSQL, CI only). Ruff and mypy are clean across all 89 source files. A throwaway SQLite Alembic head→base→head round trip passed.
- CI history: run 39401263762 on `9014e95` passed pytest (378, 0 skipped) but failed at Ruff on two unused imports that already existed. Those, and the 20 existing mypy errors in 9 P5 files, were fixed by the owner-side commits `7c59b11`…`27fd95e` ("P5: resolve Ruff and mypy issues without changing research gates"), which landed while this work was in progress. A parallel fix from Claude was dropped in favour of them to avoid conflicting edits. The eToro hardening commit sits on top, and Ruff and mypy are clean.

## Remaining gaps and gates

- [x] USD mapping set to `accountCurrencyId = 1` and checked against each live response.
- [ ] **Owner-run, one authenticated Demo GET:** capture the baseline. Load `ETORO_API_KEY` and `ETORO_USER_KEY` into the PowerShell session yourself first, without printing them. Then, from the `sidedeck\` checkout:

  ```powershell
  .venv\Scripts\python.exe -m sidedeck.application.etoro_demo_portfolio --confirm-owner-demo-read --db data\etoro_demo.sqlite3 --capture-baseline --expected-positions 4
  ```

  `data\` is git-ignored, and the database holds the position and order IDs. Safe output: `request_id`, `status`, `baseline_written`, `baseline_positions`, `discrepancy_count`, `available_cash_usd_status`, and per-book position counts and statuses. Exit codes:
  - `0`: matched;
  - `2`: discrepancy;
  - `3`: `FIELD_TYPE_VALIDATION_FAILED`, which lists field paths and types only. Nothing is written;
  - `4`: `BASELINE_REFUSED`, for example a count mismatch. Nothing is written;
  - `1`: an access error, reported as a classification, the CF-Ray ID and the request ID.
- [ ] Value-level validation against the real snapshot, kept locally. The strict field-type check runs on the first real response; if eToro sends numbers as strings, capture is refused with the paths listed, and the adapter is adjusted only after review.
- [ ] Mirror/copy positions are rejected, not modelled.
- [ ] An owner decision on virtual capital per strategy book (none allocated).
- [ ] A dashboard view built on `DemoReconciliation`, showing each book separately.
- [ ] Demo order lifecycle, idempotency and operator release: a separate, explicitly approved stage. `record_order_attribution` exists only for that future order path.
- [ ] Real-money execution stays permanently disabled.

**Isolation:** Saxo P4 is still `NO-GO` with `SIM_SUBMISSION_RELEASED=False`. Alpaca is unchanged, and the outer `feat/p2-agent-adapters` checkout is untouched.
