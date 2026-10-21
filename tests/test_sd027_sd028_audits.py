from __future__ import annotations

import json
from pathlib import Path

from sidedeck.application.sd027_paper_readiness_audit import audit_paper_release_controls
from sidedeck.application.sd028_portfolio_economics import audit_joint_portfolio


def _bundle(path: Path, ticker: str, prices: list[str]) -> None:
    path.write_text(json.dumps({
        "ticker": ticker, "adjustment": "split", "feed": "sip", "broker_execution": "DISABLED",
        "records": [{"date": f"2024-01-{day:02d}", "close": price} for day, price in enumerate(prices, 1)],
    }), encoding="utf-8")


def test_paper_readiness_is_no_go_even_with_some_safe_controls() -> None:
    result = audit_paper_release_controls()
    assert result["overall_status"] == "NO_GO"
    assert result["release_enabled"] is False
    assert result["paper_order_submission"] == "DISABLED"
    assert "approval_signature" in result["blocking_checks"]
    assert "account_separation" in result["blocking_checks"]


def test_joint_portfolio_is_deterministic_and_segregated(tmp_path: Path) -> None:
    spy, qqq = tmp_path / "spy.json", tmp_path / "qqq.json"
    _bundle(spy, "SPY", ["100", "102", "101", "104"])
    _bundle(qqq, "QQQ", ["200", "202", "204", "203"])
    result = audit_joint_portfolio(spy, qqq)
    assert result["overlap_status"] == "VERIFIED"
    assert result["weights"] == {"SPY": "0.50", "QQQ": "0.50"}
    assert result["cash_weight"] == "0.00"
    assert result["max_concentration"] == "0.50"
    assert result["broker_execution"] == "DISABLED"
    assert result["transaction_costs"].startswith("NOT_APPLIED")
