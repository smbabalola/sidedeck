"""Deterministic proposal-only strategy research and portfolio simulation.

The module deliberately accepts caller-supplied normalized bars only. Signals
are generated at a close and executed by :mod:`m2_backtest` at the next
observed price interval; no broker or network access exists here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from itertools import product
from math import sqrt
from statistics import mean
from typing import Any, Iterable, Sequence

from sidedeck.application.m2_backtest import BacktestConfig, BacktestError, run_backtest
from sidedeck.application.m2_market_data import NormalizedBar


class StrategyResearchError(ValueError):
    pass


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    version: str
    parameters: tuple[tuple[str, str], ...]
    holding_period_min: int = 5
    holding_period_max: int = 15
    execution_assumption: str = "NEXT_OBSERVED_CLOSE_INTERVAL"

    def __post_init__(self) -> None:
        if not self.strategy_id.strip() or not self.version.strip():
            raise StrategyResearchError("versioned strategy identity is required")
        if self.holding_period_min < 1 or self.holding_period_max < self.holding_period_min:
            raise StrategyResearchError("invalid holding-period constraints")


@dataclass(frozen=True)
class StrategyBar:
    day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class EvaluationConfig:
    fee_bps: Decimal = Decimal("5")
    slippage_bps: Decimal = Decimal("5")
    train_fraction: Decimal = Decimal("0.80")
    min_observations: int = 252 * 4
    min_trades: int = 30
    embargo_days: int = 0


def bars_from_normalized(bars: Sequence[NormalizedBar]) -> tuple[StrategyBar, ...]:
    if not bars:
        raise StrategyResearchError("historical bars are required")
    ordered = tuple(sorted(bars, key=lambda bar: bar.timestamp))
    if any(bar.session != "REGULAR" or bar.currency != "USD" for bar in ordered):
        raise StrategyResearchError("strategy research requires USD regular-session bars")
    if any(bar.instrument_id != ordered[0].instrument_id for bar in ordered):
        raise StrategyResearchError("one instrument is required per strategy experiment")
    result = tuple(StrategyBar(bar.trading_date, bar.open, bar.high, bar.low, bar.close, bar.volume) for bar in ordered)
    if len({bar.day for bar in result}) != len(result):
        raise StrategyResearchError("duplicate observations are not allowed")
    return result


def _parameter(spec: StrategySpec, name: str, default: int) -> int:
    try:
        return int(dict(spec.parameters).get(name, str(default)))
    except (TypeError, ValueError) as exc:
        raise StrategyResearchError(f"invalid {name} parameter") from exc


def _validate_bars(bars: Sequence[StrategyBar]) -> tuple[StrategyBar, ...]:
    ordered = tuple(sorted(bars, key=lambda bar: bar.day))
    if len({bar.day for bar in ordered}) != len(ordered):
        raise StrategyResearchError("duplicate observations are not allowed")
    if any(any(not isinstance(value, Decimal) or not value.is_finite() or value <= 0
               for value in (bar.open, bar.high, bar.low, bar.close, bar.volume)) for bar in ordered):
        raise StrategyResearchError("OHLCV values must be finite and positive")
    if any(bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close) for bar in ordered):
        raise StrategyResearchError("inconsistent OHLC range")
    return ordered


def catalogue() -> tuple[StrategySpec, ...]:
    return (
        StrategySpec("channel_mean_reversion", "1.0.0", (("lookback", "20"), ("entry_bps", "100"))),
        StrategySpec("liquidity_sweep_reversal", "1.0.0", (("lookback", "20"), ("volume_multiple", "1.5"))),
        StrategySpec("moving_average_trend", "1.0.0", (("fast", "10"), ("slow", "30"))),
        StrategySpec("buy_and_hold", "1.0.0", (), holding_period_min=1, holding_period_max=10_000),
    )


def generate_signals(spec: StrategySpec, bars: Sequence[StrategyBar]) -> dict[date, str]:
    ordered = _validate_bars(bars)
    signals = {bar.day: "HOLD" for bar in ordered}
    if spec.strategy_id == "buy_and_hold":
        if ordered:
            signals[ordered[0].day] = "BUY"
        return signals
    lookback = _parameter(spec, "lookback", 20)
    if lookback < 2 or lookback >= len(ordered):
        raise StrategyResearchError("lookback requires prior observations")
    closes = [bar.close for bar in ordered]
    held = False
    for index, bar in enumerate(ordered):
        if index < lookback:
            continue
        window = closes[index - lookback:index]
        if spec.strategy_id == "moving_average_trend":
            fast = _parameter(spec, "fast", 10)
            slow = _parameter(spec, "slow", 30)
            if fast < 2 or slow <= fast or slow >= len(ordered):
                raise StrategyResearchError("moving-average windows are invalid")
            if index < slow:
                continue
            fast_avg = sum(closes[index - fast:index], Decimal("0")) / Decimal(fast)
            slow_avg = sum(closes[index - slow:index], Decimal("0")) / Decimal(slow)
            desired = fast_avg > slow_avg
        elif spec.strategy_id == "channel_mean_reversion":
            entry_bps = Decimal(dict(spec.parameters).get("entry_bps", "100"))
            if entry_bps < 0:
                raise StrategyResearchError("entry_bps must be nonnegative")
            low = min(window)
            high = max(window)
            width = high - low
            desired = bar.close <= low + width * entry_bps / Decimal("10000")
            if held and bar.close >= (low + high) / Decimal("2"):
                desired = False
        elif spec.strategy_id == "liquidity_sweep_reversal":
            multiple = Decimal(dict(spec.parameters).get("volume_multiple", "1.5"))
            if not multiple.is_finite() or multiple <= 0:
                raise StrategyResearchError("volume_multiple must be positive")
            prior_low = min(window)
            average_volume = sum((item.volume for item in ordered[index - lookback:index]), Decimal("0")) / Decimal(lookback)
            desired = bar.low < prior_low and bar.close > prior_low and bar.volume >= average_volume * multiple
        else:
            raise StrategyResearchError("unknown strategy")
        if desired and not held:
            signals[bar.day] = "BUY"
            held = True
        elif not desired and held:
            signals[bar.day] = "SELL"
            held = False
    return signals


def _split_dates(bars: Sequence[StrategyBar], config: EvaluationConfig) -> tuple[date, date | None]:
    if not 0 < config.train_fraction < 1:
        raise StrategyResearchError("train_fraction must be between zero and one")
    if config.min_observations < 2 or config.min_trades < 0 or config.embargo_days < 0:
        raise StrategyResearchError("invalid evaluation thresholds")
    ordered = _validate_bars(bars)
    split_index = max(1, min(len(ordered) - 1, int(len(ordered) * config.train_fraction)))
    split = ordered[split_index].day
    oos_start = split + timedelta(days=config.embargo_days)
    return ordered[0].day, oos_start


def _metrics(result: dict[str, Any], bars: Sequence[StrategyBar], oos_start: date | None) -> dict[str, Any]:
    returns = [Decimal(str(row["return"])) for row in result["results"]]
    positive = [value for value in returns if value > 0]
    negative = [abs(value) for value in returns if value < 0]
    exposure = sum(1 for value in returns if value != 0) / len(returns) if returns else 0.0
    arithmetic = mean(float(value) for value in returns) if returns else 0.0
    deviation = (sum((float(value) - arithmetic) ** 2 for value in returns) / len(returns)) ** 0.5 if returns else 0.0
    sharpe = arithmetic / deviation * sqrt(252) if deviation else 0.0
    years = Decimal(max(1, len(bars) - 1)) / Decimal("252")
    ending = Decimal(str(result["ending_equity"]))
    annualized = ending ** (Decimal("1") / years) - Decimal("1") if ending > 0 else Decimal("-1")
    trade_count = int(result["trade_count"])
    oos = [row for row in result["results"] if oos_start is not None and row["date"] >= oos_start.isoformat()]
    return {
        "annualized_return": str(annualized), "max_drawdown": result["max_drawdown"],
        "profit_factor": str(sum(positive, Decimal("0")) / sum(negative, Decimal("0"))) if negative else "UNDEFINED",
        "sharpe": str(Decimal(str(sharpe))), "trade_count": trade_count,
        "win_rate": str(Decimal(len(positive)) / Decimal(len(returns))) if returns else "0",
        "average_gain": str(sum(positive, Decimal("0")) / Decimal(len(positive))) if positive else "0",
        "average_loss": str(sum(negative, Decimal("0")) / Decimal(len(negative))) if negative else "0",
        "market_exposure": str(Decimal(str(exposure))), "out_of_sample_days": len(oos),
        "status": "INSUFFICIENT_DATA" if len(bars) < 252 * 4 or trade_count < 30 else "NOT_ASSESSED",
    }


def evaluate_strategy(spec: StrategySpec, bars: Sequence[StrategyBar], config: EvaluationConfig = EvaluationConfig()) -> dict[str, Any]:
    ordered = _validate_bars(bars)
    start, oos_start = _split_dates(ordered, config)
    signals = generate_signals(spec, ordered)
    try:
        result = run_backtest(
            {bar.day: bar.close for bar in ordered}, signals,
            BacktestConfig(f"{spec.strategy_id}:{spec.version}", spec.version,
                           config.fee_bps, config.slippage_bps, oos_start),
        )
    except BacktestError as exc:
        raise StrategyResearchError(str(exc)) from exc
    benchmark = {bar.day: bar.close for bar in ordered}
    return {
        "strategy": {"id": spec.strategy_id, "version": spec.version, "parameters": dict(spec.parameters)},
        "data": {"start": start.isoformat(), "end": ordered[-1].day.isoformat(), "observations": len(ordered),
                 "provenance": "CALLER_SUPPLIED_NORMALIZED_BARS"},
        "metrics": _metrics(result, ordered, oos_start),
        "benchmark_ending_equity": str(benchmark[ordered[-1].day] / benchmark[ordered[0].day]),
        "backtest": result, "selection": "NO_PARAMETER_SELECTED",
        "status": _metrics(result, ordered, oos_start)["status"], "broker_execution": "DISABLED",
    }


def parameter_surface(
    base: StrategySpec, bars: Sequence[StrategyBar], axes: dict[str, tuple[str, ...]], config: EvaluationConfig = EvaluationConfig()
) -> dict[str, Any]:
    if not axes or any(not values for values in axes.values()):
        raise StrategyResearchError("parameter surface axes cannot be empty")
    keys = tuple(axes)
    cells = []
    for values in product(*(axes[key] for key in keys)):
        spec = StrategySpec(base.strategy_id, base.version, tuple(sorted({**dict(base.parameters), **dict(zip(keys, values))}.items())),
                            base.holding_period_min, base.holding_period_max)
        evaluation = evaluate_strategy(spec, bars, config)
        cells.append({"parameters": dict(spec.parameters), "metrics": evaluation["metrics"],
                      "status": evaluation["status"]})
    return {"axes": {key: list(values) for key, values in axes.items()}, "cells": cells,
            "selection": "NOT_SELECTED", "status": "RESEARCH_ONLY", "broker_execution": "DISABLED"}


def select_on_training(
    candidates: Iterable[StrategySpec], bars: Sequence[StrategyBar], config: EvaluationConfig = EvaluationConfig()
) -> dict[str, Any]:
    ordered = _validate_bars(bars)
    _, oos_start = _split_dates(ordered, config)
    evaluations = [evaluate_strategy(candidate, ordered, config) for candidate in candidates]
    if not evaluations:
        raise StrategyResearchError("at least one candidate is required")
    train = [item for item in evaluations if item["backtest"]["in_sample_days"] > 0]
    def in_sample_ending(item: dict[str, Any]) -> Decimal:
        rows = [row for row in item["backtest"]["results"] if row["in_sample"]]
        return Decimal(str(rows[-1]["equity"])) if rows else Decimal("0")

    selected = max(train, key=in_sample_ending)
    if oos_start is None:
        raise StrategyResearchError("locked out-of-sample boundary is required")
    return {"selected_strategy": selected["strategy"], "oos_start": oos_start.isoformat(),
            "candidates": [{"strategy": item["strategy"], "status": item["status"]} for item in evaluations],
            "selection_basis": "IN_SAMPLE_ONLY", "locked_oos": True,
            "status": "INSUFFICIENT_DATA" if len(ordered) < config.min_observations else "NOT_ASSESSED",
            "broker_execution": "DISABLED"}


def walk_forward_evaluate(
    spec: StrategySpec, bars: Sequence[StrategyBar], *, train_size: int, test_size: int,
    config: EvaluationConfig = EvaluationConfig(),
) -> dict[str, Any]:
    """Evaluate chronological train/test windows without reusing future rows."""
    ordered = _validate_bars(bars)
    if train_size < 2 or test_size < 1 or train_size + test_size > len(ordered):
        raise StrategyResearchError("invalid walk-forward window")
    windows: list[dict[str, Any]] = []
    start = 0
    while start + train_size + test_size <= len(ordered):
        window = ordered[start:start + train_size + test_size]
        split = window[train_size].day
        window_config = EvaluationConfig(config.fee_bps, config.slippage_bps,
                                         Decimal(train_size) / Decimal(train_size + test_size),
                                         min(config.min_observations, len(window)), config.min_trades,
                                         config.embargo_days)
        evaluation = evaluate_strategy(spec, window, window_config)
        oos_rows = [row for row in evaluation["backtest"]["results"] if not row["in_sample"]]
        windows.append({"train_start": window[0].day.isoformat(), "test_start": split.isoformat(),
                        "test_end": window[-1].day.isoformat(), "out_of_sample_rows": len(oos_rows),
                        "status": "NOT_ASSESSED" if len(oos_rows) else "INSUFFICIENT_DATA"})
        start += test_size
    return {"strategy": {"id": spec.strategy_id, "version": spec.version}, "windows": windows,
            "selection": "NO_PARAMETER_SELECTED", "status": "NOT_ASSESSED" if windows else "INSUFFICIENT_DATA",
            "broker_execution": "DISABLED"}


def acceptance_report(
    evaluation: dict[str, Any], *, minimum_observations: int = 252 * 4,
    minimum_trades: int = 30, minimum_profit_factor: Decimal = Decimal("1.15"),
) -> dict[str, Any]:
    metrics = evaluation["metrics"]
    observations = int(evaluation["data"]["observations"])
    trades = int(metrics["trade_count"])
    reasons: list[str] = []
    if observations < minimum_observations:
        reasons.append("INSUFFICIENT_OBSERVATIONS")
    if trades < minimum_trades:
        reasons.append("INSUFFICIENT_TRADES")
    profit_factor = metrics["profit_factor"]
    if profit_factor != "UNDEFINED" and Decimal(str(profit_factor)) <= minimum_profit_factor:
        reasons.append("PROFIT_FACTOR_BELOW_SCREEN")
    if metrics["out_of_sample_days"] == 0:
        reasons.append("NO_LOCKED_OUT_OF_SAMPLE")
    status = "INSUFFICIENT_DATA" if any(reason.startswith("INSUFFICIENT") for reason in reasons) else "REJECTED" if reasons else "VERIFIED"
    return {"strategy": evaluation["strategy"], "status": status, "reasons": reasons,
            "criteria": {"minimum_observations": minimum_observations, "minimum_trades": minimum_trades,
                          "minimum_profit_factor": str(minimum_profit_factor), "max_correlation": "0.70"},
            "genuine_profitability": "NOT_ESTABLISHED" if status != "VERIFIED" else "SCREENED_NOT_AUTHORIZED",
            "broker_execution": "DISABLED"}


def simulate_portfolio(
    evaluations: dict[str, dict[str, Any]], *, max_correlation: Decimal = Decimal("0.70"),
    max_exposure: Decimal = Decimal("1"), kill_drawdown_multiple: Decimal = Decimal("1.5"),
) -> dict[str, Any]:
    if not evaluations or max_correlation < 0 or max_correlation > 1 or max_exposure <= 0 or kill_drawdown_multiple <= 0:
        raise StrategyResearchError("invalid portfolio simulation configuration")
    series = {name: [Decimal(str(row["return"])) for row in value["backtest"]["results"]] for name, value in evaluations.items()}
    lengths = {len(values) for values in series.values()}
    if len(lengths) != 1 or not next(iter(lengths)):
        raise StrategyResearchError("portfolio strategies require aligned return series")
    names = tuple(series)
    returns = [sum((values[index] for values in series.values()), Decimal("0")) / Decimal(len(names))
               for index in range(len(next(iter(series.values()))))]
    equity = Decimal("1")
    peak = equity
    max_drawdown = Decimal("0")
    for value in returns:
        equity *= Decimal("1") + value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak)
    correlations: dict[str, str] = {}
    for left_index, left in enumerate(names):
        for right in names[left_index + 1:]:
            left_values = [float(value) for value in series[left]]
            right_values = [float(value) for value in series[right]]
            left_mean = sum(left_values) / len(left_values)
            right_mean = sum(right_values) / len(right_values)
            numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left_values, right_values))
            left_norm = sum((a - left_mean) ** 2 for a in left_values) ** 0.5
            right_norm = sum((b - right_mean) ** 2 for b in right_values) ** 0.5
            correlation = numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0
            correlations[f"{left}:{right}"] = str(Decimal(str(correlation)))
    correlation_status = "REJECTED" if any(Decimal(value) > max_correlation for value in correlations.values()) else "VERIFIED"
    return {"strategies": names, "weights": {name: str(Decimal("1") / Decimal(len(names))) for name in names},
            "ending_equity": str(equity), "max_drawdown": str(max_drawdown),
            "max_correlation": str(max_correlation), "kill_switch_threshold": str(kill_drawdown_multiple),
            "exposure_limit": str(max_exposure), "correlations": correlations, "correlation_status": correlation_status,
            "attribution": {name: str(sum(series[name], Decimal("0")) / Decimal(len(names))) for name in names},
            "status": "RESEARCH_ONLY", "broker_execution": "DISABLED"}
