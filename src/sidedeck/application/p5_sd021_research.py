"""Offline SD-021 strategy evaluation over admitted historical bundles."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sidedeck.application.m2_market_data import normalize_daily_bars
from sidedeck.application.sd014_strategy_engine import (
    EvaluationConfig, acceptance_report, catalogue, evaluate_strategy, parameter_surface,
    StrategySpec, select_on_training, simulate_portfolio, walk_forward_evaluate, bars_from_normalized,
)


SD021_CUTOFF = datetime(2026, 10, 20, 23, 59, 59, tzinfo=timezone.utc)


def run_bundle(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return research_payload(payload, cutoff=SD021_CUTOFF)


def research_payload(payload: dict[str, Any], *, cutoff: datetime) -> dict[str, Any]:
    """SD-021 research on one admitted bundle, using only bars at or before ``cutoff``."""
    bars, normalization = normalize_daily_bars(payload, cutoff=cutoff)
    strategy_bars = bars_from_normalized(bars)
    config = EvaluationConfig()
    evaluations: dict[str, dict[str, Any]] = {}
    reports: dict[str, dict[str, Any]] = {}
    surfaces: dict[str, dict[str, Any]] = {}
    walk_forward: dict[str, dict[str, Any]] = {}
    training_selection: dict[str, dict[str, Any]] = {}
    axes: dict[str, dict[str, tuple[str, ...]]] = {
        "channel_mean_reversion": {"lookback": ("10", "20", "40"), "entry_bps": ("50", "100", "200")},
        "liquidity_sweep_reversal": {"lookback": ("10", "20", "40"), "volume_multiple": ("1.25", "1.5", "2.0")},
        "moving_average_trend": {"fast": ("5", "10", "20"), "slow": ("30", "60", "120")},
    }
    for spec in catalogue():
        evaluation = evaluate_strategy(spec, strategy_bars, config)
        evaluations[spec.strategy_id] = evaluation
        reports[spec.strategy_id] = acceptance_report(evaluation)
        if spec.strategy_id in axes:
            surfaces[spec.strategy_id] = parameter_surface(spec, strategy_bars, axes[spec.strategy_id], config)
            candidates = [spec]
            for key, values in axes[spec.strategy_id].items():
                candidates = [
                    StrategySpec(spec.strategy_id, spec.version,
                                 tuple(sorted({**dict(candidate.parameters), key: value}.items())),
                                 spec.holding_period_min, spec.holding_period_max)
                    for candidate in candidates for value in values
                ]
            training_selection[spec.strategy_id] = select_on_training(candidates, strategy_bars, config)
        else:
            training_selection[spec.strategy_id] = select_on_training([spec], strategy_bars, config)
        walk_forward[spec.strategy_id] = walk_forward_evaluate(
            spec, strategy_bars, train_size=800, test_size=100, config=config,
        )
    portfolio = simulate_portfolio(evaluations)
    return {
        "schema_version": 1, "instrument_id": payload["instrument_id"],
        "ticker": payload["ticker"], "source_bundle_sha256": payload.get("source_bundle_sha256"),
        "data": {"start": strategy_bars[0].day.isoformat(), "end": strategy_bars[-1].day.isoformat(),
                 "observations": len(strategy_bars), "normalization": normalization,
                 "provenance": payload.get("source_identity"), "feed": payload.get("feed"),
                 "adjustment": payload.get("adjustment")},
        "strategies": evaluations, "acceptance": reports, "parameter_surfaces": surfaces,
        "training_selection": training_selection, "walk_forward": walk_forward, "portfolio": portfolio,
        "broker_execution": "DISABLED", "genuine_profitability": "RESEARCH_SCREEN_ONLY",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run offline SD-021 strategy research")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run_bundle(args.input)
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"{result['ticker']}_STRATEGIES={len(result['strategies'])}; OBSERVATIONS={result['data']['observations']}")
    for strategy_id, report in result["acceptance"].items():
        print(f"{strategy_id}={report['status']}; TRADES={result['strategies'][strategy_id]['metrics']['trade_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
