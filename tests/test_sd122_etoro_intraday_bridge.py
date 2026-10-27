"""Offline contract tests: no provider requests and no admission upgrade."""
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from sidedeck.application.sd119_etoro_market_data import EtoroMarketDataError
from sidedeck.application.sd122_etoro_intraday_bridge import research_bars_from_etoro_sample


def _side(base: str, vol: str = "11") -> dict[str, str]:
    p = Decimal(base)
    return {"open": str(p), "high": str(p + 1), "low": str(p - 1),
            "close": str(p + Decimal("0.5")), "volume": vol}


def _payload() -> dict:
    # 2026-10-23 is a normal US equity session; 13:30 UTC is 09:30 ET.
    return {
        "instrumentId": 1004, "symbol": "MSFT/USD", "interval": "5m", "side": "both",
        "results": [
            {"time": "2026-10-23T13:35:00Z", "bid": _side("101"), "ask": _side("101.1")},
            {"time": "2026-10-23T13:30:00Z", "bid": _side("100"), "ask": _side("100.1")},
        ],
    }


_CUTOFF = datetime(2026, 10, 23, 13, 40, tzinfo=UTC)


def test_etoro_bid_ask_sample_is_research_only_and_preserves_lineage():
    bars, evidence = research_bars_from_etoro_sample(
        _payload(), instrument_id=1004, symbol="MSFT", cutoff=_CUTOFF)
    assert len(bars) == 2
    assert bars[0].open == Decimal("100.05")
    assert bars[1].start.isoformat() == "2026-10-23T13:35:00+00:00"
    assert len(evidence["source_payload_sha256"]) == 64
    assert evidence["complete_sessions"] == 0
    assert evidence["strategy_admission_eligible"] is False
    assert evidence["data_entitlement"] == "UNVERIFIED"
    assert evidence["broker_execution"] == "DISABLED"


@pytest.mark.parametrize("mutation,reason", [
    ("missing_ask", "bid and ask"),
    ("negative_spread", "negative bid/ask spread"),
    ("volume_disagreement", "volume"),
    ("timestamp_gap", "missing five-minute bar"),
    ("premarket", "outside a verified regular session"),
])
def test_etoro_sample_fails_closed(mutation: str, reason: str):
    payload = _payload()
    rows = payload["results"]
    if mutation == "missing_ask":
        rows[0].pop("ask")
    elif mutation == "negative_spread":
        rows[0]["ask"] = _side("100")
    elif mutation == "volume_disagreement":
        rows[0]["ask"]["volume"] = "12"
    elif mutation == "timestamp_gap":
        rows[0]["time"] = "2026-10-23T13:40:00Z"
    else:
        rows[1]["time"] = "2026-10-23T13:25:00Z"
    cutoff = (datetime(2026, 10, 23, 13, 45, tzinfo=UTC)
              if mutation == "timestamp_gap" else _CUTOFF)
    with pytest.raises(EtoroMarketDataError, match=reason):
        research_bars_from_etoro_sample(
            payload, instrument_id=1004, symbol="MSFT", cutoff=cutoff)


def test_etoro_sample_rejects_unfinished_bars_and_identity_mismatch():
    with pytest.raises(EtoroMarketDataError, match="future or incomplete"):
        research_bars_from_etoro_sample(
            _payload(), instrument_id=1004, symbol="MSFT",
            cutoff=datetime(2026, 10, 23, 13, 39, tzinfo=UTC))
    with pytest.raises(EtoroMarketDataError, match="identity"):
        research_bars_from_etoro_sample(
            _payload(), instrument_id=1002, symbol="MSFT", cutoff=_CUTOFF)
    with pytest.raises(EtoroMarketDataError, match="timezone"):
        research_bars_from_etoro_sample(
            _payload(), instrument_id=1004, symbol="MSFT",
            cutoff=datetime(2026, 10, 23, 13, 40))
