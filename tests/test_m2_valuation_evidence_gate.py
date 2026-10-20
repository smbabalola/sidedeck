from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from sidedeck.application.m2_market_data import MarketDataError, admit_valuation, normalize_daily_bars


def example():
    data = {"instrument_id": "US:MSFT", "source": "fixture",
            "exchange": "NASDAQ", "session": "REGULAR",
            "currency": "USD", "adjustment": "split_adjusted",
            "records": [{"timestamp": "2026-01-05T21:00:00+00:00", "open": "100",
                         "high": "105", "low": "99", "close": "104",
                         "volume": "100", "source_id": "fixture-1"}]}
    return normalize_daily_bars(data, cutoff=datetime(2026, 1, 6, tzinfo=timezone.utc))


@pytest.mark.parametrize("flags", [
    {},
    {"independent_close_verified": True},
    {"independent_close_verified": True, "corporate_actions_verified": True},
    {"independent_close_verified": True, "share_price_basis_verified": True},
])
def test_valuation_requires_all_external_evidence(flags):
    bars, report = example()
    with pytest.raises(MarketDataError, match="independent closing-price"):
        admit_valuation(eps=Decimal("5"), shares=Decimal("10"), bar=bars[-1],
                        market_report=report, shares_filed=date(2025, 12, 1),
                        cutoff=date(2026, 1, 6), **flags)


def test_nonfinite_eps_cannot_be_admitted():
    bars, report = example()
    with pytest.raises(MarketDataError):
        admit_valuation(eps=Decimal("NaN"), shares=Decimal("10"), bar=bars[-1],
                        market_report=report, shares_filed=date(2025, 12, 1),
                        cutoff=date(2026, 1, 6), independent_close_verified=True,
                        corporate_actions_verified=True, share_price_basis_verified=True)
