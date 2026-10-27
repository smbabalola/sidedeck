from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from sidedeck.application.sd065_market_universe import (
    BrokerMapping, InstrumentRecord, MarketUniverseRegistry, TickerInterval,
)
from sidedeck.application.sd069_day_trader_methods import METHOD_VERSION
from sidedeck.application.sd123_day_demo_integration import (
    STRATEGY_ID, STRATEGY_VERSION, admit_fixture_day_strategy, release_status,
    research_day_sample,
)

from test_sd122_etoro_intraday_bridge import _CUTOFF, _payload, _side


def _registry(*, wrong_mapping: bool = False, include_spy: bool = True) -> MarketUniverseRegistry:
    pairs = [
        ("MSFT", "NASDAQ", "COMMON_STOCK", "1004"),
        ("QQQ", "NASDAQ", "ETF", "2002"),
    ]
    if include_spy:
        pairs.append(("SPY", "NYSE_ARCA", "ETF", "2001"))
    records = []
    for symbol, exchange, asset_type, broker_id in pairs:
        mapping = BrokerMapping(
            broker="ETORO", environment="DEMO",
            broker_instrument_id="9999" if wrong_mapping and symbol == "MSFT" else broker_id,
            verified_at=datetime(2026, 10, 20, tzinfo=UTC),
            verification_source="LOCAL_TEST_FIXTURE",
        )
        records.append(InstrumentRecord(
            canonical_id=f"US:{symbol}", name=symbol, country="US",
            asset_type=asset_type, currency="USD",
            tickers=(TickerInterval(symbol, exchange, date(2000, 1, 3)),),
            history_basis="POINT_IN_TIME", provenance="TEST_FIXTURE",
            listing_date=date(2000, 1, 3), broker_mappings=(mapping,),
        ))
    return MarketUniverseRegistry(1, datetime(2026, 10, 20, tzinfo=UTC),
                                  "TEST_FIXTURE_ONLY", tuple(records))


def _sample(symbol: str, instrument_id: int, times: tuple[str, ...],
            prices: tuple[str, ...]) -> dict:
    return {
        "instrumentId": instrument_id, "symbol": f"{symbol}/USD",
        "interval": "5m", "side": "both",
        "results": [
            {"time": stamp, "bid": _side(price), "ask": _side(str(Decimal(price) + Decimal("0.1")))}
            for stamp, price in zip(times, prices)
        ],
    }


def test_day_research_stays_research_only_and_keeps_independent_admission():
    result = research_day_sample(
        _payload(), instrument_id=1004, symbol="MSFT", cutoff=_CUTOFF,
        generated_at=datetime(2026, 10, 23, 13, 40, tzinfo=UTC),
        registry=_registry(),
    )
    assert result.signal is None
    assert result.status == "NO_SIGNAL"
    assert result.admission.status == "RESEARCH_ONLY"
    assert result.admission.version == METHOD_VERSION
    assert result.metadata["strategy_admission_eligible"] is False
    assert result.metadata["canonical_id"] == "US:MSFT"
    assert result.metadata["broker_mapping"] == "VERIFIED"


def test_orb_signal_admission_and_policy_use_the_same_pinned_identity():
    payload = _sample(
        "MSFT", 1004,
        ("2026-10-23T13:30:00Z", "2026-10-23T13:35:00Z",
         "2026-10-23T13:40:00Z", "2026-10-23T13:45:00Z"),
        ("100", "100", "100", "103"),
    )
    stamp = datetime(2026, 10, 23, 13, 50, tzinfo=UTC)
    result = research_day_sample(
        payload, instrument_id=1004, symbol="MSFT", cutoff=stamp,
        generated_at=stamp, registry=_registry(),
    )
    assert result.status == "RESEARCH_ONLY"
    assert result.signal is not None
    assert result.signal.source_kind == "DAY_TRADER_METHOD"
    assert (result.signal.source_id, result.signal.source_version) == (
        result.admission.strategy_id, result.admission.version,
    ) == (STRATEGY_ID, STRATEGY_VERSION)
    assert result.signal.canonical_id == "US:MSFT"
    assert result.admission.status == "RESEARCH_ONLY"
    # A chart rule match is not itself a NATIVE_STRATEGY, let alone an execution permit.


@pytest.mark.parametrize("symbol,ident,exchange", [
    ("SPY", 2001, "NYSE_ARCA"),
    ("QQQ", 2002, "NASDAQ"),
    ("MSFT", 1004, "NASDAQ"),
])
def test_registry_resolves_correct_listing_not_fabricated_nasdaq(symbol, ident, exchange):
    sample = _sample(
        symbol, ident, ("2026-10-23T13:30:00Z", "2026-10-23T13:35:00Z"),
        ("100", "101"),
    )
    registry = _registry()
    assert registry.resolve(symbol, date(2026, 10, 23)).ticker_on(
        date(2026, 10, 23)).exchange == exchange
    result = research_day_sample(
        sample, instrument_id=ident, symbol=symbol, cutoff=_CUTOFF,
        generated_at=_CUTOFF, registry=registry,
    )
    assert result.metadata["canonical_id"] == f"US:{symbol}"
    assert result.admission.status == "RESEARCH_ONLY"


def test_sd120_ten_am_discovery_window_refuses_to_make_up_opening_range():
    payload = _sample(
        "MSFT", 1004,
        ("2026-10-23T14:00:00Z", "2026-10-23T14:05:00Z"),
        ("100", "101"),
    )
    stamp = datetime(2026, 10, 23, 14, 10, tzinfo=UTC)
    result = research_day_sample(
        payload, instrument_id=1004, symbol="MSFT", cutoff=stamp,
        generated_at=stamp, registry=_registry(),
    )
    assert result.status == "INSUFFICIENT_OPENING_RANGE"
    assert result.signal is None
    assert result.admission.status == "RESEARCH_ONLY"
    assert result.metadata["complete_sessions"] == 0


def test_registry_refuses_unknown_ticker_and_verified_broker_id_conflict():
    with pytest.raises(ValueError, match="absent or ambiguous"):
        research_day_sample(
            _sample("SPY", 2001, ("2026-10-23T13:30:00Z",), ("100",)),
            instrument_id=2001, symbol="SPY", cutoff=_CUTOFF,
            generated_at=_CUTOFF, registry=_registry(include_spy=False),
        )
    with pytest.raises(ValueError, match="conflicts"):
        research_day_sample(
            _payload(), instrument_id=1004, symbol="MSFT", cutoff=_CUTOFF,
            generated_at=_CUTOFF, registry=_registry(wrong_mapping=True),
        )


def test_research_rejects_generation_before_cutoff():
    with pytest.raises(ValueError, match="ordered timezone-aware"):
        research_day_sample(
            _payload(), instrument_id=1004, symbol="MSFT", cutoff=_CUTOFF,
            generated_at=datetime(2026, 10, 23, 13, 35, tzinfo=UTC),
            registry=_registry(),
        )


def test_fixture_admission_requires_explicit_override_and_oos_floor():
    with pytest.raises(PermissionError, match="fixture_acceptance"):
        admit_fixture_day_strategy(evidence_ref="sd071://fixture", oos_trades=30,
                                   oos_validated=True)
    with pytest.raises(ValueError):
        admit_fixture_day_strategy(evidence_ref="sd071://fixture", oos_trades=29,
                                   oos_validated=True, fixture_acceptance=True)
    admission = admit_fixture_day_strategy(
        evidence_ref="sd071://fixture", oos_trades=30, oos_validated=True,
        fixture_acceptance=True,
    )
    assert admission.status == "ADMITTED"
    assert (admission.strategy_id, admission.version) == (STRATEGY_ID, STRATEGY_VERSION)
    assert admission.track == "DAY"


def test_release_status_remains_fail_closed():
    status = release_status()
    assert status["broker_route"] == "ETORO_DEMO_NOT_RELEASED"
    assert status["etoro_real"] == "PERMANENTLY_EXCLUDED"
