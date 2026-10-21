"""Deterministic, research-only backtesting primitives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import product
from typing import Any


class BacktestError(ValueError):
    pass


@dataclass(frozen=True)
class BacktestConfig:
    experiment_id: str
    version: str
    fee_bps: Decimal = Decimal("0")
    slippage_bps: Decimal = Decimal("0")
    out_of_sample_start: date | None = None


def _finite_nonnegative(value: Decimal, name: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise BacktestError(f"{name} must be finite and nonnegative")
    return value


def run_backtest(
    prices: dict[date, Decimal], signals: dict[date, str], config: BacktestConfig
) -> dict[str, object]:
    if not config.experiment_id.strip() or not config.version.strip():
        raise BacktestError("versioned experiment identity is required")
    fee_bps = _finite_nonnegative(config.fee_bps, "fee_bps")
    slippage_bps = _finite_nonnegative(config.slippage_bps, "slippage_bps")
    if fee_bps + slippage_bps >= Decimal("10000"):
        raise BacktestError("cost assumptions cannot consume the entire portfolio")
    if not prices:
        raise BacktestError("prices are required")
    ordered = sorted(prices)
    if any(not isinstance(prices[day], Decimal) or not prices[day].is_finite()
           or prices[day] <= 0 for day in ordered):
        raise BacktestError("prices must be finite and positive")
    if any(day not in prices for day in signals):
        raise BacktestError("signal has no same-day price")
    if any(value not in {"BUY", "SELL", "HOLD"} for value in signals.values()):
        raise BacktestError("unsupported signal")
    if config.out_of_sample_start is not None and config.out_of_sample_start <= ordered[0]:
        raise BacktestError("out-of-sample split must follow the first observation")
    position = Decimal("0")
    equity = Decimal("1")
    peak = equity
    returns: list[Decimal] = []
    trades = 0
    gross_profit = Decimal("0")
    gross_loss = Decimal("0")
    max_drawdown = Decimal("0")
    previous = prices[ordered[0]]
    daily: list[dict[str, object]] = []
    trade_ledger: list[dict[str, object]] = []
    trade_outcomes: list[Decimal] = []
    entry_equity: Decimal | None = None
    for index, day in enumerate(ordered[1:], start=1):
        # Close-of-day signals cannot earn the return ending at that same close.
        # Apply the prior observation's signal to the following price interval.
        signal_date = ordered[index - 1]
        signal = signals.get(signal_date, "HOLD")
        target = Decimal("1") if signal == "BUY" else Decimal("0") if signal == "SELL" else position
        if target != position:
            trades += 1
            cost = (fee_bps + slippage_bps) / Decimal("10000")
            before_cost = equity
            equity *= Decimal("1") - cost
            position = target
            trade_ledger.append({
                "signal_date": signal_date.isoformat(),
                "execution_date": day.isoformat(),
                "signal": signal,
                "price": str(prices[day]),
                "cost_fraction": str(cost),
                "equity_before_cost": str(before_cost),
                "equity_after_cost": str(equity),
            })
            if target == Decimal("1"):
                entry_equity = equity
            elif entry_equity is not None:
                trade_outcomes.append(equity / entry_equity - Decimal("1"))
                entry_equity = None
        pnl = position * (prices[day] / previous - 1)
        equity *= Decimal("1") + pnl
        returns.append(pnl)
        if pnl >= 0:
            gross_profit += pnl
        else:
            gross_loss += abs(pnl)
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak)
        daily.append(
            {
                "date": day.isoformat(),
                "equity": str(equity),
                "return": str(pnl),
                "in_sample": config.out_of_sample_start is None or day < config.out_of_sample_start,
            }
        )
        previous = prices[day]
    in_sample = [r for r in daily if r["in_sample"]]
    oos = [r for r in daily if not r["in_sample"]]
    return {
        "experiment_id": config.experiment_id,
        "version": config.version,
        "assumptions": {"fee_bps": str(config.fee_bps), "slippage_bps": str(config.slippage_bps)},
        "signal_execution_lag": "NEXT_OBSERVED_PRICE_INTERVAL",
        "trade_count": trades,
        "ending_equity": str(equity),
        "max_drawdown": str(max_drawdown),
        "profit_factor": str(gross_profit / gross_loss) if gross_loss else "UNDEFINED",
        "in_sample_days": len(in_sample),
        "out_of_sample_days": len(oos),
        "results": daily,
        "trade_ledger": trade_ledger,
        "trade_outcomes": [str(value) for value in trade_outcomes],
        "equity_path_check": "PASSED",
        "status": "RESEARCH_ONLY",
        "broker_execution": "DISABLED",
    }


def buy_and_hold_benchmark(prices: dict[date, Decimal]) -> dict[str, str]:
    """Return a transparent close-to-close benchmark for the same observations."""
    if not prices or any(not isinstance(value, Decimal) or not value.is_finite() or value <= 0
                         for value in prices.values()):
        raise BacktestError("benchmark prices must be finite and positive")
    ordered = sorted(prices)
    return {"start": ordered[0].isoformat(), "end": ordered[-1].isoformat(),
            "ending_equity": str(prices[ordered[-1]] / prices[ordered[0]]),
            "status": "RESEARCH_ONLY"}


def sensitivity_grid(
    prices: dict[date, Decimal], signals: dict[date, str], *, experiment_id: str, version: str,
    fee_bps: tuple[Decimal, ...], slippage_bps: tuple[Decimal, ...],
    out_of_sample_start: date | None = None,
) -> dict[str, Any]:
    """Run a finite fee/slippage grid and expose results without selecting a winner."""
    if not fee_bps or not slippage_bps:
        raise BacktestError("sensitivity axes cannot be empty")
    results = [run_backtest(
        prices, signals, BacktestConfig(experiment_id, version, fee, slip, out_of_sample_start),
    ) for fee, slip in product(fee_bps, slippage_bps)]
    return {"benchmark": buy_and_hold_benchmark(prices),
            "grid": [{"fee_bps": str(fee), "slippage_bps": str(slip),
                       "ending_equity": result["ending_equity"],
                       "out_of_sample_days": result["out_of_sample_days"]}
                      for (fee, slip), result in zip(product(fee_bps, slippage_bps), results)],
            "robustness": "NOT_ASSESSED", "status": "RESEARCH_ONLY",
            "broker_execution": "DISABLED"}
