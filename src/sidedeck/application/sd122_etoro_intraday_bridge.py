"""SD-122: Offline eToro bid/ask 5m sample -> SideDeck DAY research bars.

This conversion never grants data entitlement, strategy admission or trading permission.
It has no credentials, HTTP client or order transport. Any research bars returned
are derived midpoint proxies; trading requires independent executable quotes.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Mapping

from sidedeck.application.sd068_track_scheduler import NEW_YORK, session_for
from sidedeck.application.sd069_day_trader_methods import IntradayBar
from sidedeck.application.sd119_etoro_market_data import (
    EtoroMarketDataError, parse_candles, provenance,
)

_STEP = timedelta(minutes=5)
_BASIS = "ETORO_5M_JSON_RESEARCH_ONLY_UNVERIFIED_LICENSE"
_FIELDS = ("open", "high", "low", "close")


def research_bars_from_etoro_sample(
    payload: Mapping[str, Any], *, instrument_id: int, symbol: str, cutoff: datetime,
) -> tuple[list[IntradayBar], dict[str, Any]]:
    """Parse a bounded local sample, rejecting missing sides, bars and future data.

    A sample may start mid-session for discovery. Incomplete sessions are labelled,
    never filled, and *never* counted as strategy admission evidence.
    """
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise EtoroMarketDataError("cutoff must be timezone-aware")
    if payload.get("side") != "both":
        raise EtoroMarketDataError("independent bid and ask candles are required")
    parsed = parse_candles(payload, instrument_id=instrument_id, symbol=symbol)
    if not parsed:
        raise EtoroMarketDataError("empty candle sample cannot form research bars")

    by_time: dict[datetime, dict[str, Any]] = {}
    for candle in parsed:
        sides = by_time.setdefault(candle.timestamp, {})
        if candle.side in sides:
            raise EtoroMarketDataError("duplicate candle side")
        sides[candle.side] = candle

    cutoff_utc = cutoff.astimezone(UTC)
    result: list[IntradayBar] = []
    sessions: dict[str, list[datetime]] = {}
    previous: datetime | None = None
    prior_session: str | None = None
    widest_spread = Decimal(0)

    for stamp, sides in sorted(by_time.items()):
        if set(sides) != {"bid", "ask"}:
            raise EtoroMarketDataError("both quote sides are required for each bar")
        if stamp.second or stamp.microsecond or stamp.minute % 5:
            raise EtoroMarketDataError("candle timestamp is not five-minute aligned")
        if stamp + _STEP > cutoff_utc:
            raise EtoroMarketDataError("future or incomplete five-minute candle")
        local_day = stamp.astimezone(NEW_YORK).date()
        session = session_for(local_day)
        if session is None or stamp < session.open_utc or stamp + _STEP > session.close_utc:
            raise EtoroMarketDataError("bar lies outside a verified regular session")
        session_day = local_day.isoformat()
        if previous is not None and session_day == prior_session and stamp != previous + _STEP:
            raise EtoroMarketDataError("missing five-minute bar inside sample session")
        bid, ask = sides["bid"], sides["ask"]
        if bid.volume is None or ask.volume is None or bid.volume != ask.volume:
            raise EtoroMarketDataError("missing or inconsistent bid/ask volume")
        for field in _FIELDS:
            if getattr(ask, field) < getattr(bid, field):
                raise EtoroMarketDataError("negative bid/ask spread")
        mid = {field: (getattr(bid, field) + getattr(ask, field)) / 2
               for field in _FIELDS}
        if mid["high"] < max(mid["open"], mid["close"]) or \
                mid["low"] > min(mid["open"], mid["close"]):
            raise EtoroMarketDataError("derived midpoint OHLC is inconsistent")
        widest_spread = max(widest_spread, ask.open - bid.open, ask.close - bid.close)
        result.append(IntradayBar(stamp, mid["open"], mid["high"], mid["low"],
                                  mid["close"], bid.volume))
        sessions.setdefault(session_day, []).append(stamp)
        previous, prior_session = stamp, session_day

    complete_sessions = 0
    for day, stamps in sessions.items():
        session = session_for(datetime.fromisoformat(day).date())
        if session is None:
            raise EtoroMarketDataError("session calendar lookup failed")
        expected = int((session.close_utc - session.open_utc) / _STEP)
        if len(stamps) == expected and stamps[0] == session.open_utc \
                and stamps[-1] + _STEP == session.close_utc:
            complete_sessions += 1

    source = provenance(payload)
    return result, {
        "schema": "sidedeck-etoro-five-minute-research-sample/1",
        "basis": _BASIS,
        "symbol": symbol, "instrument_id": instrument_id,
        "source_payload_sha256": source["payload_sha256"],
        "first_bar_utc": result[0].start.isoformat(),
        "last_bar_utc": result[-1].start.isoformat(),
        "cutoff_utc": cutoff_utc.isoformat(),
        "bar_count": len(result), "sessions_seen": len(sessions),
        "complete_sessions": complete_sessions,
        "price_basis": "DERIVED_BID_ASK_MIDPOINT_NONEXECUTABLE",
        "widest_observed_spread": str(widest_spread),
        "adjustment_basis": "UNVERIFIED",
        "data_entitlement": "UNVERIFIED",
        "strategy_admission_eligible": False,
        "broker_execution": "DISABLED",
    }
