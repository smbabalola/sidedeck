from decimal import Decimal

import pytest

from sidedeck.application.saxo_sofi_acceptance import acceptance_reasons, _count


def test_broker_precheck_ok_still_never_authorizes_order():
    reasons = acceptance_reasons(
        detail_ok=True, precheck_ok=True, estimate_eur=Decimal("41.03"),
        account_currency="EUR", positions=0, orders=0,
    )
    assert "estimated_cash_exceeds_risk_cap" not in reasons
    assert "single_sim_order_submit_not_implemented" in reasons
    assert "approved_eur_usd_fx_and_fees_missing" in reasons


def test_estimate_and_exposure_rejected():
    reasons = acceptance_reasons(
        detail_ok=True, precheck_ok=True, estimate_eur=Decimal("201"),
        account_currency="EUR", positions=1, orders=0,
    )
    assert "estimated_cash_exceeds_risk_cap" in reasons
    assert "unexpected_existing_broker_exposure" in reasons


@pytest.mark.parametrize("data", [
    {"Data": [], "__next": "another"}, {"Data": [], "__count": 2},
    {"Data": [None]}, {},
])
def test_incomplete_broker_data_fails_closed(data):
    with pytest.raises(ValueError):
        _count(data, "orders")
