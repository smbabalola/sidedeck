import json
from datetime import date

from sidedeck.application.p5_sd021_research import run_bundle
from sidedeck.application.us_equity_calendar import expected_regular_sessions


def test_sd021_research_runs_all_strategies_and_keeps_broker_disabled(tmp_path):
    sessions = expected_regular_sessions(date(2021, 10, 21), date(2026, 10, 20))
    records = []
    for index, day in enumerate(sessions):
        close = 100 + (index % 37) * 0.1
        records.append({"date": day.isoformat(), "timestamp": day.isoformat() + "T20:00:00Z",
                        "open": str(close), "high": str(close + 1), "low": str(close - 1),
                        "close": str(close), "volume": "1000", "source_id": "fixture:" + day.isoformat()})
    payload = {"ticker": "QQQ", "instrument_id": "US:QQQ", "exchange": "NASDAQ", "currency": "USD",
               "session": "REGULAR", "feed": "sip", "adjustment": "split_adjusted",
               "source": "fixture", "source_identity": "fixture", "records": records,
               "source_bundle_sha256": "fixture"}
    path = tmp_path / "qqq.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = run_bundle(path)
    assert set(result["strategies"]) == {"channel_mean_reversion", "liquidity_sweep_reversal",
                                          "moving_average_trend", "buy_and_hold"}
    assert result["data"]["observations"] == 1254
    assert all(item["selection_basis"] == "IN_SAMPLE_ONLY"
               for item in result["training_selection"].values())
    assert result["portfolio"]["broker_execution"] == "DISABLED"
    assert all(report["status"] in {"INSUFFICIENT_DATA", "REJECTED", "VERIFIED"}
               for report in result["acceptance"].values())
