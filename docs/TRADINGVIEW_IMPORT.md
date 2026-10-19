# TradingView paper-history import: staged, not executed

SideDeck does not control or authenticate to TradingView's own paper-trading account. This is a **local CSV staging tool** for user-reviewed *executions*. TradingView has a $100,000 paper simulator; SideDeck retains its separate $1,000 experiment portfolios. No CSV import silently moves funds or books fills.

## First use

1. In TradingView Paper Trading, inspect **Trade history** after an order becomes **Filled**. The **Orders** tab's `Working` record (such as the current 1-share AAPL limit order) is not an execution.
2. Export available trade history to CSV. Examine its real column headings and timestamp/fee semantics. TradingView export layouts can vary.
3. Create a **local, reviewed normalized CSV** (never commit confidential exports) with columns:

```csv
execution_id,timestamp,symbol,side,quantity,price,status,fee
example-fill-001,2026-10-19T14:00:00Z,AAPL,BUY,1,343.46,filled,0
```

The example is illustrative, **not evidence that AAPL actually filled**. Source execution ID must remain stable across imports; timestamp is ISO 8601 with explicit UTC offset; price and quantity reflect *executed* trade, not a pending limit instruction. Only positive quantities/prices, nonnegative fees, BUY/SELL, and `filled`/`executed` statuses are accepted. Known non-filled statuses are ignored. Unknown statuses or conflicting duplicate execution IDs block the import. Repeated identical execution IDs within one file are deduplicated.

4. Preview locally:

```powershell
.\.venv\Scripts\python.exe -m sidedeck.application.tradingview_preview .\fills-normalized.csv --portfolio tradingagents
```

or use `--portfolio ai-trading`. The selected portfolio is a **proposed mapping only**. CSV cannot determine which SideDeck experiment originated an external trade. Never map trades to both portfolios by assumption.

## Acceptance limitations

The staging tool does not infer mappings from arbitrary TradingView CSV headers, import open orders, create accounting ledger events, deduplicate across different files, or reconcile complete TradingView cash/positions. It cannot verify that an exported trade originated in the intended TradingView account. Actual source CSV must be inspected and mapped, and live-filled rows reconciled to that source, before implementing a durable idempotent ledger importer. This phase requires **no keys, no webhook subscription, no broker API**, and places **no orders**.
