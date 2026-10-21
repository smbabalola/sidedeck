from __future__ import annotations

import pytest

from sidedeck.application.sd024_etf_distribution_evidence import validate_evidence


def _payload() -> dict[str, object]:
    return {
        "ticker": "SPY",
        "source_class": "owner_supplied_licensed",
        "source_url": "file://owner-supplied/spy-actions.csv",
        "records": [
            {"kind": "distribution", "effective_date": "2024-03-15", "payment_date": "2024-03-20", "amount_per_share": "1.50"},
            {"kind": "split", "effective_date": "2024-06-01", "ratio": "2:1"},
        ],
    }


def test_normalizes_action_evidence_without_claiming_prices_are_total_return() -> None:
    result = validate_evidence(_payload())
    assert result["corporate_actions_status"] == "VERIFIED"
    assert result["price_only_benchmark"] == "SUPPORTED"
    assert result["total_return_benchmark"] == "AVAILABLE_IF_DISTRIBUTIONS_AND_REINVESTMENT_ARE_COMPLETE"
    assert result["records"][0]["amount_per_share"] == "1.50"


@pytest.mark.parametrize("change", [
    {"source_class": "authenticated"},
    {"records": [{"kind": "distribution", "effective_date": "2024-03-15", "payment_date": "2024-03-14", "amount_per_share": "1"}]},
    {"records": [{"kind": "split", "effective_date": "2024-03-15"}]},
])
def test_rejects_unapproved_or_economically_invalid_evidence(change: dict[str, object]) -> None:
    payload = _payload()
    payload.update(change)
    with pytest.raises(ValueError):
        validate_evidence(payload)
