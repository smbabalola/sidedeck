import json
import sqlite3
from datetime import datetime, timezone

import pytest

from sidedeck.application.p5_demo_dashboard_api import (
    baseline_summary, dashboard_summary, research_summary, strategy_catalogue_summary,
    strategy_validation_summary,
)


def test_read_only_saved_baseline_summary(tmp_path):
    path = tmp_path / "demo.sqlite3"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE etoro_demo_baseline_capture (capture_id INTEGER, captured_at TEXT, position_count INTEGER)")
    db.execute("CREATE TABLE etoro_demo_baseline (position_id INTEGER)")
    db.execute("INSERT INTO etoro_demo_baseline_capture VALUES (1, ?, 2)",
               (datetime.now(timezone.utc).isoformat(),))
    db.executemany("INSERT INTO etoro_demo_baseline VALUES (?)", [(11,), (12,)])
    db.commit()
    db.close()
    result = dashboard_summary(str(path))
    assert result["protected_positions"] == 2
    assert result["reconciliation_status"] == "NOT_CURRENT"
    assert result["discrepancy_count"] is None
    assert result["available_cash_usd_status"] == "UNAVAILABLE"
    assert result["execution_enabled"] is False
    # Check structured exposure, not digit substrings that may appear in timestamps.
    # The browser receives counts and status only; raw broker identifiers stay in SQLite.
    assert set(result) == {
        "schema_version", "source", "baseline_status", "captured_at",
        "protected_positions", "reconciliation_status", "discrepancy_count",
        "available_cash_usd_status", "unrealized_pnl_status",
        "execution_enabled", "books", "fresh_snapshot",
    }
    assert all(set(book) == {"id", "positions", "allocation_status"} for book in result["books"])
    assert result["books"][2]["positions"] == 2
    assert result["books"][0]["positions"] is None


def test_mismatched_baseline_fails_closed(tmp_path):
    path = tmp_path / "demo.sqlite3"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE etoro_demo_baseline_capture (capture_id INTEGER, captured_at TEXT, position_count INTEGER)")
    db.execute("CREATE TABLE etoro_demo_baseline (position_id INTEGER)")
    db.execute("INSERT INTO etoro_demo_baseline_capture VALUES (1, ?, 4)",
               (datetime.now(timezone.utc).isoformat(),))
    db.commit()
    db.close()
    with pytest.raises(ValueError, match="count mismatch"):
        baseline_summary(str(path))


def test_missing_database_is_not_created(tmp_path):
    path = tmp_path / "missing.sqlite3"
    with pytest.raises(FileNotFoundError):
        baseline_summary(str(path))
    assert not path.exists()


def test_research_summary_is_sanitized_and_fail_closed(tmp_path):
    path = tmp_path / "research.json"
    path.write_text('{"schema_version":1,"execution_enabled":false,"status":"READY_OFFLINE",'
                    '"valuation":"PENDING","agents":[{"id":"tradingagents",'
                    '"status":"VERIFIED_OFFLINE","evidence_count":2}],"api_key":"secret"}',
                    encoding="utf-8")
    result = research_summary(str(path))
    assert result["status"] == "READY_OFFLINE"
    assert result["agents"] == [{"id": "tradingagents", "status": "VERIFIED_OFFLINE", "evidence_count": 2}]
    assert "api_key" not in result and "secret" not in str(result)
    assert research_summary(str(tmp_path / "missing.json"))["status"] == "BLOCKED"


def test_strategy_catalogue_is_read_only_and_versioned():
    result = strategy_catalogue_summary()
    assert result["execution_enabled"] is False
    assert {item["id"] for item in result["strategies"]} == {
        "channel_mean_reversion", "liquidity_sweep_reversal", "moving_average_trend", "buy_and_hold"
    }
    assert all(item["acceptance"] == "NOT_ASSESSED" for item in result["strategies"])


def test_strategy_validation_summary_is_sanitized_and_read_only(tmp_path):
    path = tmp_path / "research.json"
    path.write_text(json.dumps({
        "schema_version": 1, "broker_execution": "DISABLED", "ticker": "SPY",
        "instrument_id": "US:SPY", "source_bundle_sha256": "abc",
        "data": {"start": "2021-10-21", "end": "2026-10-20", "observations": 1254,
                 "provenance": "alpaca_market_data_api", "feed": "sip", "adjustment": "split_adjusted"},
        "strategies": {"channel_mean_reversion": {"metrics": {"trade_count": 122,
                       "round_trip_count": 61, "profit_factor": "1.5"}}},
        "acceptance": {"channel_mean_reversion": {"status": "VERIFIED"}},
        "portfolio": {"ending_equity": "1.2", "max_drawdown": "0.1", "correlation_status": "VERIFIED"},
        "equity_path_secret": "must not appear",
    }), encoding="utf-8")
    result = strategy_validation_summary((str(path),))
    assert result["status"] == "RESEARCH_ONLY"
    assert result["datasets"][0]["strategies"][0]["status"] == "VERIFIED"


def test_strategy_validation_summary_exposes_benchmark_convention_not_fake_total_return(tmp_path):
    research = tmp_path / "research.json"
    research.write_text(json.dumps({
        "schema_version": 1, "broker_execution": "DISABLED", "ticker": "SPY",
        "instrument_id": "US:SPY", "data": {"start": "2021-10-21", "end": "2026-10-20",
        "observations": 1254, "provenance": "alpaca_market_data_api", "feed": "sip", "adjustment": "split_adjusted"},
        "strategies": {}, "acceptance": {}, "portfolio": {},
    }), encoding="utf-8")
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({
        "ticker": "SPY", "broker_execution": "DISABLED",
        "benchmark": {"convention": "close_to_close_price_only_no_dividend_reinvestment",
                      "total_return": "UNAVAILABLE", "ending_equity": "1.2", "return": "0.2", "max_drawdown": "0.1"},
        "corporate_action_status": "NOT_ASSESSED",
    }), encoding="utf-8")
    result = strategy_validation_summary((str(research),), (str(audit),))
    benchmark = result["datasets"][0]["benchmark"]
    assert benchmark["convention"].startswith("close_to_close")
    assert benchmark["total_return"] == "UNAVAILABLE"
    assert benchmark["corporate_action_status"] == "NOT_ASSESSED"
    assert "equity_path_secret" not in str(result)
    assert result["execution_enabled"] is False
