import json
from datetime import date

from sidedeck.application.p5_sd021_research import run_bundle
from sidedeck.application.sd022_robustness_audit import audit_bundle
from sidedeck.application.us_equity_calendar import expected_regular_sessions


def test_sd022_reclassifies_transaction_only_screen(tmp_path):
    sessions = expected_regular_sessions(date(2021, 10, 21), date(2026, 10, 20))
    records = [{"date": day.isoformat(), "timestamp": day.isoformat() + "T20:00:00Z",
                "open": str(100 + index), "high": str(102 + index), "low": str(99 + index),
                "close": str(100 + index),
                "volume": "1000", "source_id": "fixture:" + day.isoformat()}
               for index, day in enumerate(sessions)]
    payload = {"ticker": "SPY", "instrument_id": "US:SPY", "exchange": "NYSE_ARCA", "currency": "USD",
               "session": "REGULAR", "feed": "sip", "adjustment": "split_adjusted", "source": "fixture",
               "source_identity": "fixture", "records": records, "source_bundle_sha256": "fixture"}
    source = tmp_path / "bundle.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    research = tmp_path / "research.json"
    research.write_text(json.dumps(run_bundle(source)), encoding="utf-8")
    result = audit_bundle(research)
    assert result["strategies"]["moving_average_trend"]["metrics"]["completed_trade_count"] < 30
    assert result["strategies"]["moving_average_trend"]["audited_status"] == "INSUFFICIENT_DATA"
    assert result["strategies"]["moving_average_trend"]["selection_basis"] == "IN_SAMPLE_ONLY"
    assert "oos_profit_factor" in result["strategies"]["moving_average_trend"]["metrics"]
    assert result["portfolio"]["weights_sum"] in {"1", "1.00"}
