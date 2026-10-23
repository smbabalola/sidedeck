"""Regression tests for the pre-authorisation eToro probe safety boundaries.

No network calls, real account credentials, or broker APIs are used.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import sys

import pytest

from sidedeck import data_probe
from sidedeck.domain.etoro import (
    EtoroCandle, EtoroDataError, EtoroHistoricalDataClient,
    EtoroInstrument, MarketDataReadCapability, _validate_path,
)


def test_live_cutoff_excludes_current_utc_day_and_is_not_fixture_date() -> None:
    clock = datetime(2026, 10, 18, 16, 30, tzinfo=timezone.utc)
    cutoff = data_probe.completed_daily_cutoff(clock)
    assert cutoff.date().isoformat() == "2026-10-17"
    assert cutoff.hour == 23 and cutoff.minute == 59 and cutoff.second == 59
    assert cutoff < clock
    with pytest.raises(ValueError):
        data_probe.completed_daily_cutoff(datetime(2026, 10, 18, 16, 30))


def test_readonly_transport_rejects_ambiguous_and_unapproved_paths() -> None:
    _validate_path("/api/v2/market-data/instruments/search")
    _validate_path("/api/v1/market-data/instruments/1001/history/candles/desc/OneDay/1000")
    for bad in (
        "/api/v1/market-data/instruments/1001/history/candles/backward/OneDay/1000",
        "/api/v1/market-data/instruments/1001/history/candles/desc/OneDay/1001",
        "/api/v1/market-data/instruments/1001/../trading/history/candles/desc/OneDay/10",
        "/api/v1/market-data/instruments/abc/history/candles/desc/OneDay/10",
        "/api/v1/market-data/instruments/1001/history/candles/desc/OneDay/10/extra",
        "/trading/orders",
        "//other.example/market-data/search",
    ):
        with pytest.raises(EtoroDataError):
            _validate_path(bad)
        with pytest.raises(EtoroDataError):
            data_probe.UrllibReadOnlyTransport({}).get(bad, {}, __import__("uuid").uuid4())


def test_five_year_depth_is_insufficient_without_early_dates_and_unverified_without_calendar() -> None:
    class NoNetwork:
        def get(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("no network")

    client = EtoroHistoricalDataClient(NoNetwork(), capability=MarketDataReadCapability())  # type: ignore[arg-type]
    instrument = EtoroInstrument(1001, "AAPL", "EQUITY", "NASDAQ")
    cutoff = datetime(2026, 10, 17, tzinfo=timezone.utc)
    def candle(at: datetime) -> EtoroCandle:
        return EtoroCandle(at, Decimal("100"), Decimal("110"), Decimal("90"), Decimal("101"), Decimal("0"))
    recent = client.scan_five_year_daily(instrument, cutoff=cutoff, candles=(candle(cutoff),))
    assert recent.status == "INSUFFICIENT_DEPTH"
    older = client.scan_five_year_daily(
        instrument, cutoff=cutoff,
        candles=(candle(datetime(2021, 10, 16, tzinfo=timezone.utc)), candle(cutoff)),
    )
    assert older.status == "UNVERIFIED"
    assert "calendar" in older.reason


def test_live_probe_uses_dynamic_cutoff_and_never_fabricates_exchange_sessions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[tuple[datetime, object]] = []

    class MockClient:
        def __init__(self, transport: object, *, capability: object) -> None:
            pass

        def resolve_instrument(self, ticker: str) -> object:
            return SimpleNamespace(ticker=ticker)

        def fetch_daily_candles(self, instrument: object, *, cutoff: datetime) -> tuple[()]:
            assert cutoff.date().year == datetime.now(timezone.utc).year
            return ()

        def scan_five_year_daily(
            self, instrument: object, *, cutoff: datetime,
            candles: tuple[()], exchange_sessions: object,
        ) -> SimpleNamespace:
            seen.append((cutoff, exchange_sessions))
            return SimpleNamespace(ticker=instrument.ticker, status="UNVERIFIED")

    # Dummy in-memory test variables; no owner .env or actual network transport.
    monkeypatch.setenv("ETORO_API_KEY", "test-only-placeholder")
    monkeypatch.setenv("ETORO_USER_KEY", "test-only-placeholder")
    monkeypatch.setattr(data_probe, "UrllibReadOnlyTransport", lambda headers: object())
    monkeypatch.setattr(data_probe, "EtoroHistoricalDataClient", MockClient)
    monkeypatch.setattr(sys, "argv", [
        "data_probe", "--provider", "etoro", "--market-data-only",
        "--allow-read-network", "--confirm-owner-read-only",
    ])
    assert data_probe.main() == 0
    assert len(seen) == 4
    assert all(cal is None for _, cal in seen)
    assert all(cutoff.date() == datetime.now(timezone.utc).date() - timedelta(days=1) for cutoff, _ in seen)
    assert "test-only-placeholder" not in capsys.readouterr().out
