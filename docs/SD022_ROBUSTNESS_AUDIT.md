# SD-022 independent strategy robustness audit

Status: completed offline on 2026-10-21. Inputs are the three ignored,
research-only SD-021 bundles. No network, credential, broker, paid-data,
model, account or trading action was used.

## Audit method

The audit recalculated equity compounding, annualized return, volatility,
drawdown, Sharpe, profit factor, closed round-trip outcomes, exposure, fees
and slippage from the saved research ledger and daily path, independently of
the strategy engine metric helper. Reconciliations were zero or floating-point
rounding at approximately `1e-16` for drawdown, profit factor and Sharpe.

The denominator is now explicit: a completed independent trade is one BUY
followed by a SELL. Open positions do not count as profitable completed trades.
The minimum screen is 30 completed trades, plus at least 5 locked-OOS completed
trades and locked-OOS profit factor above 1.15 for robustness survival.

Selection remained `IN_SAMPLE_ONLY`; no OOS result selected a parameter. Each
parameterized strategy had a 9-cell surface, and each audit retained the
surface's `NOT_SELECTED` status. Each strategy had four chronological 800/100
walk-forward windows with 400 OOS rows in total.

## Status correction

| Instrument | Strategy | Prior SD-021 | SD-022 | Completed trades | OOS PF | OOS ending equity | Reason |
| --- | --- | --- | --- | ---: | ---: | ---: | --- |
| SPY | Channel mean reversion | VERIFIED | VERIFIED | 61 | 5.987 | 1.094 | 9/9 surface cells screened; OOS screen passed |
| SPY | Liquidity-sweep reversal | REJECTED | INSUFFICIENT_DATA | 17 | 0.456 | 0.994 | Fewer than 30 completed trades |
| SPY | Moving-average trend | VERIFIED | INSUFFICIENT_DATA | 19 | 5.684 | 1.008 | Fewer than 30 completed trades |
| SPY | Buy and hold | INSUFFICIENT_DATA | INSUFFICIENT_DATA | 0 | UNDEFINED | 1.146 | No closed trade |
| QQQ | Channel mean reversion | VERIFIED | VERIFIED | 65 | 1.696 | 1.044 | 9/9 surface cells screened; OOS screen passed |
| QQQ | Liquidity-sweep reversal | REJECTED | INSUFFICIENT_DATA | 18 | 1.470 | 1.012 | Fewer than 30 completed trades |
| QQQ | Moving-average trend | VERIFIED | INSUFFICIENT_DATA | 22 | 7.237 | 1.045 | Fewer than 30 completed trades |
| QQQ | Buy and hold | INSUFFICIENT_DATA | INSUFFICIENT_DATA | 0 | UNDEFINED | 1.173 | No closed trade |
| MSFT | Channel mean reversion | VERIFIED | REJECTED | 76 | 0.382 | 0.902 | OOS PF below 1.15; OOS loss |
| MSFT | Liquidity-sweep reversal | INSUFFICIENT_DATA | INSUFFICIENT_DATA | 9 | 0.000 | 0.957 | Fewer than 30 completed trades |
| MSFT | Moving-average trend | REJECTED | INSUFFICIENT_DATA | 26 | 0.117 | 1.098 | Fewer than 30 completed trades |
| MSFT | Buy and hold | INSUFFICIENT_DATA | INSUFFICIENT_DATA | 0 | UNDEFINED | 1.029 | No closed trade |

The five prior whole-period screens therefore reduce to two robustness
survivors: SPY and QQQ channel mean reversion. They are still screening
results, not paper-trading candidates or profitability guarantees.

## Economic and portfolio findings

The two survivors use approximately 9.7% and 10.1% whole-period exposure and
have whole-period drawdowns of 9.01% and 8.16%, respectively. Their annualized
returns remain below their corresponding price-only buy-and-hold benchmarks;
the lower exposure/drawdown profile is not by itself proof of economic value.
The benchmark excludes dividends and is not a total-return benchmark.

Independent portfolio checks confirmed weights sum to 1 and the within-
instrument strategy correlation ceilings remain below 0.70: maximum observed
correlation was 0.628 for SPY, 0.644 for QQQ and 0.668 for MSFT. The simulator
remains `RESEARCH_ONLY` with broker execution disabled. These correlations do
not establish that SPY and QQQ are independent exposures; cross-instrument
overlap and rebalance/cash assumptions remain limitations.

## Data and corporate-action limitations

The underlying 1,254-bar bundles remain `ADMITTED_RESEARCH_ONLY`. They are
split-adjusted SIP close data, not dividend-reinvested total-return data.
Independent corporate-action/dividend corroboration remains pending, so SD-004
valuation admission remains blocked. No strategy result changes that gate.

