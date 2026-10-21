from datetime import date, timedelta
from decimal import Decimal

import pytest

from sidedeck.application.sd014_strategy_engine import (
    EvaluationConfig,
    StrategyBar,
    StrategyResearchError,
    StrategySpec,
    catalogue,
    evaluate_strategy,
    acceptance_report,
    generate_signals,
    parameter_surface,
    select_on_training,
    simulate_portfolio,
    walk_forward_evaluate,
)


def bars(count: int = 40) -> tuple[StrategyBar, ...]:
    return tuple(
        StrategyBar(date(2025, 1, 1) + timedelta(days=index), Decimal("100"),
                    Decimal(str(101 + index)), Decimal("99"),
                    Decimal(str(100 + index)), Decimal("1000"))
        for index in range(count)
    )


def test_catalogue_has_four_versioned_proposal_strategies() -> None:
    assert {item.strategy_id for item in catalogue()} == {
        "channel_mean_reversion", "liquidity_sweep_reversal", "moving_average_trend", "buy_and_hold"
    }
    assert all(item.version and item.execution_assumption for item in catalogue())


def test_signals_are_close_only_and_benchmark_buys_first_observation() -> None:
    spec = StrategySpec("buy_and_hold", "1.0.0", (), holding_period_min=1, holding_period_max=100)
    signals = generate_signals(spec, bars())
    assert signals[date(2025, 1, 1)] == "BUY"
    assert set(signals.values()) <= {"BUY", "SELL", "HOLD"}


def test_short_history_is_insufficient_not_profitable() -> None:
    result = evaluate_strategy(catalogue()[-1], bars(), EvaluationConfig(min_observations=100))
    assert result["status"] == "INSUFFICIENT_DATA"
    assert result["broker_execution"] == "DISABLED"


def test_parameter_surface_does_not_select_a_winner() -> None:
    result = parameter_surface(catalogue()[0], bars(), {"lookback": ("5", "10"), "entry_bps": ("100", "200")})
    assert len(result["cells"]) == 4
    assert result["selection"] == "NOT_SELECTED"


def test_selection_declares_in_sample_only_and_locks_oos() -> None:
    result = select_on_training(catalogue()[-2:], bars(), EvaluationConfig(min_observations=20))
    assert result["selection_basis"] == "IN_SAMPLE_ONLY"
    assert result["locked_oos"] is True


def test_walk_forward_keeps_test_windows_chronological() -> None:
    result = walk_forward_evaluate(catalogue()[-1], bars(30), train_size=10, test_size=5,
                                    config=EvaluationConfig(min_observations=10))
    assert result["windows"][0]["test_start"] < result["windows"][1]["test_start"]
    assert result["selection"] == "NO_PARAMETER_SELECTED"


def test_acceptance_report_is_insufficient_for_short_real_history() -> None:
    evaluation = evaluate_strategy(catalogue()[-1], bars(), EvaluationConfig(min_observations=20))
    report = acceptance_report(evaluation, minimum_observations=100)
    assert report["status"] == "INSUFFICIENT_DATA"
    assert report["genuine_profitability"] == "NOT_ESTABLISHED"


def test_portfolio_requires_aligned_series_and_preserves_controls() -> None:
    first = evaluate_strategy(catalogue()[-1], bars(), EvaluationConfig(min_observations=20))
    second = evaluate_strategy(catalogue()[-1], bars(), EvaluationConfig(min_observations=20))
    result = simulate_portfolio({"a": first, "b": second})
    assert result["weights"] == {"a": "0.5", "b": "0.5"}
    assert result["max_correlation"] == "0.70"
    assert result["broker_execution"] == "DISABLED"


def test_invalid_bars_and_portfolio_controls_fail_closed() -> None:
    duplicate = bars() + (bars()[0],)
    with pytest.raises(StrategyResearchError, match="duplicate"):
        generate_signals(catalogue()[-1], duplicate)
    with pytest.raises(StrategyResearchError, match="invalid portfolio"):
        simulate_portfolio({}, max_correlation=Decimal("1.2"))
