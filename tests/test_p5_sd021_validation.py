import json
from datetime import date

from sidedeck.application.p5_sd021_validation import validate_bundle
from sidedeck.application.us_equity_calendar import expected_regular_sessions


def _bundle(ticker="SPY"):
    sessions = expected_regular_sessions(date(2021, 10, 21), date(2026, 10, 20))
    return {
        "ticker": ticker, "instrument_id": "US:" + ticker, "exchange": "NASDAQ",
        "currency": "USD", "session": "REGULAR", "feed": "sip", "adjustment": "split",
        "source": "https://data.alpaca.markets/v2/stocks/" + ticker + "/bars",
        "source_identity": "alpaca_market_data_api", "research_only": True,
        "http_statuses": [200], "request_count": 1, "pagination_pages": 1,
        "records": [{"date": day.isoformat(), "timestamp": day.isoformat() + "T20:00:00Z",
                     "open": "100", "high": "101", "low": "99", "close": "100", "volume": "1000",
                     "source_id": "alpaca:1Day:" + day.isoformat()} for day in sessions],
    }


def test_sd021_admits_complete_bundle_and_records_exchange_correction(tmp_path):
    path = tmp_path / "spy.json"
    path.write_text(json.dumps(_bundle()), encoding="utf-8")
    admitted, report = validate_bundle(path, ticker="SPY")
    assert report["status"] == "ADMITTED_RESEARCH_ONLY"
    assert report["observations"] == 1254
    assert admitted["exchange"] == "NYSE_ARCA"
    assert report["metadata_corrections"] == ["EXCHANGE_IDENTITY_NORMALIZED_FROM_RETRIEVAL_METADATA"]


def test_sd021_rejects_missing_session(tmp_path):
    payload = _bundle("MSFT")
    payload["records"].pop(20)
    path = tmp_path / "msft.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    _, report = validate_bundle(path, ticker="MSFT")
    assert report["status"] == "REJECTED"
    assert "SESSION_COVERAGE" in report["fatal_issues"]
