# SideDeck local demo

SideDeck is a credential-free research and virtual-accounting demo. The local demo runs two separate USD 1,000 virtual portfolios—`tradingagents` and `ai-trading`—against synthetic, timestamped fixtures. It validates proposals through SideDeck-owned risk controls, simulates local fills, posts P1 accounting events, and writes an inspectable dashboard/report.

Every output is labelled `FIXTURE / NOT LIVE MARKET DATA` and `SIMULATED ORDERS / NO ETORO`. The fixture workers are not evidence that either upstream AI framework ran. No credentials, network calls, broker endpoints, or real orders are used.

## Setup

PowerShell:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock
$env:PYTHONPATH = "src"
```

bash:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
export PYTHONPATH=src
```

An editable install is also supported with `python -m pip install -e .`; the source-path commands above avoid changing the repository.

## Run the demo

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe -m sidedeck.demo run
```

The command creates the ignored `results/` directory containing:

- `dashboard.html` — side-by-side cash, NAV, realized P&L and fees.
- `report.json` — reproducible session, risk, run and simulated-fill evidence.
- `trades.csv` — local export of decisions and fills.
- `demo.sqlite3` — restart-safe local P1 journal and audit records.

Open `results\dashboard.html` locally, or use:

```powershell
.venv\Scripts\python.exe -m sidedeck.demo status
.venv\Scripts\python.exe -m sidedeck.demo report
.venv\Scripts\python.exe -m sidedeck.demo reset-fixture
```

`reset-fixture` is the only command that removes demo data, and it is scoped to the ignored `results/` directory. Run it before a fresh deterministic comparison; an ordinary `run` reuses the existing report and journal rather than silently deleting or duplicating economic events.

## Verification

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe -m pytest
.venv\Scripts\ruff.exe check .
.venv\Scripts\python.exe -m mypy src --no-incremental --follow-imports=silent
.venv\Scripts\python.exe -m alembic upgrade head
```

Disposable PostgreSQL coverage runs in GitHub Actions. The local environment does not contact an existing PostgreSQL service.

## Integrations

The TradingAgents adapter preparation is protocol-only and fixture-backed; actual upstream model execution requires separate owner-approved model access and remains opt-in. The `imranpollob/ai-trading` source is not imported, copied, installed, or executed because its licensing is unresolved. eToro and all broker execution remain outside this project.
The credential-free eToro historical-data boundary is read-only and transport-injected. Its later live probe requires all three explicit flags and owner-approved environment credentials; it has no order or Yahoo fallback:

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe -m sidedeck.data_probe --provider etoro --market-data-only --allow-read-network --confirm-owner-read-only
```

SideDeck instrument resolution now uses SignalDeck's legacy `GET /api/v2/market-data/instruments/search?query=AAPL&limit=5`, while completed daily candles remain on eToro API **v1**. This is a deliberately chosen compatibility path, **not** proof that eToro still authorizes v2. The regular probe above can make multiple reads and is **not** an appropriate first authentication check. Five-year daily eToro coverage remains unverified.

For a strictly bounded verification, there is also an **AAPL-only single-request mode** (at most one market-data GET, no rate/candle/account/portfolio/order request and no automatic retries):

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe -m sidedeck.data_probe --provider etoro --market-data-only --allow-read-network --confirm-owner-read-only --single-v2-search AAPL
```

Run this only once with the owner's express permission and private credentials loaded into the process, never in GitHub CI. The probe does **not** load `.env` automatically. Do not echo values to the terminal or persist them in shell history. Do not repeat after an error without a new decision. The existing licensed local CSV import is the prepared fallback; it must be supplied with confirmed usage rights and is never silently combined with or replaced by Yahoo.
Credential-free dry run for all four approved instruments:

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe -m sidedeck.data_probe --provider etoro --dry-run
```

The dry run intentionally reports insufficient depth from fixture data. It does not contact eToro.

## Optional candidate for five-year EOD research (not connected)

Tiingo's free individual EOD data plan is a potential licence-compatible source for **personal internal use**. SideDeck now includes a pure offline Tiingo-style JSON validator in `src/sidedeck/domain/tiingo_eod.py` and tests, **not a network adapter or a real backtest**. It checks raw/adjusted OHLCV, dividends, splits and a five-year exchange-calendar coverage gate. It never treats today's retrospectively adjusted prices as contemporaneously available historical observations. See `docs/HISTORICAL_DATA_ALTERNATIVE.md` and the living TODO. No Tiingo token or live call is required or authorised.

## SideDeck-managed Alpaca PAPER portfolio (initial read-only integration)

Alpaca PAPER is the preferred eventual simulated broker, while **SideDeck remains the only strategy and portfolio management control plane**. Source: [architecture decision](docs/ADR-002-alpaca-paper-control-plane.md). **This initial integration does not transmit paper orders, reconcile fills or verify any provider account.** It is an offline-tested broker inspection interface only. Do not confuse SideDeck's independent USD 1,000 strategy ledgers with one aggregate broker paper account.

Run completely offline without keys:

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe -m sidedeck.paper --dry-run
```

A future bounded read-only paper-account inspection (account summary, approved long positions and open orders only) requires separate owner approval, both paper key and secret privately loaded into the process, and all opt-in flags:

```powershell
.venv\Scripts\python.exe -m sidedeck.paper --paper-only --allow-read-network --confirm-owner-paper-read-only
```

The application **does not auto-load `.env`**. The key variable is `ALPACA_API_KEY` and the matching paper secret must be in `ALPACA_SECRET_KEY`, `ALPACA_API_SECRET_KEY`, or `APCA_API_SECRET_KEY`. Never paste the values into chat or commit them. The client uses **only** `https://paper-api.alpaca.markets` and GET account, positions and open orders; redirects and retries are blocked. One account's buying power may be greater than the two SideDeck allocations and **is not shared with either strategy**. Broker orders will be added only after two distinct paper accounts (if broker separation desired), order-level risk/idempotency, reconciliation and additional explicit authorisation. No eToro or live brokerage calls are made by this module.

## Two paper-key IDs: dual-account safety (not live tested)

Local variable names:

| Strategy | Paper key ID | Corresponding paper secret |
| --- | --- | --- |
| `tradingagents` | `ALPACA_API_KEY` | `ALPACA_SECRET_KEY` (or supported alias) |
| `ai-trading` | `ALPACA_API_KEY2` | `ALPACA_SECRET_KEY2` (or supported alias) |

Creating another API key does **not** necessarily create a second Alpaca PAPER account. SideDeck's dual-account validator uses one `GET /v2/account` per key pair **only after deliberate read-only permission**; it compares broker account IDs in memory and reports whether they differ, never displaying IDs.

Safe offline test, no credentials or network:

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe -m sidedeck.paper_pair --dry-run
```

If separately authorised for a single bounded *two-account* read-only check, the opt-in CLI is:

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe -m sidedeck.paper_pair --paper-only --allow-read-network --confirm-owner-paper-read-only
```

The CLI does not load `.env`; a local launcher must privately provide both key/secret pairs. It contacts the **paper host only**, at most twice, without retries, and stops if authentication fails. It cannot place or cancel paper orders. No distinct-account assertion should be made based on the fixture dry-run.

## SideDeck paper order review screen (offline)

Review the two isolated SideDeck strategy proposals and their assigned Alpaca key slots without credentials or any API traffic:

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe -m sidedeck.paper_desk_review --dry-run
```

Open `results/paper_desk_review.html`. The page is **fixture-only**, uses SideDeck's actual risk gate, and does **not** reflect authenticated Alpaca positions, orders or real performance. Order submission remains disabled.
