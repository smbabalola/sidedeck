# SideDeck

SideDeck is a local, deterministic research and virtual-accounting workstation. Research outputs are proposals only. Broker execution, paid model calls, authenticated market-data requests and real-money trading are disabled.

## Offline verification

From the repository checkout, use the isolated environment:

```powershell
.venv\Scripts\python.exe -m pytest
.venv\Scripts\ruff.exe check .
.venv\Scripts\mypy.exe src --no-incremental --follow-imports=silent
.venv\Scripts\python.exe -m alembic upgrade head
Push-Location web; npm install --no-package-lock --ignore-scripts; npm run build; Pop-Location
```

The PostgreSQL test uses only the disposable CI service and is skipped when no local test service is configured. SQLite migrations can be round-tripped with `alembic upgrade head`, `alembic downgrade base`, then `alembic upgrade head`.

## Safe local workflows

The deterministic demo and read-only dashboard are fixture/local workflows and do not need credentials:

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
.venv\Scripts\python.exe -m sidedeck.demo --help
```

The `web` application is a loopback-only, sanitized view of the protected eToro Demo baseline. It never exposes broker IDs, credentials, monetary values or order controls. See [web/README.md](web/README.md) and [docs/OPERATOR_RUNBOOK.md](docs/OPERATOR_RUNBOOK.md).

## Evidence boundaries

MSFT accounting evidence is filing-dated local evidence; valuation remains blocked until independent historical prices, corporate-action basis and share count reconciliation are proven. Fixture market data, simulated fills and offline agent contracts are not genuine market observations, model calls, trading performance or broker fills. Existing eToro Demo positions remain unattributed and protected.

## Broker priority

eToro **Demo** is the primary paper broker and Alpaca PAPER is secondary ([ADR-003](docs/ADR-003-etoro-demo-primary-broker.md)). eToro Real execution is permanently excluded.

The eToro Demo order desk is offline only. It accepts only a deterministic simulator transport, and execution release is `NO_GO`. An offline rehearsal (no network, synthetic data) runs with:

```powershell
.venv\Scripts\python.exe -m sidedeck.application.sd036_etoro_demo_desk --rehearse
```

See [docs/SD036_ETORO_DEMO_CONTRACT_REVIEW.md](docs/SD036_ETORO_DEMO_CONTRACT_REVIEW.md).

The isolated SD-107 branch adds a separate policy-bound simulator path for autonomous proposals.
Its tests exercise signed-grant checks, fresh sealed quotes, durable order/position lineage,
partial and unresolved outcomes, and a complete simulated close. The SD-103 `ETORO_DEMO` route
remains `NOT_RELEASED`; this code has no production broker transport. Run the offline acceptance
checks with:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_sd063_autonomous_demo_policy.py tests/test_sd074_trusted_inputs.py tests/test_sd108_broker_adapters.py
```

The live execution board and current blockers are maintained in [TODO.md](TODO.md), governed by [SIDEDECK_STEERING.md](SIDEDECK_STEERING.md).

## UK equities (research and simulation only)

SideDeck supports London Stock Exchange instruments for discovery, research and local simulation
([docs/SD088_UK_EQUITY_INTEGRATION.md](docs/SD088_UK_EQUITY_INTEGRATION.md), steering §13):
an XLON calendar (Europe/London, 08:00–16:30, half days, bank holidays, DST), LSE TIDM/ISIN
identity, strict pence (GBX/`GBp`) vs pounds (GBP) normalisation, per-exchange scheduling, a UK
scan on the native scanner/decision engine and a SIMULATION order desk.

```powershell
.venv\Scripts\python.exe -m sidedeck.application.sd096_uk_acceptance
```

No genuine UK market data is held locally, so real-data UK scans abstain; the runner's scan and
trade use a labelled synthetic fixture. UK broker execution is not enabled, and the MSFT eToro
Demo pilot authorization does not extend to UK instruments.
## Day Trader research module

The Day Trader workspace is a read-only research surface. Its pinned-skill fixture command runs
offline and stores sanitized reports locally:

```powershell
.venv\Scripts\python.exe -m sidedeck.application.sd114_day_trader run --fixture --db data/day-trader-runs.sqlite3
```

An isolated synthetic lifecycle acceptance harness exercises SD-071 decisions, SD-072 track
risk, and the SD-079 append-only simulated ledger through protective exit and SQLite restart
reconciliation. It requires a fresh work directory and an explicit fixture-only flag:

```powershell
.venv\Scripts\python.exe -m sidedeck.application.sd121_day_trader_simulation --fixture-acceptance --workdir data/sd121-acceptance
```

The opt-in fixture scheduler reuses SD-068 durable slots and leases, runs 45 minutes after the
XNYS close, and stores append-only schedule audit rows. A Windows Task Scheduler job may invoke
this tick every 30 minutes; it only runs when the scheduled slot is due:

```powershell
.venv\Scripts\python.exe -m sidedeck.application.sd121_day_trader_schedule --fixture-acceptance
```

It runs only the pinned offline fixtures, never real market data.

Its synthetic admission and instrument eligibility are test overrides, labelled
`FIXTURE_ONLY_OVERRIDE_NOT_EVIDENCE`; this does not admit a strategy or enable any broker route.
Genuine intraday data, locked out-of-sample admission, and eToro Demo execution remain blocked.

For a locally supplied CSV, use the research-only backtest command (the input source and rights
note are traceability strings only; SideDeck does not verify either):

```powershell
.venv\Scripts\python.exe -m sidedeck.application.sd114_day_trader backtest-csv --csv .\data\bars.csv --source-label "owner-supplied" --licence-reference "review-note"
```

The CSV must have `timestamp,open,high,low,close,volume` columns and explicit-offset UTC bar
timestamps. Results remain `OWNER_SUPPLIED_UNVERIFIED_NOT_ADMISSION_EVIDENCE`.
