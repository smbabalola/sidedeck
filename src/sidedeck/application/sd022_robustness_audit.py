"""Independent, offline audit of SD-021 strategy research reports."""
from __future__ import annotations

import argparse
import json
from decimal import Decimal
from math import sqrt
from pathlib import Path
from typing import Any


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def _closed_trades(ledger: list[dict[str, Any]]) -> list[dict[str, Any]]:
    opened: dict[str, dict[str, Any]] | None = None
    result: list[dict[str, Any]] = []
    for event in sorted(ledger, key=lambda row: str(row["execution_date"])):
        signal = event.get("signal")
        if signal == "BUY":
            if opened is not None:
                raise ValueError("overlapping BUY transactions")
            opened = event
        elif signal == "SELL":
            if opened is None:
                raise ValueError("SELL without an open BUY")
            entry = _dec(opened["equity_after_cost"])
            exit_equity = _dec(event["equity_after_cost"])
            result.append({"entry_date": opened["execution_date"], "exit_date": event["execution_date"],
                           "return": exit_equity / entry - Decimal("1")})
            opened = None
    return result


def _independent_metrics(evaluation: dict[str, Any]) -> dict[str, Any]:
    backtest = evaluation["backtest"]
    rows = list(backtest["results"])
    if not rows:
        raise ValueError("empty equity path")
    equities = [_dec(row["equity"]) for row in rows]
    returns = [_dec(row["return"]) for row in rows]
    ending = equities[-1]
    product = Decimal("1")
    for value in returns:
        product *= Decimal("1") + value
    peak = Decimal("1")
    max_drawdown = Decimal("0")
    for equity in equities:
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak)
    trades = _closed_trades(list(backtest["trade_ledger"]))
    gains = [item["return"] for item in trades if item["return"] > 0]
    losses = [abs(item["return"]) for item in trades if item["return"] < 0]
    profit_factor = sum(gains, Decimal("0")) / sum(losses, Decimal("0")) if losses else None
    mean_return = sum(returns, Decimal("0")) / Decimal(len(returns))
    variance = sum((value - mean_return) ** 2 for value in returns) / Decimal(len(returns))
    volatility = variance.sqrt() * Decimal(str(sqrt(252)))
    sharpe = mean_return / variance.sqrt() * Decimal(str(sqrt(252))) if variance else Decimal("0")
    in_sample = [row for row in rows if row["in_sample"]]
    oos = [row for row in rows if not row["in_sample"]]
    oos_dates = {row["date"] for row in oos}
    oos_product = Decimal("1")
    for row in oos:
        oos_product *= Decimal("1") + _dec(row["return"])
    exposure_dates = 0
    position = False
    event_by_date = {event["execution_date"]: event for event in backtest["trade_ledger"]}
    for row in rows:
        event = event_by_date.get(row["date"])
        if event is not None:
            position = event["signal"] == "BUY"
        exposure_dates += int(position)
    reported = evaluation["metrics"]
    comparisons = {
        "ending_equity_match": product == ending,
        "max_drawdown_delta": str(max_drawdown - _dec(reported["max_drawdown"])),
        "profit_factor_delta": str((profit_factor - _dec(reported["profit_factor"])) if profit_factor is not None else Decimal("0")),
        "sharpe_delta": str(sharpe - _dec(reported["sharpe"])),
    }
    oos_trades = [trade for trade in trades if trade["exit_date"] in oos_dates]
    oos_gains = [trade["return"] for trade in oos_trades if trade["return"] > 0]
    oos_losses = [abs(trade["return"]) for trade in oos_trades if trade["return"] < 0]
    oos_profit_factor = (sum(oos_gains, Decimal("0")) / sum(oos_losses, Decimal("0"))
                         if oos_losses else None)
    oos_equities: list[Decimal] = []
    oos_equity = Decimal("1")
    for row in oos:
        oos_equity *= Decimal("1") + _dec(row["return"])
        oos_equities.append(oos_equity)
    oos_peak = Decimal("1")
    oos_drawdown = Decimal("0")
    for equity in oos_equities:
        oos_peak = max(oos_peak, equity)
        oos_drawdown = max(oos_drawdown, (oos_peak - equity) / oos_peak)
    oos_returns = [_dec(row["return"]) for row in oos]
    oos_mean = sum(oos_returns, Decimal("0")) / Decimal(len(oos_returns)) if oos_returns else Decimal("0")
    oos_variance = (sum((value - oos_mean) ** 2 for value in oos_returns) / Decimal(len(oos_returns))
                    if oos_returns else Decimal("0"))
    oos_sharpe = (oos_mean / oos_variance.sqrt() * Decimal(str(sqrt(252)))
                  if oos_variance else Decimal("0"))
    return {
        "observations": len(rows), "ending_equity": str(ending), "annualized_return": str(
            ending ** (Decimal("252") / Decimal(len(rows))) - Decimal("1")),
        "annualized_volatility": str(volatility), "max_drawdown": str(max_drawdown),
        "profit_factor": str(profit_factor) if profit_factor is not None else "UNDEFINED",
        "sharpe": str(sharpe), "transaction_count": int(backtest["trade_count"]),
        "completed_trade_count": len(trades), "win_rate": str(Decimal(len(gains)) / Decimal(len(trades))) if trades else "UNDEFINED",
        "exposure": str(Decimal(exposure_dates) / Decimal(len(rows))),
        "in_sample_observations": len(in_sample), "oos_observations": len(oos),
        "oos_ending_equity": str(oos_product), "oos_max_drawdown": str(oos_drawdown),
        "oos_sharpe": str(oos_sharpe), "oos_profit_factor": str(oos_profit_factor) if oos_profit_factor is not None else "UNDEFINED",
        "oos_trades": len(oos_trades),
        "benchmark_ending_equity": evaluation["benchmark_ending_equity"],
        "return_to_drawdown": str((ending ** (Decimal("252") / Decimal(len(rows))) - Decimal("1")) / max_drawdown)
            if max_drawdown else "UNDEFINED",
        "fee_slippage_bps": str(_dec(backtest["assumptions"]["fee_bps"]) + _dec(backtest["assumptions"]["slippage_bps"])),
        "comparisons": comparisons,
    }


def _screen_status(metrics: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if metrics["observations"] < 1008:
        reasons.append("INSUFFICIENT_OBSERVATIONS")
    if metrics["completed_trade_count"] < 30:
        reasons.append("INSUFFICIENT_COMPLETED_TRADES")
    if metrics["oos_trades"] < 5:
        reasons.append("INSUFFICIENT_OOS_COMPLETED_TRADES")
    if metrics["profit_factor"] == "UNDEFINED" or _dec(metrics["profit_factor"]) <= Decimal("1.15"):
        reasons.append("PROFIT_FACTOR_BELOW_SCREEN")
    if metrics["oos_profit_factor"] == "UNDEFINED" or _dec(metrics["oos_profit_factor"]) <= Decimal("1.15"):
        reasons.append("OOS_PROFIT_FACTOR_BELOW_SCREEN")
    if metrics["oos_observations"] == 0:
        reasons.append("NO_LOCKED_OUT_OF_SAMPLE")
    return ("INSUFFICIENT_DATA" if any(reason.startswith("INSUFFICIENT") for reason in reasons)
            else "REJECTED" if reasons else "VERIFIED", reasons)


def audit_bundle(path: str | Path) -> dict[str, Any]:
    return audit_report(json.loads(Path(path).read_text(encoding="utf-8")))


def audit_report(data: dict[str, Any]) -> dict[str, Any]:
    """Independent robustness audit of one in-memory SD-021 research report."""
    audited: dict[str, Any] = {}
    for strategy_id, evaluation in data["strategies"].items():
        metrics = _independent_metrics(evaluation)
        status, reasons = _screen_status(metrics)
        surface = data.get("parameter_surfaces", {}).get(strategy_id)
        stability = None
        if surface is not None:
            cells = list(surface["cells"])
            stable = [cell for cell in cells
                      if cell["metrics"].get("profit_factor") != "UNDEFINED"
                      and _dec(cell["metrics"]["profit_factor"]) > Decimal("1.15")
                      and int(cell["metrics"].get("round_trip_count", 0)) >= 30]
            stability = {"cells": len(cells), "screened_cells": len(stable),
                         "selection": surface["selection"], "status": "NOT_SELECTED"}
        audited[strategy_id] = {"prior_status": data["acceptance"][strategy_id]["status"],
                                "audited_status": status, "reasons": reasons,
                                "metrics": metrics, "parameter_stability": stability,
                                "selection_basis": data["training_selection"][strategy_id]["selection_basis"],
                                "locked_oos": data["training_selection"][strategy_id]["locked_oos"],
                                "walk_forward_windows": len(data["walk_forward"][strategy_id]["windows"])}
    portfolio = data["portfolio"]
    correlations = {key: _dec(value) for key, value in portfolio["correlations"].items()}
    portfolio_audit = {"weights_sum": str(sum(_dec(value) for value in portfolio["weights"].values())),
                       "correlation_limit": portfolio["max_correlation"],
                       "max_observed_correlation": str(max(correlations.values(), default=Decimal("0"))),
                       "correlation_status": portfolio["correlation_status"],
                       "broker_execution": portfolio["broker_execution"],
                       "status": "RESEARCH_ONLY"}
    return {"schema_version": 1, "ticker": data["ticker"], "instrument_id": data["instrument_id"],
            "source_bundle_sha256": data.get("source_bundle_sha256"), "strategies": audited,
            "portfolio": portfolio_audit, "data_limitations": [
                "SPLIT_ADJUSTED_PRICE_ONLY", "INDEPENDENT_CORPORATE_ACTION_CORROBORATION_PENDING",
                "PRICE_ONLY_BENCHMARK_EXCLUDES_DIVIDENDS"], "broker_execution": "DISABLED"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run independent SD-022 robustness audit")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = audit_bundle(args.input)
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"{result['ticker']}_AUDITED={len(result['strategies'])}")
    for strategy_id, report in result["strategies"].items():
        print(f"{strategy_id}={report['audited_status']}; COMPLETED_TRADES={report['metrics']['completed_trade_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
