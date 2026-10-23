from __future__ import annotations

from datetime import datetime, timedelta

from .contracts import MarketSnapshot, PriceType, USD, require_utc
from .instruments import get_instrument_by_id


def validate_snapshot(snapshot: MarketSnapshot, as_of: datetime, max_age: timedelta) -> MarketSnapshot:
    cutoff = require_utc(as_of)
    if max_age <= timedelta(0):
        raise ValueError("max_age must be positive")
    instrument = get_instrument_by_id(snapshot.instrument_id)
    if snapshot.ticker != instrument.ticker or snapshot.currency != USD:
        raise ValueError("snapshot does not match the approved USD instrument")
    market_time = snapshot.market_timestamp
    if market_time > cutoff or snapshot.ingestion_timestamp > cutoff:
        raise ValueError("snapshot is future-dated relative to decision cutoff")
    if snapshot.publication_timestamp is not None and snapshot.publication_timestamp > cutoff:
        raise ValueError("snapshot publication is future-dated relative to decision cutoff")
    if cutoff - market_time > max_age:
        raise ValueError("snapshot is stale")
    if snapshot.price_type is PriceType.EOD_CLOSE and snapshot.session.value != "CLOSED":
        raise ValueError("EOD close must be marked as a closed-session snapshot")
    return snapshot
