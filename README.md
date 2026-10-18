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

Do not run that command until read-only access is explicitly approved. Five-year daily eToro coverage is currently unverified. The existing licensed local CSV import is the prepared fallback; it must be supplied with confirmed usage rights and is never silently combined with or replaced by Yahoo.
Credential-free dry run for all four approved instruments:

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe -m sidedeck.data_probe --provider etoro --dry-run
```

The dry run intentionally reports insufficient depth from fixture data. It does not contact eToro.

## Optional candidate for five-year EOD research (not connected)

Tiingo's free individual EOD data plan is a potential licence-compatible source for **personal internal use**. SideDeck now includes a pure offline Tiingo-style JSON validator in `src/sidedeck/domain/tiingo_eod.py` and tests, **not a network adapter or a real backtest**. It checks raw/adjusted OHLCV, dividends, splits and a five-year exchange-calendar coverage gate. It never treats today's retrospectively adjusted prices as contemporaneously available historical observations. See `docs/HISTORICAL_DATA_ALTERNATIVE.md` and the living TODO. No Tiingo token or live call is required or authorised.
