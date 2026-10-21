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


def test_authorization_is_single_use_and_budgeted():
    plan = plan_run("lease", "US:MSFT", NOW, max_provider_calls=1, max_cost_usd="0.25")
    lease = require_owner_authorization(plan, True)
    lease.consume(estimated_cost_usd="0.25")
    with pytest.raises(ResearchRunBlocked, match="exhausted"):
        lease.consume()


def test_authorization_rejects_cost_overrun_without_consuming_call():
    lease = require_owner_authorization(
        plan_run("overrun", "US:MSFT", NOW, max_provider_calls=2, max_cost_usd="0.25"), True,
    )
    with pytest.raises(ResearchRunBlocked, match="exceeds"):
        lease.consume(estimated_cost_usd="0.26")
    lease.consume(estimated_cost_usd="0.25")


def test_same_run_cannot_replay_owner_attestation():
    plan = plan_run("replay", "US:MSFT", NOW, max_provider_calls=1, max_cost_usd="0.25")
    require_owner_authorization(plan, True)
    with pytest.raises(ResearchRunBlocked, match="already been issued"):
        require_owner_authorization(plan, True)
