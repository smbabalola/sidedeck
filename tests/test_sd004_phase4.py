from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from sidedeck.application.p5_independent_price_evidence import (
    IndependentPriceCandidate,
    assess_candidate,
)
from sidedeck.application.p5_msft_corporate_actions import verify_msft_window
from sidedeck.application.p5_msft_share_basis import (
    MSFT_FY26_SHARE_BASIS,
    validate_actual_share_basis,
)
from sidedeck.application.p5_msft_valuation import (
    ValuationEvidenceError,
    MsftValuationEvidence,
    admit_msft_valuation,
)


def test_msft_window_has_no_split_and_records_dividend() -> None:
    result = verify_msft_window(date(2026, 7, 29), date(2026, 10, 20))
    assert result["status"] == "VERIFIED"
    assert result["split_in_window"] is False
    assert result["dividends_in_window"][0].effective_date == date(2026, 8, 20)
    assert result["dividends_in_window"][0].amount_per_share == Decimal("0.91")


def test_actual_share_basis_is_point_in_time_and_not_diluted_average() -> None:
    validate_actual_share_basis(basis=MSFT_FY26_SHARE_BASIS, valuation_date=date(2026, 7, 30))
    assert MSFT_FY26_SHARE_BASIS.actual_common_shares == Decimal("7425545491")
    assert MSFT_FY26_SHARE_BASIS.diluted_weighted_average_fy == Decimal("7453000000")


def test_future_actual_shares_are_rejected() -> None:
    with pytest.raises(ValueError, match="point-in-time"):
        validate_actual_share_basis(basis=MSFT_FY26_SHARE_BASIS, valuation_date=date(2026, 7, 22))


def test_proprietary_display_candidate_does_not_become_valuation_evidence() -> None:
    candidate = IndependentPriceCandidate(
        source_id="quiver:msft:historical",
        source_url="https://www.quiverquant.com/stock/MSFT/historical-prices/",
        access_status="PUBLIC", license_status="PERSONAL_NONCOMMERCIAL_ALLOWED",
        coverage_status="INCOMPLETE", close_definition="CLOSE",
        adjustment_basis="SPLIT_ADJUSTED_NOT_DIVIDEND_ADJUSTED", independent_transport=True,
    )
    assert assess_candidate(candidate) == "BLOCKED_PROVENANCE"


def test_diluted_weighted_average_is_not_accepted_as_actual_share_basis() -> None:
    evidence = MsftValuationEvidence(
        valuation_date=date(2026, 7, 30), cutoff=datetime(2026, 10, 20, tzinfo=timezone.utc),
        filing_published_at=datetime(2026, 7, 29, 20, 8, tzinfo=timezone.utc),
        price_date=date(2026, 7, 30), close_source_a=Decimal("451.10"),
        close_source_b=Decimal("451.10"), source_a="alpaca:sip", source_b="quiver:msft:historical",
        adjustment_basis="split_adjusted_close", corporate_actions_status="VERIFIED",
        diluted_eps=Decimal("17.95"), eps_source="sec:10-k", shares_outstanding=MSFT_FY26_SHARE_BASIS.diluted_weighted_average_fy,
        shares_as_of=date(2026, 7, 23), share_basis="diluted_weighted_average",
    )
    with pytest.raises(ValuationEvidenceError, match="actual outstanding"):
        admit_msft_valuation(evidence)
