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
