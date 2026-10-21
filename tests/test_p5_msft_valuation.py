from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from sidedeck.application.p5_msft_valuation import (
    MsftValuationEvidence, ValuationEvidenceError, admit_msft_valuation,
)


def evidence(**changes):
    values = dict(
        valuation_date=date(2025, 2, 3), cutoff=datetime(2025, 3, 1, tzinfo=timezone.utc),
        filing_published_at=datetime(2025, 1, 31, 14, tzinfo=timezone.utc),
        price_date=date(2025, 2, 3), close_source_a=Decimal("410"),
        close_source_b=Decimal("410.01"), source_a="alpaca:sip", source_b="nasdaq:eod",
        adjustment_basis="split_adjusted_close", corporate_actions_status="VERIFIED",
        diluted_eps=Decimal("10"), eps_source="sec:2025-01-31", shares_outstanding=Decimal("100"),
        shares_as_of=date(2025, 1, 31),
    )
    values.update(changes)
    return MsftValuationEvidence(**values)


def test_valuation_contract_calculates_only_after_all_evidence_is_explicit():
    result = admit_msft_valuation(evidence())
    assert result["status"] == "VALIDATED"
    assert result["market_cap_usd"] == "41000.500"
    assert result["pe"] == "41.0005"


@pytest.mark.parametrize("changes", [
    {"source_b": "alpaca:sip"},
    {"corporate_actions_status": "UNVERIFIED"},
    {"filing_published_at": datetime(2025, 3, 2, tzinfo=timezone.utc)},
    {"adjustment_basis": "raw_close"},
    {"close_source_b": Decimal("420")},
])
def test_valuation_contract_fails_closed(changes):
    with pytest.raises(ValuationEvidenceError):
        admit_msft_valuation(evidence(**changes))
