import json
from datetime import datetime, timedelta, timezone

from sidedeck.application.p5_demo_dashboard_api import read_refresh


def snapshot(t):
    return {
        "schema_version": 1, "source": "OWNER_AUTHORIZED_DEMO_READ",
        "execution_enabled": False, "observed_at": t.isoformat(),
        "reconciliation_status": "MATCHED", "discrepancy_count": 0,
        "available_cash_usd_status": "AVAILABLE", "unrealized_pnl_status": "AVAILABLE",
        "books": [
            {"id": "etoro-demo:tradingagents", "positions": 0},
            {"id": "etoro-demo:ai-trading", "positions": 0},
            {"id": "etoro-demo:unattributed", "positions": 4},
        ],
    }


def test_fresh_snapshot_is_allowlisted(tmp_path):
    now = datetime.now(timezone.utc)
    path = tmp_path / "sanitized.json"
    doc = snapshot(now)
    doc["private_key"] = "SHOULD_NOT_LEAK"
    path.write_text(json.dumps(doc), encoding="utf-8")
    result = read_refresh(str(path), now=now)
    assert result is not None
    assert result["books"][2]["positions"] == 4
    assert "private_key" not in result
    assert "SHOULD_NOT_LEAK" not in str(result)


def test_snapshot_expires_and_future_is_refused(tmp_path):
    now = datetime.now(timezone.utc)
    path = tmp_path / "sanitized.json"
    path.write_text(json.dumps(snapshot(now - timedelta(minutes=6))), encoding="utf-8")
    assert read_refresh(str(path), now=now) is None
    path.write_text(json.dumps(snapshot(now + timedelta(seconds=1))), encoding="utf-8")
    assert read_refresh(str(path), now=now) is None


def test_snapshot_does_not_accept_execution(tmp_path):
    now = datetime.now(timezone.utc)
    path = tmp_path / "sanitized.json"
    data = snapshot(now)
    data["execution_enabled"] = True
    path.write_text(json.dumps(data), encoding="utf-8")
    assert read_refresh(str(path), now=now) is None
