# SideDeck Track A MVP report

Date: 2026-10-18  
Branch: `feat/p2-agent-adapters`  
Status: runnable offline demo; no upstream engine or broker integration

## Launch

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe -m sidedeck.demo reset-fixture --results-dir results
.venv\Scripts\python.exe -m sidedeck.demo run --results-dir results
```

The generated `results/dashboard.html` is a local side-by-side view. `report.json` and `trades.csv` are machine-readable exports. `results/demo.sqlite3` contains the restart-safe P1 journal and P2A audit records. The results directory is ignored and was not committed.

## Demonstrated output

The deterministic three-session fixture run creates separate $1,000 `tradingagents` and `ai-trading` portfolios. Both execute local fixture BUY/SELL paths with fees and realized P&L; the final generated values were:

| Portfolio | Cash | NAV | Realized net P&L | Fees |
|---|---:|---:|---:|---:|
| tradingagents | 1009.6850 | 1009.6850 | 9.6850 | 0.21 |
| ai-trading | 1009.3850 | 1009.3850 | 9.3850 | 0.41 |

These are synthetic fixture prices and simulated fills, not market observations, upstream AI results or profitability claims. Re-running without `reset-fixture` reuses the persisted report and does not duplicate economic journal events.

## Acceptance evidence

- 34 local tests passed; one local PostgreSQL test skipped because Docker has no usable daemon.
- Ruff passed; mypy passed for 19 source files.
- SQLite Alembic upgrade through `0004_agent_audits` passed.
- Risk controls cover portfolio isolation, approved instruments, point-in-time data, cash, position/exposure/position-count caps, stop-risk budget, long-only selling, fees, spread and refusal reasons.
- Simulator lifecycle covers partial fill and cancellation; P1 journal replay provides accounting and restart persistence.
- No network client, broker endpoint, credential, eToro path or upstream AI source is used.

## Remaining external gates

Actual TradingAgents execution still requires owner-approved model credentials and controlled upstream compatibility testing. The unlicensed `imranpollob/ai-trading` source remains blocked and was not imported or executed. eToro and all broker writes remain out of scope.
