# SD-014–SD-019 real-data strategy validation

The strategy engine is deterministic, offline-only and proposal-only. It
accepts caller-supplied normalized USD regular-session bars, generates signals
from observations available at each close, and delegates execution timing to
the existing next-observation backtest.

The catalogue currently contains versioned channel mean reversion, liquidity-
sweep reversal, moving-average trend following and buy-and-hold benchmark
strategies. Parameter surfaces are exported without selecting a winner.
Selection is explicitly in-sample-only; locked out-of-sample rows are never
used to choose parameters. Walk-forward windows, embargo configuration,
transaction-cost assumptions, portfolio weights, correlation limits and a
drawdown kill-switch simulation are exposed as deterministic controls.

The acceptance report distinguishes `VERIFIED`, `REJECTED`,
`INSUFFICIENT_DATA` and `NOT_ASSESSED`. The screening defaults require four
years of observations, 30 trades and profit factor above 1.15; these are
research screens, not trading authorization or guarantees.

## Genuine MSFT evidence boundary

The existing Alpaca SIP evidence contains 59 regular sessions from 2026-07-29
through 2026-10-20. Running the catalogue against that ignored local bundle
classifies every strategy as `INSUFFICIENT_DATA`; observed trade counts are
also below the configured minimum. No profitability, robustness, or strategy
acceptance claim is made. Five-year evaluation requires a separately lawful,
complete historical dataset; no additional authenticated request was made.

The dashboard exposes only strategy metadata and acceptance status. It does
not display broker positions, balances, simulated fills as live holdings, or
enable order actions.
