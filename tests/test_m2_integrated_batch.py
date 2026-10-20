from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from sidedeck.application.m2_backtest import BacktestConfig, run_backtest
from sidedeck.application.m2_market_data import MarketDataError, admit_valuation, normalize_daily_bars
from sidedeck.application.m2_research_run import ResearchRunBlocked, dry_run, plan_run, require_owner_authorization


def bars(**overrides):
    payload = {"instrument_id": "US:MSFT", "source": "fixture:validated-provider",
               "exchange": "NASDAQ", "session": "REGULAR", "currency": "USD",
               "adjustment": "split_adjusted", "records": [
                   {"timestamp": "2026-01-02T21:00:00+00:00", "open": "100", "high": "105", "low": "99", "close": "104", "volume": "100", "source_id": "a"},
                   {"timestamp": "2026-01-05T21:00:00+00:00", "open": "104", "high": "106", "low": "103", "close": "105", "volume": "110", "source_id": "b"},
               ]}
    payload.update(overrides)
    return payload


def test_market_normalization_and_valuation_gate():
    normalized, report = normalize_daily_bars(bars(), cutoff=datetime(2026, 1, 6, tzinfo=timezone.utc))
    assert report["status"] == "READY" and len(normalized) == 2
    value = admit_valuation(eps=Decimal("5"), shares=Decimal("10"), bar=normalized[-1],
                            market_report=report, shares_filed=date(2025, 12, 1), cutoff=date(2026, 1, 6))
    assert value["market_cap_usd"] == "1050" and value["pe"] == "21"


def test_market_data_rejects_future_duplicate_and_bad_range():
    with pytest.raises(MarketDataError):
        normalize_daily_bars(bars(records=[{**bars()["records"][0], "high": "98"}]),
                             cutoff=datetime(2026, 1, 6, tzinfo=timezone.utc))
    with pytest.raises(MarketDataError):
        normalize_daily_bars(bars(records=bars()["records"] * 2), cutoff=datetime(2026, 1, 6, tzinfo=timezone.utc))


def test_backtest_is_versioned_costed_and_split():
    result = run_backtest({date(2026, 1, 1): Decimal("100"), date(2026, 1, 2): Decimal("110"), date(2026, 1, 3): Decimal("105")},
                          {date(2026, 1, 2): "BUY", date(2026, 1, 3): "SELL"},
                          BacktestConfig("EXP-MSFT-001", "v1", Decimal("5"), Decimal("2"), date(2026, 1, 3)))
    assert result["status"] == "RESEARCH_ONLY" and result["trade_count"] == 2
    assert result["out_of_sample_days"] == 1 and result["broker_execution"] == "DISABLED"

    drawdown = run_backtest(
        {date(2026, 1, 1): Decimal("100"), date(2026, 1, 2): Decimal("110"), date(2026, 1, 3): Decimal("90")},
        {date(2026, 1, 2): "BUY"}, BacktestConfig("EXP-MSFT-002", "v1"),
    )
    assert Decimal(str(drawdown["max_drawdown"])) > 0


def test_research_run_dry_run_never_authorizes_provider():
    plan = plan_run("RUN-1", "US:MSFT", datetime(2026, 1, 1, tzinfo=timezone.utc), max_cost_usd="0")
    assert dry_run(plan)["provider_calls"] == 0
    with pytest.raises(ResearchRunBlocked):
        require_owner_authorization(plan, False)
