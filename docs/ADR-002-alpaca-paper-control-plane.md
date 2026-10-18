# ADR-002 — SideDeck as Alpaca paper portfolio control plane

**Date:** 2026-10-18. **Status:** Selected; paper account connectivity and broker orders not yet independently verified.

## Decision

The owner requested that **SideDeck manage the portfolios** using their existing local `ALPACA_API_KEY` credential. Choose **Alpaca Paper Trading** as the proposed broker for future virtual execution, rather than prioritizing blocked eToro market-data access. This is **not** a request to place paper orders immediately.

### Ownership

- **SideDeck**: two distinct USD 1,000 virtual strategy ledgers (`tradingagents`, `ai-trading`), risk/stop logic, idempotent strategy→proposal→order→fill→exit lineage, source data and strategy attribution; dashboard is the sole control plane.
- **Alpaca paper**: broker-side order/fill lifecycle and paper positions, subject to future validation. Broker account read transport hardcoded to `https://paper-api.alpaca.markets`, with zero real-trading host or write routes. Paper account visibility must not overwrite SideDeck's existing strategy ledgers.
- **Single account limitation:** One credential pair belongs to one paper trading account. It does **not** establish two independent USD 1,000 accounts. Alpaca dashboard supports creating a second paper account and its separately issued API credentials; to compare fully independent broker-side execution, assign exactly one account per engine, with verified distinct account IDs. Do not reset, create, fund or delete accounts automatically. Until verified, broker trading stays disabled.
- **Risk:** no shorting, margin/leverage, crypto, CFDs, options or live trading. Long-only AAPL/MSFT/SPY/QQQ. Paper account default is often USD 100,000 and may allow margin; an account read is **not** a guarantee of SideDeck's USD 1,000 strategy budget. Server-side paper cash and SideDeck allocated cash must not be silently conflated.
- **Market data:** historical stock bar data is served separately by `data.alpaca.markets`, not the paper brokerage host. Basic real-time equity prices are IEX-only, and the latest 15 minutes of historical data are restricted in the Basic plan. Five-year daily EOD coverage, adjustments, publication timing and usage rights must be independently verified before real backtests.

## Implemented now

- Pure `AlpacaPaperReadClient` validates a single paper account, positions and open orders under a strict GET-only allowlist; rejects foreign symbols, short positions, duplicate entries, nonfinite money and unexpected order data.
- Dedicated `sidedeck.paper` CLI: credential-free fixture `--dry-run`, gated read-only inspection with `--paper-only --allow-read-network --confirm-owner-paper-read-only`. The live command requires **both** `ALPACA_API_KEY` and its paired secret key, available locally under one of `ALPACA_SECRET_KEY`, `ALPACA_API_SECRET_KEY` or `APCA_API_SECRET_KEY`. It does not read `.env` automatically. Never reveal actual keys, raw provider error bodies or account IDs.
- No external Alpaca request was made through GitHub or CI; user-local read-only verification is a separate acceptance step. No order creation, cancellation, secret upload or broker-side paper account mutation code exists.

## Follow-on gates

1. Verify local key and **paired secret are present**, without revealing values, and confirm they belong to an Alpaca **paper**, not live account, in the provider dashboard. A filename or variable alone cannot establish key scope.
2. Obtain owner authorisation for a bounded **read-only** paper account + positions + open orders inspection from their local machine. Confirm paper account `ACTIVE`, cash/equity, buying power, multiplier, blocked status and any existing non-SideDeck activity. Do not assume empty account or exactly USD 1,000.
3. Create second Alpaca paper account **by owner action** if two independent broker-side strategy portfolios are required; provision a second ignored local key pair, check unique paper account binding and mapped source`strategy_id`↔`broker_account` without publishing IDs.
4. Implement order-submit/cancel **only under distinct owner approval**, disabled-by-default configuration, verified paper-only host and credentials, risk approval tied cryptographically/idempotently to an exact proposal and portfolio/account, explicit kill-switch; no direct AI-generated order and no order request before full preflight.
5. Reconcile broker open/filled/canceled/partially filled events with internal journals before altering NAV or considering automation. Avoid duplicate broker orders; preserve idempotency, partial fills, dry-run simulation and audit of all outcomes. Require separate acceptance for autonomous paper execution.
6. Add scoped Alpaca data provider after validating market-data entitlement, five-year EOD price depth, provenance and adjustment-vintage limits. Historical **backtesting** is distinct from paper **forward trading**.

## Sources

- Official paper and multiple account behavior: https://docs.alpaca.markets/us/docs/paper-trading
- Paper authentication/host: https://docs.alpaca.markets/us/v1.1/docs/authentication-1
- Trading/positions/orders API: https://docs.alpaca.markets/us/reference/getaccount-1
- Basic historical/real-time feed limits: https://docs.alpaca.markets/us/docs/about-market-data-api

**Supersedes for planned broker integration:** eToro. The previous eToro 403 investigations remain recorded, but no retries are authorised.

## SD-12C — Owner-labelled paper account mapping (not independently verified)

The user reports `ALPACA_API_KEY` was issued for **signaldeckdemo** and `ALPACA_API_KEY2` for **Sidedeckdemo**. The earlier Alpaca screenshot displays **SignalDeckProject** and **Sidedeckdemo account**, so account naming is not yet a verified one-to-one match. The current *provisional* strategy mapping is `tradingagents → ALPACA_API_KEY`, `ai-trading → ALPACA_API_KEY2`. Each pair needs its matching locally stored secret; validate unique provider account IDs **in memory** using the offline-tested, owner-opt-in dual-account read. A first account still used by SignalDeck could contaminate SideDeck's comparative trial. **Paper broker writes remain disabled** until both accounts are distinct, dedicated/isolated, risk reconciled and separately authorised.
