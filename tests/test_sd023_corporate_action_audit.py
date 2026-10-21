from __future__ import annotations

import json
from pathlib import Path

from sidedeck.application.sd023_corporate_action_audit import audit_bundle


def _write_bundle(tmp_path: Path, ticker: str = "SPY") -> tuple[Path, Path]:
    bundle = tmp_path / f"{ticker}.json"
    bundle.write_text(json.dumps({
        "ticker": ticker, "instrument_id": f"US:{ticker}",
        "source_identity": "alpaca_market_data_api", "feed": "sip",
        "price_basis": "split_adjusted_close", "records": [
            {"date": "2021-10-21", "close": "100"},
            {"date": "2021-10-22", "close": "110"},
            {"date": "2021-10-25", "close": "105"},
        ],
    }), encoding="utf-8")
    research = tmp_path / f"{ticker}-research.json"
    research.write_text(json.dumps({"benchmark": {"ending_equity": "1.050000000000", "max_drawdown": "0.045454545455"}}), encoding="utf-8")
    return bundle, research


def test_audit_reconciles_price_only_benchmark_and_keeps_total_return_unavailable(tmp_path: Path) -> None:
    bundle, research = _write_bundle(tmp_path)
    result = audit_bundle(bundle, research_path=research)
    assert result["benchmark"]["ending_equity"] == "1.050000000000"
    assert result["benchmark"]["convention"] == "close_to_close_price_only_no_dividend_reinvestment"
    assert result["benchmark"]["total_return"] == "UNAVAILABLE"
    assert result["research_benchmark_reconciliation"]["status"] == "RECONCILED"
    assert result["corporate_action_status"] == "NOT_ASSESSED"
    assert result["valuation_admission"] == "BLOCKED_EXTERNAL"


def test_msft_window_uses_recorded_action_evidence(tmp_path: Path) -> None:
    bundle, _ = _write_bundle(tmp_path, "MSFT")
    result = audit_bundle(bundle)
    assert result["corporate_action_status"] == "VERIFIED"
    assert result["corporate_actions"]["split_in_window"] is False
    assert result["dividend_treatment"] == "EXCLUDED_FROM_CLOSE; NOT_TOTAL_RETURN"
