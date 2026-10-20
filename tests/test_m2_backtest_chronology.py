"""Backtest chronological acceptance: signal cannot profit on its own price bar."""
from datetime import date
from decimal import Decimal

from sidedeck.application.m2_backtest import BacktestConfig, run_backtest


def test_close_signal_is_applied_on_next_interval_not_earlier():
    days = [date(2026, 1, d) for d in (5, 6, 7, 8)]
    prices = dict(zip(days, map(Decimal, ("100", "200", "100", "110"))))
    report = run_backtest(prices, {days[1]: "BUY"}, BacktestConfig("lag-check", "v1"))
    assert report["signal_execution_lag"] == "NEXT_OBSERVED_PRICE_INTERVAL"
    assert report["results"][0]["equity"] == "1"
    # Buying on Jan 6 at 200 cannot earn Jan 5 -> Jan 6's +100%.
    assert report["results"][1]["equity"] == "0.5"
    assert report["broker_execution"] == "DISABLED"


def test_last_day_signal_never_receives_same_bar_return():
    days = [date(2026, 1, d) for d in (5, 6, 7)]
    report = run_backtest(
        {days[0]: Decimal("100"), days[1]: Decimal("200"), days[2]: Decimal("300")},
        {days[-1]: "BUY"}, BacktestConfig("last-day", "v1"),
    )
    assert report["trade_count"] == 0
    assert report["ending_equity"] == "1"
