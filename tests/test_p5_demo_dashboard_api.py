import sqlite3
from datetime import datetime, timezone

import pytest

from sidedeck.application.p5_demo_dashboard_api import baseline_summary, dashboard_summary, research_summary


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
