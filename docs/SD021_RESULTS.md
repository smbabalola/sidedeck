# SD-021 five-year SIP research results

Status: retrieval and offline proposal-only evaluation completed 2026-10-21.
The datasets are `ADMITTED_RESEARCH_ONLY`, not valuation-admitted or trade
authorized. No account, order, paper or real execution path was used.

## Retrieval and admission

The exact owner-authorized Alpaca Market Data scope was used: `GET
/v2/stocks/{ticker}/bars`, SPY/QQQ/MSFT only, SIP, `1Day`, split-adjusted,
USD, ascending, 2021-10-21 through 2026-10-20. Each ticker used one HTTP 200
request, one page and no retry. Total usage was 3/60 requests; each ticker
used 1/20.

| Ticker | Bars | Coverage | SHA-256 of raw ignored bundle | Admission |
| --- | ---: | --- | --- | --- |
| SPY | 1,254 | 2021-10-21–2026-10-20 | `9e7dec378b9777eff894c343e6695676d880c9cc7797faa0df4f021b7c6cdfbd` | ADMITTED_RESEARCH_ONLY |
| QQQ | 1,254 | 2021-10-21–2026-10-20 | `3593259e1f541660a769bf398bd1951553e468d03b87148feb92e3db9a2f2053` | ADMITTED_RESEARCH_ONLY |
| MSFT | 1,254 | 2021-10-21–2026-10-20 | `b89d99d2a44afcf0ed92c108d849aef0981ec5d1fac46b7f5a0fbc8b1375c094` | ADMITTED_RESEARCH_ONLY |

The deterministic 2021–2026 US equity calendar matched all 1,254 observations
for each ticker. SPY's retrieved generic exchange metadata was normalized to
the approved `NYSE_ARCA` identity in the derived admission bundle and the
correction is recorded in its validation report. The source remains Alpaca SIP
and the raw bundle is preserved unchanged.

Independent corporate-action/dividend corroboration remains pending. The
series is split-adjusted close data, not a total-return series; this does not
close SD-004's independent valuation gate.

## Strategy evaluation

The existing next-observation execution model used 5 bps fee plus 5 bps
slippage, a chronological 80/20 split with 251 locked OOS observations,
in-sample-only parameter selection, 9-cell surfaces for each parameterized
strategy, and four 800/100 walk-forward windows. No OOS result selected a
parameter. Trade metrics use closed round-trip outcomes where available.

`VERIFIED` below means the established screening criteria were met by the
research report. It is not a claim of durable profitability or authorization.

| Ticker | Strategy | Status | Transactions | Round trips | Profit factor | Annualized return | Max drawdown |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| SPY | Channel mean reversion | VERIFIED | 122 | 61 | 1.896 | 2.77% | 9.01% |
| SPY | Liquidity-sweep reversal | REJECTED | 34 | 17 | 0.590 | -1.63% | 10.29% |
| SPY | Moving-average trend | VERIFIED | 39 | 19 | 2.135 | 5.07% | 18.75% |
| SPY | Buy and hold | INSUFFICIENT_DATA | 1 | 0 | 1.134 | 11.18% | 25.36% |
| QQQ | Channel mean reversion | VERIFIED | 130 | 65 | 1.977 | 5.52% | 8.16% |
| QQQ | Liquidity-sweep reversal | REJECTED | 36 | 18 | 0.373 | -3.96% | 20.01% |
| QQQ | Moving-average trend | VERIFIED | 45 | 22 | 1.935 | 6.52% | 23.38% |
| QQQ | Buy and hold | INSUFFICIENT_DATA | 1 | 0 | 1.124 | 13.78% | 35.62% |
| MSFT | Channel mean reversion | VERIFIED | 152 | 76 | 1.595 | 3.83% | 17.06% |
| MSFT | Liquidity-sweep reversal | INSUFFICIENT_DATA | 18 | 9 | 0.009 | -2.87% | 13.49% |
| MSFT | Moving-average trend | REJECTED | 53 | 26 | 0.911 | 3.00% | 29.40% |
| MSFT | Buy and hold | INSUFFICIENT_DATA | 1 | 0 | 1.097 | 11.39% | 37.56% |

## Portfolio simulation

Equal-weight proposal simulations remained `RESEARCH_ONLY` with correlation
limit 0.70 and configurable 1.5x drawdown kill-switch threshold:

| Ticker | Ending equity | Max drawdown | Correlation control |
| --- | ---: | ---: | --- |
| SPY | 1.313 | 10.13% | VERIFIED |
| QQQ | 1.402 | 13.58% | VERIFIED |
| MSFT | 1.324 | 19.07% | VERIFIED |

These are deterministic historical simulations with no capital allocation,
broker state or order capability. They are not investment recommendations.

## Remaining blockers

- SD-004 remains blocked: no independent closing-price corroboration and no
  valuation admission is emitted.
- Dividend/total-return treatment is not part of the split-adjusted close
  series; benchmark interpretation remains limited.
- Strategy `VERIFIED` statuses are screening outputs only. Further robustness
  work should test alternate lawful data sources, multiple market regimes,
  parameter stability under locked OOS, and independent calculation review.
- SD-008, SD-011 and SD-013 remain behind their separate model, paper-release
  and soak approvals.

