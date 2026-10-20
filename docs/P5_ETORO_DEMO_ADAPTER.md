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
5. **Cash fails closed:** cash stays UNAVAILABLE until you confirm which `accountCurrencyId` means USD (passed as `--usd-currency-id`). It is also UNAVAILABLE when `credit` is missing or a pending order lacks its amount or `mirrorID`.
6. **Staleness:** a snapshot older than 5 minutes, or dated more than 5 seconds in the future, is refused.

## Tests (`tests/test_etoro_demo.py`, 41, synthetic only)

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

## Verification (local)

- `377 passed, 1 skipped` (the skip is PostgreSQL, CI only).
- A throwaway SQLite Alembic head→base→head round trip passed.
- Ruff and mypy are clean for every new file. The branch already had 2 Ruff and 20 mypy errors in 9 unrelated P5 files that this work doesn't touch.

## Remaining gaps and gates

- [ ] **Owner:** confirm the USD `accountCurrencyId` before cash is reported.
- [ ] **Owner-run:** capture the baseline locally with `--capture-baseline`. The database is local and git-ignored, because it holds position and order IDs.
- [ ] Value-level validation against a real snapshot, kept locally and never in GitHub. Field names come from a field-only report, so the real types (for example numbers vs strings, timestamp format) still need confirming.
- [ ] Mirror/copy positions are rejected, not modelled.
- [ ] An owner decision on virtual capital per strategy book (none allocated).
- [ ] A dashboard view built on `DemoReconciliation`, showing each book separately.
- [ ] Demo order lifecycle, idempotency and operator release: a separate, explicitly approved stage. `record_order_attribution` exists only for that future order path.
- [ ] Real-money execution stays permanently disabled.

**Isolation:** Saxo P4 is still `NO-GO` with `SIM_SUBMISSION_RELEASED=False`. Alpaca is unchanged, and the outer `feat/p2-agent-adapters` checkout is untouched.
