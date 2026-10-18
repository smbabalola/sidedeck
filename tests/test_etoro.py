from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest

from sidedeck.domain.etoro import (
    MAX_DAILY_CANDLES,
    EtoroAccessBlocked,
    EtoroDataError,
    EtoroCandle,
    EtoroHistoricalDataClient,
    EtoroInstrument,
    MarketDataReadCapability,
)


class FakeTransport:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status
        self.calls = []

    def get(self, path, params, request_id):
        self.calls.append((path, dict(params), request_id))
        return self.status, {}, json.dumps(self.payload).encode()


def client(transport):
    return EtoroHistoricalDataClient(transport, capability=MarketDataReadCapability())


def instrument():
    return EtoroInstrument(1001, "AAPL", "EQUITY", "NASDAQ")


def candle(ts, instrument_id=1001):
    return {"instrumentID": instrument_id, "fromDate": ts.isoformat(), "open": "100", "high": "105", "low": "99", "close": "102", "volume": "0", "complete": True}


def search_payload():
    return {"items": [{"internalInstrumentId": 1001, "internalSymbolFull": "AAPL", "assetType": "EQUITY", "exchange": "NASDAQ", "currency": "USD", "isLeveraged": False, "isInverse": False}]}


def candle_payload(row):
    return {"interval": "OneDay", "candles": [{"instrumentId": 1001, "candles": [row]}]}


def test_resolution_is_exact_and_daily_limit_is_clamped():
    transport = FakeTransport(search_payload())
    found = client(transport).resolve_instrument("AAPL")
    assert found.instrument_id == 1001
    candles_transport = FakeTransport(candle_payload(candle(datetime(2026, 1, 2, tzinfo=timezone.utc))))
    candles = client(candles_transport).fetch_daily_candles(found, limit=5000, cutoff=datetime(2026, 1, 3, tzinfo=timezone.utc))
    assert len(candles) == 1
    assert candles[0].volume == Decimal("0")
    assert transport.calls[0][1] == {"internalSymbolFull": "AAPL"}
    assert candles_transport.calls[0][0].endswith("/backward/OneDay/1000")


def test_coverage_does_not_claim_five_years_from_1000_bars():
    cutoff = datetime(2026, 1, 5, tzinfo=timezone.utc)
    candles = tuple(
        EtoroCandle(
            cutoff - timedelta(days=index), Decimal("100"), Decimal("105"), Decimal("99"), Decimal("102"), Decimal("1000")
        ) for index in range(1000)
    )
    scanner = client(FakeTransport({}))
    assert scanner.scan_five_year_daily(instrument(), cutoff=cutoff, candles=candles).status == "UNVERIFIED"
    sessions = frozenset((cutoff - timedelta(days=index)).date() for index in range(1300) if (cutoff - timedelta(days=index)).weekday() < 5)
    report = scanner.scan_five_year_daily(instrument(), cutoff=cutoff, candles=candles, exchange_sessions=sessions)
    assert report.status == "INSUFFICIENT_DEPTH"
    assert report.candle_count == 1000
    assert report.earliest is not None


@pytest.mark.parametrize("payload", [
    {"items": [{"internalInstrumentId": 1001, "internalSymbolFull": "AAPL", "assetType": "EQUITY", "exchange": "NASDAQ", "currency": "USD"}, {"internalInstrumentId": 1002, "internalSymbolFull": "AAPL", "assetType": "EQUITY", "exchange": "NASDAQ", "currency": "USD"}]},
    {"items": [{"internalInstrumentId": 1001, "internalSymbolFull": "AAPL", "assetType": "CFD", "exchange": "NASDAQ", "currency": "USD"}]},
    {"items": [{"internalInstrumentId": 1001, "internalSymbolFull": "AAPL", "exchange": "NASDAQ", "currency": "USD"}]},
])
def test_instrument_resolution_fails_closed(payload):
    with pytest.raises(EtoroDataError):
        client(FakeTransport(payload)).resolve_instrument("AAPL")


def test_incomplete_future_bad_ohlc_and_auth_failures_are_rejected():
    cutoff = datetime(2026, 1, 5, tzinfo=timezone.utc)
    for bad in [
        candle(datetime(2026, 1, 6, tzinfo=timezone.utc)),
        {**candle(cutoff), "complete": False},
        {**candle(cutoff), "high": "98"},
    ]:
        with pytest.raises(EtoroDataError):
            client(FakeTransport(candle_payload(bad))).fetch_daily_candles(instrument(), cutoff=cutoff)
    with pytest.raises(EtoroAccessBlocked):
        client(FakeTransport({}, status=403)).resolve_instrument("AAPL")


def test_retry_only_repeats_429_with_same_request_id():
    class RateLimited(FakeTransport):
        def __init__(self):
            super().__init__(search_payload())
            self.statuses = [429, 200]

        def get(self, path, params, request_id):
            self.calls.append((path, dict(params), request_id))
            return self.statuses.pop(0), {}, json.dumps(search_payload()).encode()

    transport = RateLimited()
    assert client(transport).resolve_instrument("AAPL").ticker == "AAPL"
    assert len(transport.calls) == 2
    assert transport.calls[0][2] == transport.calls[1][2]
    assert all("trading" not in call[0] and "order" not in call[0] for call in transport.calls)


def test_request_limit_constant_is_conservative():
    assert MAX_DAILY_CANDLES == 1000
def test_nested_cross_instrument_and_allowlist_fail_closed():
    cutoff = datetime(2026, 1, 5, tzinfo=timezone.utc)
    cross = {"interval": "OneDay", "candles": [{"instrumentId": 999, "candles": []}]}
    with pytest.raises(EtoroDataError):
        client(FakeTransport(cross)).fetch_daily_candles(instrument(), cutoff=cutoff)
    transport = FakeTransport(search_payload())
    with pytest.raises(EtoroDataError):
        client(transport)._get("/trading/info/demo/portfolio", {})
    with pytest.raises(EtoroDataError):
        client(transport)._get("/market-data/../trading", {})


def test_leap_day_period_and_zero_volume_are_safe():
    cutoff = datetime(2028, 2, 29, tzinfo=timezone.utc)
    row = candle(datetime(2028, 2, 28, tzinfo=timezone.utc))
    parsed = client(FakeTransport(candle_payload(row))).fetch_daily_candles(instrument(), cutoff=cutoff)
    assert parsed[0].volume == Decimal("0")
    report = client(FakeTransport({})).scan_five_year_daily(instrument(), cutoff=cutoff, candles=parsed)
    assert report.status == "UNVERIFIED"
