import pytest

from sidedeck.application.saxo_readiness import assess_saxo_readiness


def accounts(currency="EUR"):
    return {"Data": [{"AccountId": "22866064", "AccountKey": "synthetic",
                      "Active": True, "Currency": currency}]}


def balance(currency="EUR", cash=100000, orders=0, positions=0):
    return {"Currency": currency, "CashAvailableForTrading": cash,
            "OrdersCount": orders, "OpenPositionsCount": positions}


def test_real_configuration_blocks_usd_ledger_against_eur_broker():
    decision = assess_saxo_readiness(accounts(), balance(), expected_account_id="22866064")
    assert decision.identity_verified
    assert decision.broker_currency == "EUR"
    assert decision.reason == "currency_conversion_not_approved"
    assert not decision.orders_allowed


def test_even_usd_sim_is_not_execution_approval():
    decision = assess_saxo_readiness(accounts("USD"), balance("USD"),
                                     expected_account_id="22866064")
    assert decision.reason == "paper_execution_not_enabled"
    assert not decision.orders_allowed


def test_existing_positions_block_even_on_usd():
    result = assess_saxo_readiness(accounts("USD"), balance("USD", positions=1),
                                   expected_account_id="22866064")
    assert result.reason == "existing_broker_exposure_requires_reconciliation"


def test_mismatched_account_blocks():
    result = assess_saxo_readiness(accounts(), balance(), expected_account_id="WRONG")
    assert not result.identity_verified
    assert not result.orders_allowed


@pytest.mark.parametrize("cash,orders,positions", [
    ("NaN", 0, 0), (-1, 0, 0), (100, -1, 0), (100, 1.0, 0), (100, 0, True),
])
def test_bogus_broker_values_block(cash, orders, positions):
    with pytest.raises(ValueError):
        assess_saxo_readiness(accounts(), balance(cash=cash, orders=orders, positions=positions),
                              expected_account_id="22866064")


def test_inconsistent_balance_currency_blocks():
    result = assess_saxo_readiness(accounts(), balance("USD"),
                                   expected_account_id="22866064")
    assert result.reason == "balance_currency_mismatch"
