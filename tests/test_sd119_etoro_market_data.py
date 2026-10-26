from sidedeck.application.sd119_etoro_market_data import (
    EtoroMarketDataError,
    parse_candles,
    parse_coverage,
    parse_instrument_search,
    provenance,
    request_plan,
)


def test_request_plan_is_bounded_and_has_no_transport():
    plan = request_plan()
    assert len(plan) == 9
    assert all(item.requires_owner_authorization for item in plan)
    assert sum(item.purpose == "instrument discovery" for item in plan) == 3
    assert sum(item.purpose == "five-minute coverage" for item in plan) == 3
    assert sum(item.purpose == "bounded five-minute sample" for item in plan) == 3


def test_fixture_contract_parses_exact_identity_and_provenance():
    search = {"results": [{"internalSymbolFull": "SPY", "instrumentId": 1001}]}
    coverage = {"instrumentId": 1001, "symbol": "SPY", "intervals": [{
        "interval": "5m", "firstCandle": "2026-01-01T14:30:00Z",
        "lastCandle": "2026-01-01T21:00:00Z", "candles": 78,
        "loadedAt": "2026-01-02T07:30:00Z",
    }]}
    candles = {"instrumentId": 1001, "symbol": "SPY", "interval": "5m", "side": "both", "results": [
        {"time": "2026-01-01T14:30:00Z", "open": "100", "high": "101", "low": "99", "close": "100.5", "volume": "10"},
        {"time": "2026-01-01T14:35:00Z", "open": "100.5", "high": "102", "low": "100", "close": "101", "volume": "11"},
    ]}
    assert parse_instrument_search(search, "SPY") == 1001
    assert parse_coverage(coverage, instrument_id=1001, symbol="SPY")["intervals"][0]["candles"] == 78
    assert len(parse_candles(candles, instrument_id=1001, symbol="SPY")) == 2
    assert provenance(candles)["evidence"] == "FIXTURE_ONLY_UNVERIFIED_ENTITLEMENT"


def test_fixture_contract_fails_closed_on_ambiguous_identity_and_bad_ohlc():
    try:
        parse_instrument_search({"results": [
            {"internalSymbolFull": "SPY", "instrumentId": 1001},
            {"internalSymbolFull": "SPY", "instrumentId": 1002},
        ]}, "SPY")
    except EtoroMarketDataError:
        pass
    else:
        raise AssertionError("ambiguous identity was accepted")
    try:
        parse_candles({"instrumentId": 1001, "symbol": "SPY", "interval": "5m", "side": "bid", "results": [
            {"time": "2026-01-01T14:30:00Z", "open": "100", "high": "99", "low": "98", "close": "98.5"},
        ]}, instrument_id=1001, symbol="SPY")
    except EtoroMarketDataError:
        pass
    else:
        raise AssertionError("inconsistent OHLC was accepted")
