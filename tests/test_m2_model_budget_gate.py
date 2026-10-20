from datetime import datetime, timezone

import pytest

from sidedeck.application.m2_research_run import (
    ResearchRunBlocked, plan_run, require_owner_authorization,
)


NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-1", "not-money"])
def test_invalid_budgets_are_rejected(amount):
    with pytest.raises(ResearchRunBlocked):
        plan_run("run", "US:MSFT", NOW, max_cost_usd=amount)


@pytest.mark.parametrize("calls", [-1, True, 0.5])
def test_invalid_call_limits_are_rejected(calls):
    with pytest.raises(ResearchRunBlocked):
        plan_run("run", "US:MSFT", NOW, max_provider_calls=calls)


def test_authorization_alone_is_not_a_spending_budget():
    with pytest.raises(ResearchRunBlocked):
        require_owner_authorization(plan_run("run", "US:MSFT", NOW), True)
    with pytest.raises(ResearchRunBlocked):
        require_owner_authorization(
            plan_run("run", "US:MSFT", NOW, max_provider_calls=0, max_cost_usd="1"), True,
        )


def test_budget_gate_does_not_invoke_provider():
    plan = plan_run("run", "US:MSFT", NOW, max_provider_calls=1, max_cost_usd="0.25")
    require_owner_authorization(plan, True)
    assert plan.broker_execution == "DISABLED"
