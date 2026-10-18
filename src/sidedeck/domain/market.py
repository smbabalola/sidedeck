from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .contracts import MarketSnapshot, PriceType


def validate_snapshot(snapshot: MarketSnapshot, as_of: datetime, max_age: timedelta) -> MarketSnapshot:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    cutoff = as_of.astimezone(timezone.utc)
    market_time = snapshot.market_timestamp
    if market_time > cutoff:
        raise ValueError("snapshot is future-dated relative to decision cutoff")
    if cutoff - market_time > max_age:
        raise ValueError("snapshot is stale")
    if snapshot.price_type is PriceType.EOD_CLOSE and snapshot.session.value != "CLOSED":
        raise ValueError("EOD close must be marked as a closed-session snapshot")
    return snapshot
