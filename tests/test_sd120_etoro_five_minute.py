import json
from datetime import UTC, datetime
from urllib.error import HTTPError

from sidedeck.application.sd077_data_authorization import DataRequestLedger
from sidedeck.application.sd120_etoro_five_minute import (
    SAMPLE_FROM,
    SAMPLE_TO,
    check_diagnostic_scope,
    draft_authorization,
    draft_diagnostic_authorization,
    run_diagnostic,
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


def test_single_aapl_diagnostic_is_distinct_and_exactly_one_get(tmp_path):
    auth = draft_diagnostic_authorization(datetime(2026, 10, 26, tzinfo=UTC), owner_terms_reviewed=True)
    check_diagnostic_scope(auth, api_key_env="ETORO_API_KEY", user_key_env="ETORO_USER_KEY")
    assert auth.max_requests == 1 and auth.max_retries == 0
    assert auth.scope["symbol"] == "AAPL"
    assert auth.urls == ("https://public-api.etoro.com/api/v1/market-data/search",)

    calls = []

    def opener(request, timeout=20):
        del timeout
        calls.append((request.full_url, request.get_method(), request.headers))
        return Response({"results": [{"internalSymbolFull": "AAPL", "instrumentId": 9999}]})

    report = run_diagnostic(
        auth, DataRequestLedger(tmp_path / "ledger.sqlite3", auth),
        api_key="redacted", user_key="redacted", out_dir=tmp_path / "out",
        opener=opener, now=lambda: datetime(2026, 10, 26, tzinfo=UTC),
    )
    assert len(calls) == 1
    assert calls[0][0].endswith("internalSymbolFull=AAPL")
    assert calls[0][1] == "GET"
    assert report["status"] == 200
    assert report["classification"] == "SUCCESS"
    assert report["schema_result"] == "VALID_SEARCH_RESPONSE"
    assert report["result_count"] == 1
    assert report["response_sha256"] and "9999" not in json.dumps(report)


def test_single_aapl_diagnostic_records_numeric_http_failure_without_body(tmp_path):
    calls = []

    def opener(request, timeout=20):
        del timeout
        calls.append(request.full_url)
        raise HTTPError(request.full_url, 403, "forbidden", {"X-Secret": "do-not-record"}, None)

    auth = draft_diagnostic_authorization(datetime(2026, 10, 26, tzinfo=UTC), owner_terms_reviewed=True)
    report = run_diagnostic(
        auth, DataRequestLedger(tmp_path / "ledger.sqlite3", auth),
        api_key="redacted", user_key="redacted", out_dir=tmp_path / "out",
        opener=opener, now=lambda: datetime(2026, 10, 26, tzinfo=UTC),
    )
    assert len(calls) == 1 and report["requests_used"] == 1
    assert report["status"] == 403
    assert report["classification"] == "ACCESS_OR_ENTITLEMENT_DENIED"
    assert report["response_sha256"] is None
    assert "X-Secret" not in json.dumps(report)


def test_single_aapl_diagnostic_persists_sanitized_urlerror_without_retry(tmp_path):
    """Network errors consume exactly one GET budget and never invent an HTTP status."""
    from urllib.error import URLError

    auth = draft_diagnostic_authorization(
        datetime(2026, 10, 26, tzinfo=UTC), owner_terms_reviewed=True,
        api_key_env="ETORO_DEMO_TRADE_API_KEY",
        user_key_env="ETORO_DEMO_TRADE_USER_KEY",
    )
    ledger = DataRequestLedger(tmp_path / "budget.sqlite3", auth)
    count = 0

    def opener(request, timeout=20):
        nonlocal count
        del request, timeout
        count += 1
        raise URLError("token=secret-must-not-leak: proxy refused")

    report = run_diagnostic(
        auth, ledger, api_key="hidden_api", user_key="hidden_user",
        api_key_env="ETORO_DEMO_TRADE_API_KEY",
        user_key_env="ETORO_DEMO_TRADE_USER_KEY",
        out_dir=tmp_path / "diagnostic", opener=opener,
        now=lambda: datetime(2026, 10, 26, tzinfo=UTC),
    )
    assert count == 1
    assert ledger.used() == 1
    assert report["requests_used"] == 1
    assert report["status"] is None
    assert report["classification"] == "NETWORK_TRANSPORT_ERROR"
    persisted = (tmp_path / "diagnostic" / "summary.json").read_text()
    assert "NETWORK_TRANSPORT_ERROR" in persisted
    assert "token=" not in persisted
    assert "hidden_" not in persisted
    assert "secret-must-not-leak" not in persisted
    assert "HTTP_200" not in persisted
