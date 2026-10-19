from decimal import Decimal

import pytest

from sidedeck.application.saxo_order_preview import preview_account


def account(currency="EUR"):
    return {"Data": [{"AccountId": "22866064", "Active": True, "Currency": currency}]}


def balance(currency="EUR", cash=100000):
    return {"Currency": currency, "CashAvailableForTrading": cash}


def test_eur_account_is_observed_but_never_authorized():
    decision = preview_account(account(), balance(), expected_account_id="22866064")
    assert decision.account_verified
    assert decision.balance_currency == "EUR"
    assert decision.account_cash == Decimal("100000")
    assert decision.reason == "eur_usd_fx_not_approved"
    assert not decision.approved_for_submission


def test_usd_account_still_never_authorized():
    decision = preview_account(account("USD"), balance("USD"), expected_account_id="22866064")
    assert decision.reason == "order_submission_disabled"
    assert not decision.approved_for_submission


@pytest.mark.parametrize("value", ["NaN", "Infinity", -1, True, None, "oops"])
def test_bad_cash_blocks(value):
    with pytest.raises(ValueError):
        preview_account(account(), balance(cash=value), expected_account_id="22866064")


def test_identity_and_currency_guard():
    assert preview_account(account(), balance(), expected_account_id="WRONG").reason == "account_unverified"
    assert preview_account(account(), balance("USD"), expected_account_id="22866064").reason == "currency_mismatch"
