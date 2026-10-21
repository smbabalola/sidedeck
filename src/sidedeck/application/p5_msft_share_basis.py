"""Point-in-time MSFT share and EPS basis from the FY26 Form 10-K."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class MsftShareBasis:
    actual_common_shares: Decimal
    actual_shares_as_of: date
    basic_weighted_average_fy: Decimal
    diluted_weighted_average_fy: Decimal
    diluted_eps_fy: Decimal
    earnings_period_end: date
    source_url: str


MSFT_FY26_SHARE_BASIS = MsftShareBasis(
    actual_common_shares=Decimal("7425545491"),
    actual_shares_as_of=date(2026, 7, 23),
    basic_weighted_average_fy=Decimal("7429000000"),
    diluted_weighted_average_fy=Decimal("7453000000"),
    diluted_eps_fy=Decimal("17.95"),
    earnings_period_end=date(2026, 6, 30),
    source_url="https://www.sec.gov/Archives/edgar/data/789019/000119312526323660/msft-20260630.htm",
)


def validate_actual_share_basis(*, basis: MsftShareBasis, valuation_date: date) -> None:
    if basis.actual_shares_as_of > valuation_date:
        raise ValueError("actual shares are not point-in-time available")
    if basis.actual_common_shares <= 0 or basis.diluted_eps_fy <= 0:
        raise ValueError("share and EPS values must be positive")
    if basis.diluted_weighted_average_fy == basis.actual_common_shares:
        raise ValueError("weighted-average shares cannot certify actual shares")
