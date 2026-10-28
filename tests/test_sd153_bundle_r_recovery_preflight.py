"""SD-153 Bundle R: offline-only recovery GET preflight is never a grant."""
from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from sidedeck.application.sd152_offline_swing_runner import OfflineRunnerRefused
from sidedeck.domain.etoro_demo_orders import DEMO_CLOSE_INFO_PATH
from sidedeck.application.sd036_etoro_demo_desk import TransportNotFound

from test_sd063_autonomous_demo_policy import NOW, _Env
from test_sd140_sd152_offline_swing_runner import seal_bid
from test_sd138_autonomous_order_adapter import _composed
from sidedeck.application.sd068_track_scheduler import SchedulerStore
from sidedeck.application.sd140_offline_swing_controller import OfflineSwingCycleController
from sidedeck.application.sd152_offline_swing_runner import (
    OfflineSwingRunFence, OfflineSwingScheduledService,
)


@pytest.fixture
def recovery_env(tmp_path):
    env = _Env(tmp_path)
    gateway, quote, signer, route, lineage, _path, adapter = _composed(env, tmp_path)
    controller = OfflineSwingCycleController(gateway._runtime, adapter, clock=env.clock)
    scheduler = SchedulerStore(tmp_path / "schedule.sqlite3")
    fence = OfflineSwingRunFence(tmp_path / "single-writer.sqlite3")
    service = OfflineSwingScheduledService(scheduler, fence, controller, clock=env.clock)
    yield env, quote, signer, route, lineage, controller, scheduler, fence, service
    lineage.close()
    env.ledger.close()


def _pending(lineage, *, reference_id: str | None = None) -> str:
    ref = reference_id or str(uuid4())
    lineage.record_pending(
        reference_id=ref, kind="OPEN", intent_id=uuid4().hex,
        book_id="etoro-demo:tradingagents", instrument_id=1004,
        units=None, limit_rate=None, position_id=None,
    )
    return ref


def test_sd153_no_uncertain_orders_has_zero_recovery_requests(recovery_env):
    _env, _quote, _signer, route, _lineage, _controller, _scheduler, _fence, service = recovery_env
    before = tuple(route.calls)
    report = service.recovery_read_preflight(now=NOW)
    assert report["status"] == "NO_RECOVERY_READS_NEEDED"
    assert report["planned_get_count"] == 0
    assert report["planned_gets"] == []
    assert report["execution_release"] == "ETORO_DEMO_NOT_RELEASED"
    assert report["safe_to_send"] is False
    assert report["automatic_post_allowed"] is False
    assert tuple(route.calls) == before


def test_sd153_pending_open_proposes_one_separately_signed_reference_get(recovery_env):
    _env, _quote, _signer, route, lineage, _controller, _scheduler, _fence, service = recovery_env
    ref = _pending(lineage)
    before = tuple(route.calls)
    report = service.recovery_read_preflight(now=NOW, max_gets=1)
    assert report["status"] == "AWAITING_SEPARATE_OWNER_SIGNED_READ_AUTHORIZATION"
    assert report["planned_get_count"] == 1
    step = report["planned_gets"][0]
    assert step["reference_id"] == ref
    assert step["operation"] == "OPEN_ORDER_LOOKUP_GET"
    assert step["lookup"] == "ORIGINAL_REFERENCE_ID"
    assert step["authorization"] == "SEPARATE_OWNER_SIGNATURE_REQUIRED"
    assert step["automatic_execution"] is False
    assert report["safe_to_send"] is False
    assert tuple(route.calls) == before


def test_sd153_accepted_close_requires_two_distinct_gets_and_signed_audit(recovery_env):
    env, quote, signer, route, _lineage, controller, _scheduler, _fence, service = recovery_env
    entry = env.entry()
    controller.adapter.submit_entry(entry, quote=quote)
    plan = controller.runtime.plan_exits(bids=(seal_bid(signer, env, "455"),))
    assert len(plan.exits) == 1
    original_send = route.send

    def delay_close_info(method, path, **kwargs):
        if path == DEMO_CLOSE_INFO_PATH.format(order_id=770_002):
            raise TransportNotFound("accepted close not visible")
        return original_send(method, path, **kwargs)

    route.send = delay_close_info
    try:
        from sidedeck.application.sd138_autonomous_order_adapter import SD138Refused
        with pytest.raises(SD138Refused, match="stopped for reconciliation"):
            controller.adapter.submit_exit(plan.exits[0], quote=seal_bid(signer, env, "455"))
    finally:
        route.send = original_send
    before = tuple(route.calls)
    report = service.recovery_read_preflight(now=NOW)
    assert report["planned_get_count"] == 2
    assert [s["operation"] for s in report["planned_gets"]] == [
        "CLOSE_INFO_GET", "WHOLE_ACCOUNT_PNL_GET",
    ]
    assert all(s["pre_send_audit"] == "REQUIRED" for s in report["planned_gets"])
    assert all(s["automatic_execution"] is False for s in report["planned_gets"])
    assert report["automatic_get_allowed"] is False
    assert report["clear_halt_allowed"] is False
    assert tuple(route.calls) == before
    limited = service.recovery_read_preflight(now=NOW, max_gets=1)
    assert limited["status"] == "BLOCKED_MANUAL_REVIEW"
    assert "PLANNED_GET_BUDGET_EXCEEDED" in limited["failure_reasons"]
    assert tuple(route.calls) == before


def test_sd153_two_pending_intents_exceed_operator_get_cap(recovery_env):
    _env, _quote, _signer, route, lineage, _controller, _scheduler, _fence, service = recovery_env
    _pending(lineage)
    _pending(lineage)
    report = service.recovery_read_preflight(now=NOW, max_gets=1)
    assert report["planned_get_count"] == 2
    assert report["status"] == "BLOCKED_MANUAL_REVIEW"
    assert "PLANNED_GET_BUDGET_EXCEEDED" in report["failure_reasons"]
    assert report["automatic_get_allowed"] is False
    assert route.calls == []


def test_sd153_anchor_outage_blocks_unsigned_recovery_plan(recovery_env):
    env, _quote, _signer, route, lineage, _controller, _scheduler, _fence, service = recovery_env
    _pending(lineage)
    env.gateway_audit_anchor.unavailable = True
    before = tuple(route.calls)
    report = service.recovery_read_preflight(now=NOW)
    assert report["status"] == "BLOCKED_MANUAL_REVIEW"
    assert "EXTERNAL_AUDIT_CHECKPOINT_UNVERIFIED" in report["failure_reasons"]
    assert report["safe_to_send"] is False
    assert tuple(route.calls) == before


@pytest.mark.parametrize("budget", [0, 3, True, 1.5, "2"])
def test_sd153_recovery_budget_refuses_invalid_or_ambiguous_ceiling(recovery_env, budget):
    _env, _quote, _signer, route, _lineage, _controller, _scheduler, _fence, service = recovery_env
    with pytest.raises(OfflineRunnerRefused, match="budget"):
        service.recovery_read_preflight(now=NOW, max_gets=budget)
    assert route.calls == []


def test_sd153_recovery_preflight_does_not_accept_naive_time(recovery_env):
    _env, _quote, _signer, route, _lineage, _controller, _scheduler, _fence, service = recovery_env
    with pytest.raises(OfflineRunnerRefused, match="timezone-aware"):
        service.recovery_read_preflight(now=(NOW + timedelta(hours=1)).replace(tzinfo=None))
    assert route.calls == []


def test_sd153_recovery_plan_refuses_to_reoffer_consumed_reference_get(recovery_env):
    _env, _quote, _signer, route, lineage, _controller, _scheduler, _fence, service = recovery_env
    ref = _pending(lineage)
    lineage.reserve_offline_recovery_read(
        order_reference=ref, stage="REFERENCE", at=NOW,
    )
    before = tuple(route.calls)
    result = service.recovery_read_preflight(now=NOW)
    assert result["status"] == "BLOCKED_MANUAL_REVIEW"
    assert "DURABLE_RECOVERY_GET_ALREADY_RESERVED_MANUAL_REVIEW" in result["failure_reasons"]
    assert result["planned_get_count"] == 0
    assert result["safe_to_send"] is False
    assert tuple(route.calls) == before
