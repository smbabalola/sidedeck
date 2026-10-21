import json
import sqlite3

import pytest

from sidedeck.application.sd034_alpaca_one_shot import OneShotError, _schema_summary, _reserve, request_once


def test_sanitized_summaries_withhold_account_and_order_identifiers():
    account = _schema_summary("/v2/account", 200, {"id": "secret", "status": "ACTIVE", "currency": "USD", "cash": "1000"})
    positions = _schema_summary("/v2/positions", 200, [{"id": "position-secret", "symbol": "SPY", "qty": "2"}])
    orders = _schema_summary("/v2/orders", 200, [{"id": "order-secret", "status": "open"}])
    assert account["identity"] == "PRESENT_BUT_WITHHELD"
    assert positions["position_count"] == 1 and positions["ownership"] == "UNRESOLVED"
    assert orders["open_or_unresolved"] is True
    assert "secret" not in json.dumps((account, positions, orders))


def test_budget_is_atomic_and_one_attempt_per_endpoint(tmp_path):
    path = str(tmp_path / "budget.sqlite3")
    _reserve(path, "/v2/account")
    with pytest.raises(OneShotError, match="exhausted"):
        _reserve(path, "/v2/account")
    _reserve(path, "/v2/positions")
    _reserve(path, "/v2/orders")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT attempts FROM sd034_total WHERE singleton=1").fetchone()[0] == 3
    with pytest.raises(OneShotError, match="exhausted"):
        _reserve(path, "/v2/orders")


def test_request_once_fails_closed_without_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    result = request_once("/v2/account", budget_path=str(tmp_path / "budget.sqlite3"))
    assert result["failure"] == "CREDENTIALS_UNAVAILABLE"
    assert result["account_separation"] == "UNVERIFIED"
