from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from .contracts import MarketSnapshot, PriceType, Session, require_utc
from .market import validate_snapshot
if TYPE_CHECKING:
    from sidedeck.agents.contracts import MarketBundle


class MarketDataImportError(ValueError):
    """The local market-data file cannot be safely used as a point-in-time bundle."""


def import_csv(
    path: Path,
    *,
    bundle_id: str,
    decision_cutoff: datetime,
    max_age: timedelta,
    license_confirmed: bool,
) -> MarketBundle:
    from sidedeck.agents.contracts import MarketBundle
    if not license_confirmed:
        raise MarketDataImportError("market-data licence/usage confirmation is required")
    cutoff = require_utc(decision_cutoff)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    required = {
        "instrument_id", "ticker", "provider", "price_type", "currency", "price",
        "market_timestamp", "ingestion_timestamp", "publication_timestamp", "session", "quality",
    }
    snapshots: list[MarketSnapshot] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise MarketDataImportError(f"CSV must contain columns: {sorted(required)}")
        for row in reader:
            try:
                market_time = datetime.fromisoformat(row["market_timestamp"])
                ingestion_time = datetime.fromisoformat(row["ingestion_timestamp"])
                publication_time = datetime.fromisoformat(row["publication_timestamp"])
                snapshot = MarketSnapshot(
                    instrument_id=row["instrument_id"], ticker=row["ticker"], provider=row["provider"],
                    price_type=PriceType(row["price_type"]), currency=row["currency"],
                    price=Decimal(row["price"]), market_timestamp=market_time,
                    ingestion_timestamp=ingestion_time, publication_timestamp=publication_time,
                    session=Session(row["session"]), quality=row["quality"],
                )
                validate_snapshot(snapshot, cutoff, max_age)
            except (KeyError, TypeError, ValueError) as exc:
                raise MarketDataImportError(f"invalid market-data row: {exc}") from exc
            if snapshot.market_timestamp.weekday() >= 5:
                raise MarketDataImportError("weekend observations require an explicit synthetic fixture path")
            snapshots.append(snapshot)
    if not snapshots:
        raise MarketDataImportError("market-data CSV cannot be empty")
    snapshots.sort(key=lambda value: (value.instrument_id, value.market_timestamp))
    if len({value.instrument_id for value in snapshots}) != len(snapshots):
        raise MarketDataImportError("bundle requires one unambiguous snapshot per instrument")
    return MarketBundle(
        bundle_id=bundle_id,
        decision_cutoff_utc=cutoff,
        snapshots=tuple(snapshots),
        allowed_instruments=tuple(value.instrument_id for value in snapshots),
        max_snapshot_age_seconds=int(max_age.total_seconds()),
        provenance=f"CSV:{path.name}:sha256:{digest}:license-confirmed",
    )
