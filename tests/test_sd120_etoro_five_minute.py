import json
from datetime import UTC, datetime
from urllib.error import HTTPError

from sidedeck.application.sd077_data_authorization import DataRequestLedger
from sidedeck.application.sd120_etoro_five_minute import (
    SAMPLE_FROM,
    SAMPLE_TO,
    draft_authorization,
    run_discovery,
)


class Response:
    status = 200

    def __init__(self, payload):
        self._raw = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _limit):
        return self._raw


def test_signed_scope_binds_window_symbols_credentials_and_endpoints():
    auth = draft_authorization(datetime(2026, 10, 26, tzinfo=UTC), owner_terms_reviewed=True)
    assert auth.max_requests == 9 and auth.max_retries == 0
    assert auth.scope["symbols"] == ["SPY", "QQQ", "MSFT"]
    assert auth.scope["from"] == SAMPLE_FROM and auth.scope["to"] == SAMPLE_TO
    assert auth.scope["credential_source"] == {
        "api_key_env": "ETORO_API_KEY", "user_key_env": "ETORO_USER_KEY"
    }
    assert any("{instrumentId}" in url for url in auth.urls)


def test_offline_collector_uses_nine_gets_and_skips_no_coverage(tmp_path):
    ids = {"SPY": 1001, "QQQ": 1002, "MSFT": 1003}
    seen = []

    def opener(request, timeout=20):
        del timeout
        from urllib.parse import parse_qs, urlsplit
        parsed = urlsplit(request.full_url)
        query = parse_qs(parsed.query)
        seen.append((parsed.path, query))
        if parsed.path.endswith("/market-data/search"):
            symbol = query["internalSymbolFull"][0]
            return Response({"results": [{"internalSymbolFull": symbol, "instrumentId": ids[symbol]}]})
        if parsed.path.endswith("/coverage"):
            instrument_id = int(parsed.path.split("/")[-3])
            symbol = next(symbol for symbol, value in ids.items() if value == instrument_id)
            return Response({"instrumentId": instrument_id, "symbol": symbol, "intervals": [
                {"interval": "5m", "firstCandle": SAMPLE_FROM, "lastCandle": SAMPLE_TO,
                 "candles": 12, "loadedAt": "2026-10-26T00:00:00Z"}
            ]})
        instrument_id = int(parsed.path.split("/")[-2])
        symbol = next(symbol for symbol, value in ids.items() if value == instrument_id)
        row = {"time": "2026-10-23T14:55:00Z", "bid": {
            "open": "100", "high": "101", "low": "99", "close": "100.5"}, "ask": {
            "open": "100.1", "high": "101.1", "low": "99.1", "close": "100.6"}}
        return Response({"instrumentId": instrument_id, "symbol": symbol + "/USD",
                         "interval": "5m", "side": "both", "results": [row]})

    auth = draft_authorization(datetime(2026, 10, 26, tzinfo=UTC), owner_terms_reviewed=True)
    report = run_discovery(auth, DataRequestLedger(tmp_path / "ledger.sqlite3", auth),
                           api_key="redacted", user_key="redacted", out_dir=tmp_path / "out",
                           opener=opener, now=lambda: datetime(2026, 10, 26, tzinfo=UTC))
    assert report["requests_used"] == 9
    assert len(seen) == 9
    assert all(query.get("interval", ["5m"])[0] == "5m" for _, query in seen[6:])
    assert all(query.get("side", ["both"])[0] == "both" for _, query in seen[6:])
    assert all(query.get("from", [SAMPLE_FROM])[0] == SAMPLE_FROM for _, query in seen[6:])
    assert all(query.get("to", [SAMPLE_TO])[0] == SAMPLE_TO for _, query in seen[6:])


def test_http_status_is_classified_and_stops_before_repeating_failure(tmp_path):
    calls = []

    def opener(request, timeout=20):
        del timeout
        calls.append(request.full_url)
        raise HTTPError(request.full_url, 403, "forbidden", {}, None)

    auth = draft_authorization(datetime(2026, 10, 26, tzinfo=UTC), owner_terms_reviewed=True)
    report = run_discovery(auth, DataRequestLedger(tmp_path / "ledger.sqlite3", auth),
                           api_key="redacted", user_key="redacted", out_dir=tmp_path / "out",
                           opener=opener, now=lambda: datetime(2026, 10, 26, tzinfo=UTC))
    assert len(calls) == 1 and report["requests_used"] == 1
    assert report["stopped_early"] == {
        "symbol": "SPY", "status": 403, "classification": "ACCESS_OR_ENTITLEMENT_DENIED"
    }
    assert report["records"][0]["status"] == 403
    assert report["records"][0]["classification"] == "ACCESS_OR_ENTITLEMENT_DENIED"
    assert [row["status"] for row in report["records"][1:]] == ["SKIPPED", "SKIPPED"]
