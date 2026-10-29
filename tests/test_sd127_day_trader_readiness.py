"""Read-only readiness is a code-status report, never a live account check."""
import io
import json
from unittest.mock import Mock

import pytest

from sidedeck.application import sd127_day_trader_readiness as readiness
from sidedeck.application.p5_demo_dashboard_api import make_handler


def test_day_trader_readiness_is_fail_closed_and_contains_no_secrets(monkeypatch):
    d = readiness.day_trader_readiness()
    assert d["module"] == "DAY_TRADER"
    assert d["source"] == "CODE_DERIVED_OFFLINE"
    assert d["execution_enabled"] is False
    assert d["broker_execution"] == "DISABLED"
    assert d["demo_release"] == "NOT_RELEASED"
    assert d["real_execution"] == "PERMANENTLY_EXCLUDED"
    assert [g["id"] for g in d["gates"]] == [
        "research", "market_data", "strategy", "offline_cycle", "broker",
    ]
    assert [g["status"] for g in d["gates"]] == [
        "IMPLEMENTED_OFFLINE", "BLOCKED_EXTERNAL", "BLOCKED_EXTERNAL",
        "IMPLEMENTED_OFFLINE", "NOT_RELEASED",
    ]
    text = json.dumps(d).lower()
    assert "etoro_api_key" not in text
    assert "etoro_user_key" not in text
    assert "positionid" not in text
    assert "broker_execution" in text

    monkeypatch.setattr(readiness, "BROKER_ROUTES", {"ETORO_DEMO": "RELEASED"})
    with pytest.raises(ValueError, match="release state differs"):
        readiness.day_trader_readiness()


def test_local_readiness_http_route_is_get_only_without_database(tmp_path):
    handler_type = make_handler(str(tmp_path / "missing-baseline.sqlite3"))
    h = handler_type.__new__(handler_type)
    h.headers = {"Host": "127.0.0.1:8765"}
    h.path = "/api/day-trader/readiness"
    h.wfile = io.BytesIO()
    h.send_error = Mock()
    h.send_response = Mock()
    h.send_header = Mock()
    h.end_headers = Mock()

    h.do_GET()
    h.send_response.assert_called_once_with(200)
    result = json.loads(h.wfile.getvalue())
    assert result["demo_release"] == "NOT_RELEASED"
    assert result["execution_enabled"] is False
    assert not (tmp_path / "missing-baseline.sqlite3").exists()

    h.path = "/api/day-trader/readiness?unsafe=1"
    h.send_error.reset_mock()
    h.do_GET()
    h.send_error.assert_called_once_with(404)
