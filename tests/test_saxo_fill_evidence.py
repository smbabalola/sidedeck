from decimal import Decimal

import pytest

from sidedeck.application.saxo_fill_evidence import extract_sofi_fills


def record(**changes):
    base = {"AccountId": "22866064", "ExternalReference": "agent-1",
            "OrderId": "saxo-42", "Uic": 23241352, "AssetType": "Stock",
            "BuySell": "Buy", "Status": "FinalFill", "FillAmount": 1,
            "ExecutionPrice": 42.2, "ActivityTime": "2026-10-19T10:00:00Z",
            "LogId": "log-1"}
    base.update(changes)
    return base


def parse(data):
    return extract_sofi_fills(data, account_id="22866064",
                              external_reference="agent-1", order_id="saxo-42")


def test_verified_one_share_final_fill():
    result = parse({"Data": [record()], "__count": 1})
    assert len(result) == 1
    assert result[0].amount == Decimal("1")
    assert result[0].price == Decimal("42.2")


def test_order_placement_is_not_fill():
    assert parse({"Data": [record(Status="Placed")]}) == ()


@pytest.mark.parametrize("bad", [
    {"AccountId": "different"},
    {"ExternalReference": "other"},
    {"OrderId": "wrong"},
    {"Uic": 211},
    {"AssetType": "CfdOnStock"},
    {"BuySell": "Sell"},
    {"FillAmount": 0},
    {"ExecutionPrice": None},
    {"Status": "Unknown"},
    {"LogId": None},
])
def test_invalid_evidence_never_mints_fill(bad):
    with pytest.raises(ValueError):
        parse({"Data": [record(**bad)]})


def test_missing_page_duplicate_logs_and_oversized_fill():
    with pytest.raises(ValueError):
        parse({"Data": [record()], "__next": "next"})
    with pytest.raises(ValueError):
        parse({"Data": [record(), record()]})
    with pytest.raises(ValueError):
        parse({"Data": [record(FillAmount=2)]})
