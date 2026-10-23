from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sidedeck.domain.market_import import MarketDataImportError, import_csv


def _csv(timestamp: str) -> str:
    return "instrument_id,ticker,provider,price_type,currency,price,market_timestamp,ingestion_timestamp,publication_timestamp,session,quality\n" + f"US:AAPL,AAPL,licensed-csv,EOD_CLOSE,USD,100,{timestamp},{timestamp},{timestamp},CLOSED,VERIFIED\n"


def test_import_requires_license_and_rejects_weekend_data(tmp_path) -> None:
    path = tmp_path / "prices.csv"
    monday = "2026-01-05T21:00:00+00:00"
    path.write_text(_csv(monday), encoding="utf-8")
    bundle = import_csv(
        path,
        bundle_id="csv-1",
        decision_cutoff=datetime(2026, 1, 5, 22, tzinfo=timezone.utc),
        max_age=timedelta(hours=2),
        license_confirmed=True,
    )
    assert bundle.snapshots[0].price == Decimal("100")
    assert "license-confirmed" in bundle.provenance
    with pytest.raises(MarketDataImportError, match="licence"):
        import_csv(path, bundle_id="csv-2", decision_cutoff=datetime(2026, 1, 5, 22, tzinfo=timezone.utc), max_age=timedelta(hours=2), license_confirmed=False)

    weekend = tmp_path / "weekend.csv"
    weekend.write_text(_csv("2026-01-04T21:00:00+00:00"), encoding="utf-8")
    with pytest.raises(MarketDataImportError, match="weekend"):
        import_csv(weekend, bundle_id="csv-3", decision_cutoff=datetime(2026, 1, 4, 22, tzinfo=timezone.utc), max_age=timedelta(hours=2), license_confirmed=True)
