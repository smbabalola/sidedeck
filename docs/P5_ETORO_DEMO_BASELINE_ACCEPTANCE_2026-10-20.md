# P5 eToro Demo baseline — owner acceptance (20 October 2026)

**Status: BASELINE_CAPTURED=PASS; DEMO_RECONCILIATION=MATCHED.**

The owner executed the existing `sidedeck.application.etoro_demo_portfolio` read-only CLI locally from the inner SideDeck P5 checkout, after loading `ETORO_API_KEY` and `ETORO_USER_KEY` into the PowerShell session. The initial attempt, without environment variables loaded, exited **without any network request**.

## Sanitized evidence from successful invocation

- Command options: `--confirm-owner-demo-read --db data/etoro_demo.sqlite3 --capture-baseline --expected-positions 4`.
- HTTP call: **one authenticated GET** to eToro **Demo** portfolio only.
- `request_id`: `b7bd7eb3-487d-4033-8576-5f7a5eeb63ce`.
- `observed_at`: `2026-10-20T10:08:59.539804+00:00`.
- `baseline_written`: **true**.
- `status`: **MATCHED**.
- `baseline_positions`: **4**.
- `discrepancy_count`: **0**.
- `available_cash_usd_status`: **AVAILABLE** (no numeric balance disclosed; broker response passed currency-ID and cash-field validation).
- `execution_enabled`: **false**.
- `orders_submitted`: **0**.
- `etoro-demo:tradingagents`: **0 positions; NOT_ALLOCATED**.
- `etoro-demo:ai-trading`: **0 positions; NOT_ALLOCATED**.
- `etoro-demo:unattributed`: **4 positions; NOT_ALLOCATED**.
- Unrealized P&L status for all three books: **AVAILABLE**; no monetary values shared.

The protected baseline is stored **only** in the owner's local git-ignored `data/etoro_demo.sqlite3` file. No raw broker response, positions/position IDs, balances, account keys or credentials were uploaded.

## Interpretation and next scope

This is successful **first-capture** reconciliation, not proof of continuous reconciliation against future independent snapshots. A later owner-approved read must show that positions and broker IDs still reconcile; unrecognized manual position changes or new positions must fail closed and display discrepancies.

The baseline must **not** be regenerated or overwritten. Future SideDeck orders may never claim or close these four position IDs. The local SQLite file must be preserved and securely backed up before schema updates.

**Next task:** build a **read-only local dashboard** against the existing `DemoReconciliation` model with synthetic data first. Show venue-labelled independent books, baseline protection, counts, cash/P&L status, reconciliation status, last-snapshot timestamp and staleness. Show money amounts only when available from explicitly owner-approved live snapshots; do not invent or merge values across eToro, Saxo and Alpaca. No background refresh, authenticated broker requests, order submission or budget allocation without separate authorization.

**Operating restrictions:** eToro Demo execution OFF; eToro Real execution OFF; Saxo P4 NO-GO and `SIM_SUBMISSION_RELEASED=False`; Alpaca untouched; outer P2 checkout untouched.

This record is based on the owner's sanitized local output and is not an independent live broker read by ChatGPT.
