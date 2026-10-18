from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest

from sidedeck.domain.etoro import (
    MAX_DAILY_CANDLES,
    EtoroAccessBlocked,
    EtoroDataError,
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


def candle(ts):
    return {"timestamp": ts.isoformat(), "open": "100", "high": "105", "low": "99", "close": "102", "volume": "1000", "complete": True}


def test_resolution_is_exact_and_daily_limit_is_clamped():
    transport = FakeTransport({"data": [{"instrumentId": 1001, "symbol": "AAPL", "assetType": "EQUITY", "exchange": "NASDAQ", "currency": "USD"}]})
    found = client(transport).resolve_instrument("AAPL")
    assert found.instrument_id == 1001
    candles = client(FakeTransport({"data": {"candles": [candle(datetime(2026, 1, 2, tzinfo=timezone.utc))]}})).fetch_daily_candles(found, limit=5000, cutoff=datetime(2026, 1, 3, tzinfo=timezone.utc))
    assert len(candles) == 1
    assert transport.calls[0][1] == {"search": "AAPL"}


def test_coverage_does_not_claim_five_years_from_1000_bars():
    cutoff = datetime(2026, 1, 5, tzinfo=timezone.utc)
    candles = tuple(
        __import__("sidedeck.domain.etoro", fromlist=["EtoroCandle"]).EtoroCandle(
            cutoff - timedelta(days=index), Decimal("100"), Decimal("105"), Decimal("99"), Decimal("102"), Decimal("1000")
        ) for index in range(1000)
    )
    report = client(FakeTransport({})).scan_five_year_daily(instrument(), cutoff=cutoff, candles=candles)
    assert report.status == "INSUFFICIENT_DEPTH"
    assert report.candle_count == 1000
    assert report.earliest is not None


@pytest.mark.parametrize("payload", [
    {"data": [{"instrumentId": 1001, "symbol": "AAPL"}, {"instrumentId": 1002, "symbol": "AAPL"}]},
    {"data": [{"instrumentId": 1001, "symbol": "AAPL", "assetType": "CFD"}]},
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
            client(FakeTransport({"data": {"candles": [bad]}})).fetch_daily_candles(instrument(), cutoff=cutoff)
    with pytest.raises(EtoroAccessBlocked):
        client(FakeTransport({}, status=403)).resolve_instrument("AAPL")


def test_retry_only_repeats_429_with_same_request_id():
    class RateLimited(FakeTransport):
        def __init__(self):
            super().__init__({"data": [{"instrumentId": 1001, "symbol": "AAPL", "assetType": "EQUITY", "exchange": "NASDAQ", "currency": "USD"}]})
            self.statuses = [429, 200]

        def get(self, path, params, request_id):
            self.calls.append((path, dict(params), request_id))
            return self.statuses.pop(0), {}, json.dumps(self.payload).encode()

    transport = RateLimited()
    assert client(transport).resolve_instrument("AAPL").ticker == "AAPL"
    assert len(transport.calls) == 2
    assert transport.calls[0][2] == transport.calls[1][2]
    assert all("trading" not in call[0] and "order" not in call[0] for call in transport.calls)


def test_request_limit_constant_is_conservative():
    assert MAX_DAILY_CANDLES == 1000
