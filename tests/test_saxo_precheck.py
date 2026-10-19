import pytest

from sidedeck.infrastructure.saxo_account_scope import SaxoAccountScope
from sidedeck.infrastructure.saxo_precheck import (
    parse_precheck, precheck_payload, run_sim_precheck, SaxoPrecheckError,
)


def scope():
    return SaxoAccountScope("22866064", "fake-key==", "fake-client==")


def test_precheck_only_one_share_us_stock():
    data = precheck_payload(scope())
    assert data["Uic"] == 211
    assert data["Amount"] == 1
    assert data["AssetType"] == "Stock"
    assert data["FieldGroups"] == ["Costs"]
    assert "OrderId" not in data
    for bad in (0, 2, True, 1.0):
        with pytest.raises(ValueError):
            precheck_payload(scope(), amount=bad)
    with pytest.raises(ValueError):
        precheck_payload(scope(), uic=15777171)


def test_precheck_success_still_cannot_place_order():
    response = {"PreCheckResult": "Ok", "EstimatedCashRequired": 140,
                "EstimatedCashRequiredCurrency": "EUR",
                "EstimatedTotalCost": 120, "EstimatedTotalCostInAccountCurrency": 140,
                "InstrumentToAccountConversionRate": 1.16}
    result = parse_precheck(response, instrument_currency="USD", account_currency="EUR")
    assert result.result == "Ok"
    assert result.estimated_cash_required is not None
    result.validate_for_order(instrument_currency="USD", account_currency="EUR")
    assert result.reason == "broker_precheck_validated"


def test_broker_errors_and_disclaimers_fail_closed():
    response = {"PreCheckResult": "Error", "ErrorInfo": {"Code": "NoAccess"}}
    assert parse_precheck(response, instrument_currency="USD", account_currency="EUR").reason == "broker_precheck_not_ok"
    disclaimer = {"PreCheckResult": "Ok", "PreTradeDisclaimers": [{"Id": "required"}]}
    assert parse_precheck(disclaimer, instrument_currency="USD", account_currency="EUR").reason == "disclaimers_require_review"
    assert parse_precheck({"PreCheckResult": "Ok"}, instrument_currency="USD", account_currency="EUR").reason == "cash_estimate_missing"


def test_missing_token_does_not_request_network(monkeypatch):
    monkeypatch.delenv("SAXO_SIM_ACCESS_TOKEN", raising=False)
    with pytest.raises(SaxoPrecheckError):
        run_sim_precheck(scope())
