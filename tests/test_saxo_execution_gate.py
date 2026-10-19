from decimal import Decimal

import pytest

from sidedeck.application.saxo_execution_gate import execution_gate, stage_one_share


def test_persistent_idempotent_staging(tmp_path):
    path = tmp_path / "gate.sqlite"
    kwargs = {"order_key": "test-001", "portfolio_id": "tradingagents",
              "max_usd_notional": Decimal("100"), "max_eur_cash": Decimal("100")}
    assert stage_one_share(path, **kwargs)
    assert not stage_one_share(path, **kwargs)
    with pytest.raises(ValueError, match="conflicting"):
        stage_one_share(path, **{**kwargs, "max_eur_cash": Decimal("101")})


def test_observed_precheck_exceeds_conservative_cap(tmp_path):
    with pytest.raises(ValueError, match="cap"):
        stage_one_share(tmp_path / "gate.sqlite", order_key="test",
                        portfolio_id="ai-trading", max_usd_notional=Decimal("200"),
                        max_eur_cash=Decimal("364.02"))
    ok, reason = execution_gate(
        account_currency="EUR", precheck_ok=True,
        broker_estimate_eur=Decimal("364.02"),
        independent_quote_verified=False, fx_conversion_verified=False,
        broker_fill_reconciliation_ready=False)
    assert not ok and reason == "single_order_risk_cap"


def test_every_complete_gate_still_disables_submission():
    ok, reason = execution_gate(
        account_currency="EUR", precheck_ok=True,
        broker_estimate_eur=Decimal("100"), independent_quote_verified=True,
        fx_conversion_verified=True, broker_fill_reconciliation_ready=True)
    assert not ok and reason == "sim_order_submission_not_implemented"


@pytest.mark.parametrize("portfolio", ["wrong", "TradingAgents", ""])
def test_unauthorized_portfolios_rejected(tmp_path, portfolio):
    with pytest.raises(ValueError):
        stage_one_share(tmp_path / "gate.sqlite", order_key="one",
                        portfolio_id=portfolio, max_usd_notional=Decimal("100"),
                        max_eur_cash=Decimal("100"))
