"""SD-140/152 OFFLINE scheduled SWING end-to-end and single-writer negative tests."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import UUID
from concurrent.futures import ThreadPoolExecutor

import pytest

from sidedeck.application.sd063_autonomous_demo_policy import EntryProposal
from sidedeck.application.sd036_etoro_demo_desk import TransportNotFound
from sidedeck.domain.etoro_demo_orders import DEMO_CLOSE_INFO_PATH
from sidedeck.application.sd068_track_scheduler import SchedulerStore, session_for, slots_for
from sidedeck.application.sd140_offline_swing_controller import OfflineSwingCycleController
from sidedeck.application.sd152_offline_swing_runner import (
    OfflineRunnerRefused, OfflineSwingRunFence, OfflineSwingScheduledService,
)

from test_sd063_autonomous_demo_policy import _Env, MSFT, NOW
from test_sd138_autonomous_order_adapter import _composed


@pytest.fixture
def setup(tmp_path: Path):
    env = _Env(tmp_path)
    gateway, entry_quote, signer, route, lineage, _path, adapter = _composed(env, tmp_path)
    controller = OfflineSwingCycleController(gateway._runtime, adapter, clock=env.clock)
    scheduler = SchedulerStore(tmp_path / "schedule.sqlite3")
    fence = OfflineSwingRunFence(tmp_path / "single-writer.sqlite3")
    service = OfflineSwingScheduledService(scheduler, fence, controller, clock=env.clock)
    yield env, entry_quote, signer, route, lineage, controller, scheduler, fence, service
    lineage.close()
    env.ledger.close()


def allow_fake_schedule(scheduler: SchedulerStore) -> None:
    scheduler.set_track("SWING", enabled=True, mode="SIMULATION_ONLY")
    scheduler.set_exchange_track("XNYS", "SWING", enabled=True, mode="SIMULATION_ONLY")


def seal_bid(signer, env, price: str):
    return signer.seal({
        "canonical_id": MSFT, "bid": price, "ask": str(float(price) + 1),
        "quote_time": env.clock.now.isoformat(),
    })


def test_sd152_starts_locked_and_sends_no_fake_order(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    proposal = env.entry()
    assert isinstance(proposal, EntryProposal)
    result = service.run_due(owner="worker-a", entry=proposal, entry_quote=quote)
    assert result.status == "LOCKED"
    assert result.execution_release == "ETORO_DEMO_NOT_RELEASED"
    assert route.calls == []
    assert fence.state() == "IDLE"
    assert scheduler.history("swing_review") == ()


def test_sd140_sd152_two_sessions_open_and_close_via_real_fake_adapter(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    proposal = env.entry()
    assert isinstance(proposal, EntryProposal)
    first = service.run_due(owner="worker-a", entry=proposal, entry_quote=quote)
    assert first.status == "ENTRY_CONFIRMED"
    assert first.cycle is not None
    assert first.cycle.open_positions == 1
    assert [method for method, _ in route.calls].count("POST") == 1
    assert fence.state() == "IDLE"
    assert len(scheduler.history("swing_review")) == 1

    # A recorded slot never triggers another order even after the service is
    # reconstructed with a second fence/scheduler handle.
    duplicate = OfflineSwingScheduledService(
        SchedulerStore(env.tmp / "schedule.sqlite3"),
        OfflineSwingRunFence(env.tmp / "single-writer.sqlite3"), controller,
        clock=env.clock)
    assert duplicate.run_due(owner="worker-b", entry=proposal, entry_quote=quote).status == "NO_DUE_SLOT"
    assert [method for method, _ in route.calls].count("POST") == 1

    # Second valid XNYS review slot, same day: stop-based exit has priority.
    env.clock.now = NOW + timedelta(hours=2, minutes=35)
    planning = seal_bid(signer, env, "455")
    execution = seal_bid(signer, env, "455")
    result = service.run_due(
        owner="worker-b", planning_bids=(planning,),
        execution_bids={MSFT: execution},
        entry=proposal,
    )
    assert result.status == "EXITS_CONFIRMED"
    assert result.cycle is not None
    assert result.cycle.open_positions == 0
    assert result.cycle.entry_reference is None
    assert len(result.cycle.exit_references) == 1
    assert [method for method, _ in route.calls].count("POST") == 2
    assert lineage.owned(880_001)["state"] == "CLOSED"
    assert env.ledger.open_positions() == ()
    assert fence.state() == "IDLE"
    assert [status for _, status in fence.history()] == ["ENTRY_CONFIRMED", "EXITS_CONFIRMED"]
    assert not env.ledger.kill_switch_engaged()


def test_sd152_crash_and_second_process_do_not_take_over_or_repost(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    slot = slots_for(scheduler.jobs["swing_review"], NOW.date())[0]
    token = fence.acquire(slot, owner="crashed-worker", at=NOW)
    assert token is not None
    # New process sees the durable singleton state even if another scheduler
    # lease would eventually expire; do not guess whether a POST was delivered.
    restarted = OfflineSwingScheduledService(
        SchedulerStore(env.tmp / "schedule.sqlite3"),
        OfflineSwingRunFence(env.tmp / "single-writer.sqlite3"), controller,
        clock=env.clock)
    result = restarted.run_due(owner="worker-b", entry=env.entry(), entry_quote=quote)
    assert result.status == "RECOVERY_REQUIRED"
    assert route.calls == []
    fence.finish(token, at=NOW, safe=False, outcome="CRASH_SIMULATED")
    assert restarted.run_due(owner="worker-b").status == "RECOVERY_REQUIRED"
    assert fence.state() == "UNRESOLVED"
    assert [method for method, _ in route.calls].count("POST") == 0


def test_sd152_missing_fresh_send_quote_halts_without_order(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    proposal = env.entry()
    assert isinstance(proposal, EntryProposal)
    result = service.run_due(owner="worker-a", entry=proposal, entry_quote=None)
    assert result.status == "HALTED"
    assert env.ledger.kill_switch_engaged()
    assert fence.state() == "UNRESOLVED"
    assert [method for method, _ in route.calls].count("POST") == 0
    assert service.run_due(owner="worker-b").status == "RECOVERY_REQUIRED"


def test_sd140_out_of_session_and_non_swing_proposals_cannot_send(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    env.clock.now = NOW - timedelta(hours=1)
    result = controller.tick()
    assert result.status == "OUT_OF_SESSION"
    assert route.calls == []
    env.clock.now = NOW
    proposal = env.entry()
    assert isinstance(proposal, EntryProposal)
    from dataclasses import replace
    refused = controller.tick(entry=replace(proposal, track="DAY"), entry_quote=quote)
    assert refused.status == "NO_TRADE"
    assert route.calls == []


def test_sd152_no_signal_day_keeps_broker_locked(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    outcome = service.run_due(owner="worker-a")
    assert outcome.status == "NO_TRADE"
    assert outcome.report()["execution_release"] == "ETORO_DEMO_NOT_RELEASED"
    assert fence.state() == "IDLE"
    assert route.calls == []


def test_sd141_durable_fence_refuses_concurrent_workers(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    second_handle = OfflineSwingRunFence(env.tmp / "single-writer.sqlite3")
    slot = slots_for(scheduler.jobs["swing_review"], NOW.date())[0]
    def take(handle):
        return handle.acquire(slot, owner="concurrent-worker", at=NOW)
    with ThreadPoolExecutor(max_workers=2) as pool:
        tokens = list(pool.map(take, [fence, second_handle]))
    assert sum(token is not None for token in tokens) == 1
    assert route.calls == []
    assert fence.state() == "RUNNING"
    fence.finish(next(token for token in tokens if token is not None),
                 at=NOW, safe=False, outcome="CONCURRENCY_TEST")
    assert fence.state() == "UNRESOLVED"


def test_sd141_ambiguous_close_post_halts_worker_without_replay(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    proposal = env.entry()
    assert service.run_due(owner="worker-a", entry=proposal, entry_quote=quote).status == "ENTRY_CONFIRMED"
    env.clock.now = NOW + timedelta(hours=2, minutes=35)
    route.lose_next_response = True
    result = service.run_due(
        owner="worker-b",
        planning_bids=(seal_bid(signer, env, "455"),),
        execution_bids={MSFT: seal_bid(signer, env, "455")},
    )
    assert result.status == "HALTED"
    assert fence.state() == "UNRESOLVED"
    assert env.ledger.kill_switch_engaged()
    assert [method for method, _ in route.calls].count("POST") == 2
    restarted = OfflineSwingScheduledService(
        SchedulerStore(env.tmp / "schedule.sqlite3"),
        OfflineSwingRunFence(env.tmp / "single-writer.sqlite3"), controller,
        clock=env.clock)
    assert restarted.run_due(owner="worker-c").status == "RECOVERY_REQUIRED"
    assert [method for method, _ in route.calls].count("POST") == 2


def test_sd141_anchor_outage_before_exit_never_sends_close(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    proposal = env.entry()
    assert service.run_due(owner="worker-a", entry=proposal, entry_quote=quote).status == "ENTRY_CONFIRMED"
    env.clock.now = NOW + timedelta(hours=2, minutes=35)
    env.gateway_audit_anchor.unavailable = True
    result = service.run_due(
        owner="worker-b",
        planning_bids=(seal_bid(signer, env, "455"),),
        execution_bids={MSFT: seal_bid(signer, env, "455")},
    )
    assert result.status == "HALTED"
    assert fence.state() == "UNRESOLVED"
    assert env.ledger.kill_switch_engaged()
    assert [method for method, _ in route.calls].count("POST") == 1
    assert lineage.owned(880_001)["state"] == "OPEN"


def test_sd140_swing_review_uses_exchange_early_close_not_regular_close(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    half_day = date(2026, 11, 27)
    session = session_for(half_day)
    assert session is not None and session.early_close
    assert session.close_utc == datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    slots = slots_for(scheduler.jobs["swing_review"], half_day)
    assert slots[-1] == datetime(2026, 11, 27, 17, 30, tzinfo=UTC)
    assert route.calls == []



def test_sd152_read_only_health_and_stale_alert_never_releases_worker(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    idle = service.health(now=NOW).report()
    assert idle["state"] == "IDLE"
    assert idle["execution_release"] == "ETORO_DEMO_NOT_RELEASED"
    assert idle["broker_route"] == "SIMULATED_LOCAL"
    assert idle["alerts"] == []
    slot = slots_for(scheduler.jobs["swing_review"], NOW.date())[0]
    token = fence.acquire(slot, owner="worker-a", at=NOW)
    assert token is not None
    current = service.health(now=NOW + timedelta(seconds=30))
    assert current.state == "RUNNING"
    assert current.owner == "worker-a"
    assert current.heartbeat_age_seconds == 30
    assert current.alerts == ("EXCLUSIVE_WORKER_ACTIVE",)
    stale = service.health(now=NOW + timedelta(seconds=121))
    assert "STALE_RUNNING_HEARTBEAT_RECONCILIATION_REQUIRED" in stale.alerts
    assert fence.state() == "RUNNING"
    assert fence.acquire(slot, owner="worker-b", at=NOW + timedelta(minutes=30)) is None
    assert route.calls == []


def test_sd152_heartbeat_requires_original_token_owner_and_monotonic_clock(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    slot = slots_for(scheduler.jobs["swing_review"], NOW.date())[0]
    token = fence.acquire(slot, owner="worker-a", at=NOW)
    assert token is not None
    with pytest.raises(OfflineRunnerRefused, match="identity"):
        fence.heartbeat(token, owner="worker-b", at=NOW + timedelta(seconds=10))
    with pytest.raises(OfflineRunnerRefused, match="fence"):
        fence.heartbeat("forged-token", owner="worker-a", at=NOW + timedelta(seconds=10))
    fence.heartbeat(token, owner="worker-a", at=NOW + timedelta(seconds=10))
    assert service.health(now=NOW + timedelta(seconds=15)).heartbeat_age_seconds == 5
    with pytest.raises(OfflineRunnerRefused, match="regressed"):
        fence.heartbeat(token, owner="worker-a", at=NOW + timedelta(seconds=9))
    assert fence.state() == "RUNNING"
    with pytest.raises(OfflineRunnerRefused, match="regressed"):
        fence.finish(token, at=NOW, safe=True, outcome="NO_TRADE")
    assert fence.state() == "RUNNING"
    fence.finish(token, at=NOW + timedelta(seconds=11),
                 safe=False, outcome="INCIDENT")
    assert service.health(now=NOW + timedelta(seconds=12)).alerts == (
        "MANUAL_RECONCILIATION_REQUIRED_NO_AUTOMATIC_TAKEOVER",
    )
    assert route.calls == []


def test_sd152_durable_missing_run_record_prevents_false_safe_release(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    slot = slots_for(scheduler.jobs["swing_review"], NOW.date())[0]
    token = fence.acquire(slot, owner="worker-a", at=NOW)
    assert token is not None
    with sqlite3.connect(env.tmp / "single-writer.sqlite3") as conn:
        conn.execute("DELETE FROM offline_swing_runs WHERE token=?", (token,))
    with pytest.raises(OfflineRunnerRefused, match="matching run record"):
        service.health(now=NOW)
    with pytest.raises(OfflineRunnerRefused, match="durable run row missing"):
        fence.finish(token, at=NOW, safe=True, outcome="NO_TRADE")
    assert fence.state() == "RUNNING"
    assert route.calls == []


def test_sd152_successful_tick_reports_heartbeat_without_new_network_capability(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    result = service.run_due(owner="heartbeat-worker")
    assert result.status == "NO_TRADE"
    assert service.health(now=NOW).state == "IDLE"
    assert len(fence.history()) == 1
    assert route.calls == []


def test_sd152_inspection_uses_only_durable_local_evidence(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    before = service.inspect(now=NOW)
    assert before["policy_open_positions"] == 0
    assert before["durable_owned_open_positions"] == 0
    assert before["protected_original_positions"] == 4
    assert before["broker_account_verified"] is False
    assert before["execution_release"] == "ETORO_DEMO_NOT_RELEASED"
    assert route.calls == []
    allow_fake_schedule(scheduler)
    proposal = env.entry()
    assert service.run_due(owner="worker-a", entry=proposal,
                           entry_quote=quote).status == "ENTRY_CONFIRMED"
    post_count = [method for method, _ in route.calls].count("POST")
    observed = service.inspect(now=NOW + timedelta(seconds=1))
    assert observed["policy_open_positions"] == 1
    assert observed["durable_owned_open_positions"] == 1
    assert observed["durable_unknown_order_count"] == 0
    assert observed["durable_pending_submit_count"] == 0
    assert observed["policy_kill_switch"] is False
    assert observed["fence"]["state"] == "IDLE"
    assert [method for method, _ in route.calls].count("POST") == post_count


def test_sd152_inspection_surfaces_ambiguous_close_without_broker_calls(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    proposal = env.entry()
    assert service.run_due(owner="worker-a", entry=proposal,
                           entry_quote=quote).status == "ENTRY_CONFIRMED"
    env.clock.now = NOW + timedelta(hours=2, minutes=35)
    route.lose_next_response = True
    result = service.run_due(
        owner="worker-b",
        planning_bids=(seal_bid(signer, env, "455"),),
        execution_bids={MSFT: seal_bid(signer, env, "455")},
    )
    assert result.status == "HALTED"
    call_count = len(route.calls)
    observed = service.inspect(now=env.clock.now + timedelta(seconds=1))
    assert observed["policy_kill_switch"] is True
    assert observed["fence"]["state"] == "UNRESOLVED"
    assert observed["durable_unknown_order_count"] == 1
    assert "ORDER_LINEAGE_RECONCILIATION_REQUIRED" in observed["alerts"]
    assert "MANUAL_RECONCILIATION_REQUIRED_NO_AUTOMATIC_TAKEOVER" in observed["alerts"]
    assert "POLICY_KILL_SWITCH_ENGAGED" in observed["alerts"]
    assert len(route.calls) == call_count


def test_sd152_tampered_idle_fence_cannot_allow_a_new_tick(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    # Contradictory local fence metadata is an incident, not a free slot.
    with sqlite3.connect(env.tmp / "single-writer.sqlite3") as conn:
        conn.execute(
            "UPDATE offline_swing_single_writer SET token='unexpected' WHERE id=1"
        )
    with pytest.raises(OfflineRunnerRefused, match="identity conflict"):
        fence.state()
    with pytest.raises(OfflineRunnerRefused, match="identity conflict"):
        service.health(now=NOW)
    with pytest.raises(OfflineRunnerRefused, match="identity conflict"):
        service.run_due(owner="worker-a", entry=env.entry(), entry_quote=quote)
    assert route.calls == []



def test_sd141_recovery_dossier_is_read_only_and_never_grants_order_authority(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    count = len(route.calls)
    dossier = service.recovery_dossier(now=NOW)
    assert dossier["status"] == "NO_LOCAL_UNCERTAIN_ORDERS"
    assert dossier["uncertain_orders"] == []
    assert dossier["automatic_get_allowed"] is False
    assert dossier["automatic_post_allowed"] is False
    assert dossier["clear_halt_allowed"] is False
    assert dossier["broker_account_verified"] is False
    assert dossier["execution_release"] == "ETORO_DEMO_NOT_RELEASED"
    assert len(route.calls) == count


def test_sd141_unknown_open_is_reference_get_only_and_does_not_repost(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    proposal = env.entry()
    route.lose_next_response = True
    result = service.run_due(owner="worker-a", entry=proposal, entry_quote=quote)
    assert result.status == "HALTED"
    before = tuple(route.calls)
    dossier = service.recovery_dossier(now=env.clock.now)
    assert dossier["status"] == "HALTED_REVIEW_REQUIRED"
    assert dossier["fence"]["state"] == "UNRESOLVED"
    assert len(dossier["uncertain_orders"]) == 1
    item = dossier["uncertain_orders"][0]
    assert item["kind"] == "OPEN"
    assert item["durable_state"] == "OUTCOME_UNKNOWN"
    assert item["accepted_order_id"] is None
    assert item["review_action"] == "ORDER_REFERENCE_LOOKUP_GET_ONLY"
    assert item["signed_read_and_audit_required"] is True
    assert item["automatic_post_allowed"] is False
    assert tuple(route.calls) == before
    assert [m for m, _ in before].count("POST") == 1


def test_sd141_unknown_close_with_no_id_requires_whole_account_review(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    entry = env.entry()
    assert service.run_due(owner="worker-a", entry=entry,
                           entry_quote=quote).status == "ENTRY_CONFIRMED"
    env.clock.now = NOW + timedelta(hours=2, minutes=35)
    route.lose_next_response = True
    result = service.run_due(
        owner="worker-b",
        planning_bids=(seal_bid(signer, env, "455"),),
        execution_bids={MSFT: seal_bid(signer, env, "455")},
    )
    assert result.status == "HALTED"
    before = tuple(route.calls)
    dossier = service.recovery_dossier(now=env.clock.now)
    items = dossier["uncertain_orders"]
    assert len(items) == 1
    assert items[0]["kind"] == "CLOSE"
    assert items[0]["accepted_order_id"] is None
    assert items[0]["review_action"] == "SIGNED_WHOLE_ACCOUNT_RECONCILIATION_ONLY"
    assert dossier["clear_halt_allowed"] is False
    assert tuple(route.calls) == before
    assert [m for m, _ in before].count("POST") == 2


def test_sd141_accepted_close_needs_close_info_and_pnl_not_repost(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    entry = env.entry()
    assert service.run_due(owner="worker-a", entry=entry,
                           entry_quote=quote).status == "ENTRY_CONFIRMED"
    env.clock.now = NOW + timedelta(hours=2, minutes=35)
    original_send = route.send
    def delayed_close_info(method, request_path, **kwargs):
        if request_path == DEMO_CLOSE_INFO_PATH.format(order_id=770_002):
            raise TransportNotFound("accepted close not yet visible")
        return original_send(method, request_path, **kwargs)
    route.send = delayed_close_info
    try:
        result = service.run_due(
            owner="worker-b",
            planning_bids=(seal_bid(signer, env, "455"),),
            execution_bids={MSFT: seal_bid(signer, env, "455")},
        )
        assert result.status == "HALTED"
        before = tuple(route.calls)
        dossier = service.recovery_dossier(now=env.clock.now)
        assert len(dossier["uncertain_orders"]) == 1
        item = dossier["uncertain_orders"][0]
        assert item["kind"] == "CLOSE"
        assert item["durable_state"] == "ACCEPTED"
        assert item["accepted_order_id"] == 770_002
        assert item["review_action"] == "SIGNED_CLOSE_INFO_THEN_ACCOUNT_GET_ONLY"
        assert tuple(route.calls) == before
        assert [m for m, _ in before].count("POST") == 2
    finally:
        route.send = original_send


def test_sd152_durable_uncertain_order_blocks_fresh_idle_swing_run(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    # Reproduce an orphaned durable reservation with an otherwise IDLE
    # scheduler/fence: no automatically repeated or unrelated new opening.
    lineage.record_pending(
        reference_id="bcbf47e9-0a34-463e-9b8b-648f999eb2ee",
        kind="OPEN", intent_id="bcbf47e90a34463e9b8b648f999eb2ee",
        book_id="etoro-demo:tradingagents", instrument_id=1004,
        units=None, limit_rate=None, position_id=None,
    )
    candidate = env.entry()
    result = service.run_due(owner="worker-a", entry=candidate, entry_quote=quote)
    assert result.status == "RECOVERY_REQUIRED"
    assert "reconciliation" in result.detail
    assert scheduler.history("swing_review") == ()
    assert fence.state() == "IDLE"
    assert route.calls == []


def test_sd141_open_broker_lineage_before_policy_crash_blocks_idle_runner(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    proposal = env.entry()
    original_resolve = controller.runtime.resolve

    def crash_between_open_ledgers(_evidence):
        raise RuntimeError("crash after durable broker position, before policy resolution")

    controller.runtime.resolve = crash_between_open_ledgers
    try:
        from sidedeck.application.sd138_autonomous_order_adapter import SD138Refused
        with pytest.raises(SD138Refused, match="stopped for reconciliation"):
            controller.adapter.submit_entry(proposal, quote=quote)
    finally:
        controller.runtime.resolve = original_resolve

    assert len(lineage.owned_positions()) == 1
    assert env.ledger.state().entries[proposal.reference_id].outcome is None
    assert env.ledger.kill_switch_engaged()
    before = tuple(route.calls)
    dossier = service.recovery_dossier(now=NOW)
    assert dossier["status"] == "HALTED_REVIEW_REQUIRED"
    assert any(
        item["review_action"] == "DURABLE_OPEN_POLICY_LEDGER_MISMATCH_MANUAL_REVIEW"
        for item in dossier["uncertain_orders"]
    )
    assert "CROSS_LEDGER_RECONCILIATION_REQUIRED" in service.inspect(now=NOW)["alerts"]
    assert service.run_due(owner="new-worker").status == "RECOVERY_REQUIRED"
    assert fence.state() == "IDLE"
    assert scheduler.history("swing_review") == ()
    assert tuple(route.calls) == before


def test_sd141_filled_close_broker_ledger_before_policy_crash_blocks_idle_runner(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    entry = env.entry()
    controller.adapter.submit_entry(entry, quote=quote)
    plan = controller.runtime.plan_exits(bids=(seal_bid(signer, env, "455"),))
    assert len(plan.exits) == 1
    original_resolve = controller.runtime.resolve

    def crash_between_close_ledgers(_evidence):
        raise RuntimeError("crash after durable close, before policy resolution")

    controller.runtime.resolve = crash_between_close_ledgers
    try:
        from sidedeck.application.sd138_autonomous_order_adapter import SD138Refused
        with pytest.raises(SD138Refused, match="stopped for reconciliation"):
            controller.adapter.submit_exit(
                plan.exits[0], quote=seal_bid(signer, env, "455"),
            )
    finally:
        controller.runtime.resolve = original_resolve

    assert lineage.owned(880_001)["state"] == "CLOSED"
    assert env.ledger.state().exits[plan.exits[0].reference_id].outcome is None
    assert env.ledger.kill_switch_engaged()
    before = tuple(route.calls)
    dossier = service.recovery_dossier(now=NOW)
    assert any(
        item["review_action"] == "DURABLE_CLOSE_POLICY_LEDGER_MISMATCH_MANUAL_REVIEW"
        for item in dossier["uncertain_orders"]
    )
    assert "CROSS_LEDGER_RECONCILIATION_REQUIRED" in service.inspect(now=NOW)["alerts"]
    assert service.run_due(owner="new-worker").status == "RECOVERY_REQUIRED"
    assert scheduler.history("swing_review") == ()
    assert tuple(route.calls) == before
    assert [method for method, _ in route.calls].count("POST") == 2


def test_sd141_normal_open_and_close_recovery_dossier_has_no_ledger_discrepancies(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    proposal = env.entry()
    controller.adapter.submit_entry(proposal, quote=quote)
    assert service.recovery_dossier(now=NOW)["uncertain_orders"] == []
    plan = controller.runtime.plan_exits(bids=(seal_bid(signer, env, "455"),))
    controller.adapter.submit_exit(plan.exits[0], quote=seal_bid(signer, env, "455"))
    assert service.recovery_dossier(now=NOW)["uncertain_orders"] == []
    assert "CROSS_LEDGER_RECONCILIATION_REQUIRED" not in service.inspect(now=NOW)["alerts"]
    assert [method for method, _ in route.calls].count("POST") == 2


def test_sd140_expiry_alerts_with_open_position_never_authorize_a_close(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    proposal = env.entry()
    controller.adapter.submit_entry(proposal, quote=quote)
    before = tuple(route.calls)
    env.clock.now = datetime(2026, 11, 6, 15, 0, tzinfo=UTC)
    status = service.inspect(now=env.clock.now)
    assert "SWING_POLICY_EXPIRY_WITHIN_24H_OPEN_POSITION" in status["alerts"]
    assert "PROTECTIVE_GRANT_NOT_CONFIGURED_OPEN_POSITION" in status["alerts"]
    assert status["broker_account_verified"] is False
    env.clock.now = datetime(2026, 11, 9, 15, 0, tzinfo=UTC)
    overdue = service.inspect(now=env.clock.now)
    assert "SWING_POLICY_EXPIRED_WITH_OPEN_POSITION" in overdue["alerts"]
    assert "PROTECTIVE_GRANT_NOT_CONFIGURED_OPEN_POSITION" in overdue["alerts"]
    assert tuple(route.calls) == before
    assert lineage.owned(880_001)["state"] == "OPEN"


def test_sd140_protective_grant_expiry_alert_is_unverified_and_read_only(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    proposal = env.entry()
    controller.adapter.submit_entry(proposal, quote=quote)
    from test_sd063_autonomous_demo_policy import _grant
    from sidedeck.application.sd063_autonomous_demo_policy import protective_subject
    import json
    import uuid
    grant = _grant(
        env.policy, grant_id=str(uuid.uuid4()),
        subject_digest=protective_subject(env.policy),
        not_before=NOW, expires_at=datetime(2026, 11, 6, 20, 30, tzinfo=UTC),
        purpose="offline expiry visibility; no authorised broker calls",
    )
    gateway = controller.adapter._gate
    gateway._protective_grant = (json.loads(grant.canonical()), f"sig:{grant.digest()}")
    env.clock.now = datetime(2026, 11, 6, 15, 0, tzinfo=UTC)
    before = tuple(route.calls)
    status = service.inspect(now=env.clock.now)
    assert "SWING_POLICY_EXPIRY_WITHIN_24H_OPEN_POSITION" in status["alerts"]
    assert "PROTECTIVE_GRANT_EXPIRY_WITHIN_24H_UNVERIFIED" in status["alerts"]
    assert "PROTECTIVE_GRANT_SIGNATURE_AND_REVOCATION_CHECK_REQUIRED" in status["alerts"]
    assert status["execution_release"] == "ETORO_DEMO_NOT_RELEASED"
    assert tuple(route.calls) == before
    gateway._protective_grant = ({"expires_at": "not-a-time"}, "untrusted-signature")
    malformed = service.inspect(now=env.clock.now)
    assert "PROTECTIVE_GRANT_EXPIRY_DOCUMENT_UNREADABLE" in malformed["alerts"]
    assert "PROTECTIVE_GRANT_SIGNATURE_AND_REVOCATION_CHECK_REQUIRED" in malformed["alerts"]
    assert tuple(route.calls) == before


def test_sd152_actual_child_process_exit_leaves_durable_run_fenced(setup):
    """A genuine OS child exit (not an exception) cannot release a RUNNING fence."""
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    slot = slots_for(scheduler.jobs["swing_review"], NOW.date())[0]
    child_code = """
import os
import sys
sys.path.insert(0, sys.argv.pop(1))  # isolated src-layout checkout, no installation
from datetime import datetime
from pathlib import Path
from sidedeck.application.sd152_offline_swing_runner import OfflineSwingRunFence
path, slot, at = sys.argv[1:]
fence = OfflineSwingRunFence(Path(path))
token = fence.acquire(datetime.fromisoformat(slot), owner="hard-exit-worker",
                      at=datetime.fromisoformat(at))
if not token:
    raise SystemExit(3)
os._exit(77)
"""
    crashed = subprocess.run(
        [sys.executable, "-c", child_code, str(Path(__file__).resolve().parents[1] / "src"),
         str(env.tmp / "single-writer.sqlite3"), slot.isoformat(), NOW.isoformat()],
        check=False, capture_output=True, text=True, timeout=15,
    )
    assert crashed.returncode == 77, crashed.stderr
    restarted_fence = OfflineSwingRunFence(env.tmp / "single-writer.sqlite3")
    assert restarted_fence.state() == "RUNNING"
    stale = restarted_fence.health(now=NOW + timedelta(minutes=5))
    assert "STALE_RUNNING_HEARTBEAT_RECONCILIATION_REQUIRED" in stale.alerts
    restarted = OfflineSwingScheduledService(
        SchedulerStore(env.tmp / "schedule.sqlite3"),
        restarted_fence, controller, clock=env.clock,
    )
    assert restarted.run_due(owner="replacement").status == "RECOVERY_REQUIRED"
    assert restarted_fence.acquire(slot, owner="replacement", at=NOW) is None
    assert scheduler.history("swing_review") == ()
    assert route.calls == []


def test_sd141_actual_child_process_exits_after_open_lineage_without_policy_result(setup):
    """Durable accepted broker-shaped fixture persists across an abrupt OS exit.

    No broker POST is sent in this test: a child writes the same durable
    SD-036 state that a broker-shaped accepted-open/lookup would have recorded,
    then dies without touching SD-063 policy outcome.
    """
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    proposal = env.entry()
    request = controller.adapter._open_request(proposal)
    child_code = """
import os
import sys
sys.path.insert(0, sys.argv.pop(1))  # isolated src-layout checkout, no installation
from decimal import Decimal
from sidedeck.application.sd036_etoro_demo_desk import EtoroDemoLineage
db, ref, intent, instrument, units, limit = sys.argv[1:]
lineage = EtoroDemoLineage(
    db, baseline_position_ids=(11, 12, 13, 14),
    baseline_order_ids=(9011, 9012, 9013, 9014),
)
lineage.record_pending(
    reference_id=ref, kind="OPEN", intent_id=intent,
    book_id="etoro-demo:tradingagents", instrument_id=int(instrument),
    units=Decimal(units), limit_rate=Decimal(limit), position_id=None,
)
lineage.set_state(ref, "ACCEPTED", order_id=770001)
lineage.register_position(
    reference_id=ref, order_id=770001,
    book_id="etoro-demo:tradingagents", instrument_id=int(instrument),
    position_id=880001, units=Decimal(units), remaining=Decimal(units),
)
os._exit(78)
"""
    crashed = subprocess.run(
        [sys.executable, "-c", child_code, str(Path(__file__).resolve().parents[1] / "src"),
         str(env.tmp / "sd138-lineage.sqlite3"), request.reference_id,
         proposal.reference_id, str(request.instrument_id),
         str(request.units), str(request.limit_rate)],
        check=False, capture_output=True, text=True, timeout=15,
    )
    assert crashed.returncode == 78, crashed.stderr
    assert lineage.order(request.reference_id)["state"] == "ACCEPTED"
    assert lineage.owned(880001)["state"] == "OPEN"
    assert env.ledger.state().entries[proposal.reference_id].outcome is None
    restarted = OfflineSwingScheduledService(
        SchedulerStore(env.tmp / "schedule.sqlite3"),
        OfflineSwingRunFence(env.tmp / "single-writer.sqlite3"),
        controller, clock=env.clock,
    )
    dossier = restarted.recovery_dossier(now=NOW)
    assert any(
        row["review_action"] == "DURABLE_OPEN_POLICY_LEDGER_MISMATCH_MANUAL_REVIEW"
        for row in dossier["uncertain_orders"]
    )
    assert restarted.run_due(owner="replacement").status == "RECOVERY_REQUIRED"
    assert restarted.fence.state() == "IDLE"
    assert route.calls == []
    assert scheduler.history("swing_review") == ()


def test_sd141_actual_child_exit_after_durable_close_before_policy_resolution(setup):
    """Hard-exit a child after SD-036 close settlement, before SD-063 result.

    The close is synthetic persisted lineage, not broker execution evidence.
    After termination the parent must detect the mismatch and refuse to send.
    """
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    entry = env.entry()
    controller.adapter.submit_entry(entry, quote=quote)
    exit_plan = controller.runtime.plan_exits(bids=(seal_bid(signer, env, "455"),))
    assert len(exit_plan.exits) == 1
    close = exit_plan.exits[0]
    parent_requests = tuple(route.calls)
    child_code = """
import os
import sys
sys.path.insert(0, sys.argv.pop(1))
from decimal import Decimal
from sidedeck.application.sd036_etoro_demo_desk import EtoroDemoLineage
db, ref, intent, instrument, units = sys.argv[1:]
lineage = EtoroDemoLineage(
    db, baseline_position_ids=(11, 12, 13, 14),
    baseline_order_ids=(9011, 9012, 9013, 9014),
)
lineage.record_pending(
    reference_id=ref, kind="CLOSE", intent_id=intent,
    book_id="etoro-demo:tradingagents", instrument_id=int(instrument),
    units=Decimal(units), limit_rate=None, position_id=880001,
)
lineage.set_state(ref, "ACCEPTED", order_id=770002)
lineage.reconcile_full_close(
    reference_id=ref, order_id=770002, position_id=880001,
    closed_units=Decimal(units),
)
os._exit(79)
"""
    child = subprocess.run(
        [sys.executable, "-c", child_code,
         str(Path(__file__).resolve().parents[1] / "src"),
         str(env.tmp / "sd138-lineage.sqlite3"),
         str(UUID(hex=close.reference_id)), close.reference_id,
         str(close.etoro_instrument_id), str(close.units)],
        check=False, capture_output=True, text=True, timeout=15,
    )
    assert child.returncode == 79, child.stderr
    assert lineage.owned(880001)["state"] == "CLOSED"
    assert env.ledger.state().exits[close.reference_id].outcome is None
    resumed = OfflineSwingScheduledService(
        SchedulerStore(env.tmp / "schedule.sqlite3"),
        OfflineSwingRunFence(env.tmp / "single-writer.sqlite3"),
        controller, clock=env.clock,
    )
    dossier = resumed.recovery_dossier(now=NOW)
    assert any(
        item["review_action"] == "DURABLE_CLOSE_POLICY_LEDGER_MISMATCH_MANUAL_REVIEW"
        for item in dossier["uncertain_orders"]
    )
    assert resumed.run_due(owner="replacement").status == "RECOVERY_REQUIRED"
    assert resumed.fence.state() == "IDLE"
    assert tuple(route.calls) == parent_requests
    assert [method for method, _ in route.calls].count("POST") == 1
    assert scheduler.history("swing_review") == ()


@pytest.mark.parametrize(
    ("column", "value"), [
        ("units", "999"),
        ("remaining_units", "999"),
        ("book_id", "etoro-demo:ai-trading"),
        ("instrument_id", 9988),
    ],
)
def test_sd141_tampered_owned_open_facts_block_idle_restart(setup, column, value):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    entry = env.entry()
    controller.adapter.submit_entry(entry, quote=quote)
    original_calls = tuple(route.calls)
    # A forged local SQLite value cannot be assumed to be a genuine broker
    # event even if the opening order and position IDs remain unchanged.
    assert column in {"units", "remaining_units", "book_id", "instrument_id"}
    with sqlite3.connect(env.tmp / "sd138-lineage.sqlite3") as conn:
        conn.execute(
            f"UPDATE etoro_demo_owned_positions SET {column}=? WHERE position_id=880001",
            (value,),
        )
    dossier = service.recovery_dossier(now=NOW)
    assert any(
        item["review_action"] == "DURABLE_OPEN_POLICY_LEDGER_MISMATCH_MANUAL_REVIEW"
        for item in dossier["uncertain_orders"]
    )
    assert "CROSS_LEDGER_RECONCILIATION_REQUIRED" in service.inspect(now=NOW)["alerts"]
    assert service.run_due(owner="new-worker").status == "RECOVERY_REQUIRED"
    assert fence.state() == "IDLE"
    assert scheduler.history("swing_review") == ()
    assert tuple(route.calls) == original_calls


@pytest.mark.parametrize(
    ("column", "value"), [
        ("filled_units", "999"),
        ("units", "999"),
        ("book_id", "etoro-demo:ai-trading"),
        ("instrument_id", 9988),
    ],
)
def test_sd141_tampered_full_close_lineage_blocks_idle_restart(setup, column, value):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    entry = env.entry()
    controller.adapter.submit_entry(entry, quote=quote)
    plan = controller.runtime.plan_exits(bids=(seal_bid(signer, env, "455"),))
    assert len(plan.exits) == 1
    controller.adapter.submit_exit(plan.exits[0], quote=seal_bid(signer, env, "455"))
    assert service.recovery_dossier(now=NOW)["uncertain_orders"] == []
    original_calls = tuple(route.calls)
    assert column in {"filled_units", "units", "book_id", "instrument_id"}
    with sqlite3.connect(env.tmp / "sd138-lineage.sqlite3") as conn:
        conn.execute(
            f"UPDATE etoro_demo_lineage_orders SET {column}=? "
            "WHERE kind='CLOSE' AND state='FILLED'",
            (value,),
        )
    dossier = service.recovery_dossier(now=NOW)
    assert any(
        item["review_action"] == "DURABLE_CLOSE_POLICY_LEDGER_MISMATCH_MANUAL_REVIEW"
        for item in dossier["uncertain_orders"]
    )
    assert "CROSS_LEDGER_RECONCILIATION_REQUIRED" in service.inspect(now=NOW)["alerts"]
    assert service.run_due(owner="new-worker").status == "RECOVERY_REQUIRED"
    assert scheduler.history("swing_review") == ()
    assert tuple(route.calls) == original_calls


def test_sd141_orphan_durable_owned_position_cannot_rearm_idle_runner(setup):
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    proposal = env.entry()
    controller.adapter.submit_entry(proposal, quote=quote)
    before = tuple(route.calls)
    with sqlite3.connect(env.tmp / "sd138-lineage.sqlite3") as conn:
        conn.execute(
            "INSERT INTO etoro_demo_owned_positions "
            "(position_id,reference_id,order_id,book_id,instrument_id,"
            "units,remaining_units,state,recorded_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (887001, "orphan-reference", 779901,
             "etoro-demo:tradingagents", 1004, "1", "1",
             "OPEN", NOW.isoformat()),
        )
    dossier = service.recovery_dossier(now=NOW)
    assert any(
        item["review_action"] == "ORPHAN_OWNED_POSITION_MANUAL_REVIEW"
        and item["owned_position_id"] == 887001
        for item in dossier["uncertain_orders"]
    )
    assert service.run_due(owner="replacement").status == "RECOVERY_REQUIRED"
    assert "ORDER_LINEAGE_RECONCILIATION_REQUIRED" in service.inspect(now=NOW)["alerts"]
    assert fence.state() == "IDLE"
    assert scheduler.history("swing_review") == ()
    assert tuple(route.calls) == before


def test_sd152_twenty_restart_attempts_do_not_repeat_simulated_entry(setup):
    """Crash/restart-style repeated construction cannot replay a consumed slot."""
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    proposal = env.entry()
    assert isinstance(proposal, EntryProposal)
    first = service.run_due(owner="initial-worker", entry=proposal, entry_quote=quote)
    assert first.status == "ENTRY_CONFIRMED"
    original_posts = [call for call in route.calls if call[0] == "POST"]
    assert len(original_posts) == 1
    for attempt in range(20):
        restarted = OfflineSwingScheduledService(
            SchedulerStore(env.tmp / "schedule.sqlite3"),
            OfflineSwingRunFence(env.tmp / "single-writer.sqlite3"),
            controller, clock=env.clock,
        )
        result = restarted.run_due(
            owner=f"restart-{attempt}", entry=proposal, entry_quote=quote,
        )
        assert result.status == "NO_DUE_SLOT"
        assert result.execution_release == "ETORO_DEMO_NOT_RELEASED"
        assert [call for call in route.calls if call[0] == "POST"] == original_posts
        assert fence.state() == "IDLE"
    assert len(scheduler.history("swing_review")) == 1


def test_sd152_repeated_restart_after_unresolved_fence_never_reposts(setup):
    """A durable unresolved simulated worker cannot be rearmed by later slots."""
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    slot = slots_for(scheduler.jobs["swing_review"], NOW.date())[0]
    token = fence.acquire(slot, owner="crashed-worker", at=NOW)
    assert token is not None
    fence.finish(token, at=NOW, safe=False, outcome="SIMULATED_CRASH")
    proposal = env.entry()
    assert isinstance(proposal, EntryProposal)
    for i in range(12):
        env.clock.now = NOW + timedelta(minutes=i * 10)
        restarted = OfflineSwingScheduledService(
            SchedulerStore(env.tmp / "schedule.sqlite3"),
            OfflineSwingRunFence(env.tmp / "single-writer.sqlite3"),
            controller, clock=env.clock,
        )
        outcome = restarted.run_due(owner=f"restart-{i}", entry=proposal, entry_quote=quote)
        assert outcome.status == "RECOVERY_REQUIRED"
        assert outcome.execution_release == "ETORO_DEMO_NOT_RELEASED"
        assert restarted.fence.state() == "UNRESOLVED"
    assert not any(method == "POST" for method, _ in route.calls)


def test_sd152_ambiguous_close_ten_restarts_preserve_single_exit_post(setup):
    """Unknown simulated close outcome must not cause another close on restart."""
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    proposal = env.entry()
    assert isinstance(proposal, EntryProposal)
    assert service.run_due(owner="entry-worker", entry=proposal,
                           entry_quote=quote).status == "ENTRY_CONFIRMED"
    env.clock.now = NOW + timedelta(hours=2, minutes=35)
    route.lose_next_response = True
    first_close = service.run_due(
        owner="exit-worker",
        planning_bids=(seal_bid(signer, env, "455"),),
        execution_bids={MSFT: seal_bid(signer, env, "455")},
    )
    assert first_close.status == "HALTED"
    assert fence.state() == "UNRESOLVED"
    assert env.ledger.kill_switch_engaged()
    expected_calls = tuple(route.calls)
    assert [method for method, _ in expected_calls].count("POST") == 2
    for i in range(10):
        env.clock.now = NOW + timedelta(hours=2, minutes=35 + i)
        restarted = OfflineSwingScheduledService(
            SchedulerStore(env.tmp / "schedule.sqlite3"),
            OfflineSwingRunFence(env.tmp / "single-writer.sqlite3"),
            controller, clock=env.clock,
        )
        result = restarted.run_due(owner=f"restarted-close-{i}")
        assert result.status == "RECOVERY_REQUIRED"
        assert result.execution_release == "ETORO_DEMO_NOT_RELEASED"
        assert restarted.fence.state() == "UNRESOLVED"
        assert tuple(route.calls) == expected_calls
    assert env.ledger.kill_switch_engaged()


def test_sd152_close_ledger_mismatch_blocks_twelve_restarts_without_replay(setup):
    """Durable filled close without policy resolution remains review-only."""
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    entry = env.entry()
    controller.adapter.submit_entry(entry, quote=quote)
    plan = controller.runtime.plan_exits(bids=(seal_bid(signer, env, "455"),))
    assert len(plan.exits) == 1
    original_resolve = controller.runtime.resolve

    def interrupted_resolution(_evidence):
        raise RuntimeError("simulated crash between broker ledger and policy ledger")

    controller.runtime.resolve = interrupted_resolution
    try:
        from sidedeck.application.sd138_autonomous_order_adapter import SD138Refused
        with pytest.raises(SD138Refused, match="stopped for reconciliation"):
            controller.adapter.submit_exit(plan.exits[0], quote=seal_bid(signer, env, "455"))
    finally:
        controller.runtime.resolve = original_resolve
    assert lineage.owned(880_001)["state"] == "CLOSED"
    assert env.ledger.kill_switch_engaged()
    original_calls = tuple(route.calls)
    assert [method for method, _ in original_calls].count("POST") == 2
    for attempt in range(12):
        env.clock.now = NOW + timedelta(minutes=attempt)
        restarted = OfflineSwingScheduledService(
            SchedulerStore(env.tmp / "schedule.sqlite3"),
            OfflineSwingRunFence(env.tmp / "single-writer.sqlite3"),
            controller, clock=env.clock,
        )
        dossier = restarted.recovery_dossier(now=env.clock.now)
        assert any(
            item["review_action"] == "DURABLE_CLOSE_POLICY_LEDGER_MISMATCH_MANUAL_REVIEW"
            for item in dossier["uncertain_orders"]
        )
        result = restarted.run_due(owner=f"close-mismatch-restart-{attempt}")
        assert result.status == "RECOVERY_REQUIRED"
        assert result.execution_release == "ETORO_DEMO_NOT_RELEASED"
        assert tuple(route.calls) == original_calls
    assert env.ledger.kill_switch_engaged()


def test_sd152_tampered_final_close_units_blocks_ten_clean_slot_restarts(setup):
    """A completed synthetic close with changed durable units is not reconciled."""
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    entry = env.entry()
    controller.adapter.submit_entry(entry, quote=quote)
    plan = controller.runtime.plan_exits(bids=(seal_bid(signer, env, "455"),))
    assert len(plan.exits) == 1
    controller.adapter.submit_exit(plan.exits[0], quote=seal_bid(signer, env, "455"))
    assert service.recovery_dossier(now=NOW)["uncertain_orders"] == []
    with sqlite3.connect(env.tmp / "sd138-lineage.sqlite3") as conn:
        conn.execute(
            "UPDATE etoro_demo_lineage_orders SET filled_units=? "
            "WHERE kind='CLOSE' AND state='FILLED'", ("999",),
        )
    original_calls = tuple(route.calls)
    assert [method for method, _ in original_calls].count("POST") == 2
    for attempt in range(10):
        env.clock.now = NOW + timedelta(minutes=attempt)
        restarted = OfflineSwingScheduledService(
            SchedulerStore(env.tmp / "schedule.sqlite3"),
            OfflineSwingRunFence(env.tmp / "single-writer.sqlite3"),
            controller, clock=env.clock,
        )
        dossier = restarted.recovery_dossier(now=env.clock.now)
        assert any(
            item["review_action"] == "DURABLE_CLOSE_POLICY_LEDGER_MISMATCH_MANUAL_REVIEW"
            for item in dossier["uncertain_orders"]
        )
        assert restarted.run_due(owner=f"tamper-restart-{attempt}").status == "RECOVERY_REQUIRED"
        assert tuple(route.calls) == original_calls
    assert not env.ledger.kill_switch_engaged()  # No automatic HALT reset was attempted.


def test_sd152_inconsistent_remaining_units_never_rearms_synthetic_entry(setup):
    """Post-fill position accounting tampering remains blocked across restarts."""
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    proposal = env.entry()
    assert isinstance(proposal, EntryProposal)
    controller.adapter.submit_entry(proposal, quote=quote)
    assert lineage.owned(880_001)["state"] == "OPEN"
    with sqlite3.connect(env.tmp / "sd138-lineage.sqlite3") as conn:
        conn.execute(
            "UPDATE etoro_demo_owned_positions SET remaining_units=? "
            "WHERE position_id=?", ("999", 880_001),
        )
    before = tuple(route.calls)
    for attempt in range(8):
        restarted = OfflineSwingScheduledService(
            SchedulerStore(env.tmp / "schedule.sqlite3"),
            OfflineSwingRunFence(env.tmp / "single-writer.sqlite3"),
            controller, clock=env.clock,
        )
        dossier = restarted.recovery_dossier(now=env.clock.now)
        assert dossier["uncertain_orders"]
        assert restarted.run_due(owner=f"remaining-units-{attempt}").status == "RECOVERY_REQUIRED"
        assert tuple(route.calls) == before
    assert [method for method, _ in before].count("POST") == 1


def test_sd152_partial_entry_then_full_reduce_across_two_slots(setup):
    """Verified partial opening fill may close exactly the recorded units."""
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    proposal = env.entry()
    assert isinstance(proposal, EntryProposal)
    route.mode = "PARTIAL"
    opened = service.run_due(owner="partial-open", entry=proposal, entry_quote=quote)
    assert opened.status == "ENTRY_CONFIRMED"
    assert opened.cycle is not None
    assert opened.cycle.open_positions == 1
    assert env.ledger.open_positions()[0].units == proposal.units / 2
    assert lineage.owned(880_001)["state"] == "OPEN"
    assert service.recovery_dossier(now=env.clock.now)["uncertain_orders"] == []
    before = tuple(route.calls)
    assert [method for method, _ in before].count("POST") == 1
    route.mode = "FILL"
    env.clock.now = NOW + timedelta(hours=2, minutes=35)
    closed = service.run_due(
        owner="full-reduce", planning_bids=(seal_bid(signer, env, "455"),),
        execution_bids={MSFT: seal_bid(signer, env, "455")},
    )
    assert closed.status == "EXITS_CONFIRMED"
    assert closed.cycle is not None
    assert closed.cycle.open_positions == 0
    assert env.ledger.open_positions() == ()
    assert lineage.owned(880_001)["state"] == "CLOSED"
    assert [method for method, _ in route.calls].count("POST") == 2
    assert service.recovery_dossier(now=env.clock.now)["uncertain_orders"] == []


def test_sd152_partial_close_ten_restarts_never_infer_flat_or_repost(setup):
    """A partial broker-shaped CLOSE response cannot be treated as a final fill."""
    env, quote, signer, route, lineage, controller, scheduler, fence, service = setup
    allow_fake_schedule(scheduler)
    proposal = env.entry()
    assert service.run_due(owner="entry", entry=proposal, entry_quote=quote).status == "ENTRY_CONFIRMED"
    env.clock.now = NOW + timedelta(hours=2, minutes=35)
    route.close_mode = "PARTIAL"
    attempted = service.run_due(
        owner="partial-exit", planning_bids=(seal_bid(signer, env, "455"),),
        execution_bids={MSFT: seal_bid(signer, env, "455")},
    )
    assert attempted.status == "HALTED"
    assert env.ledger.kill_switch_engaged()
    assert fence.state() == "UNRESOLVED"
    assert env.ledger.open_positions()
    assert lineage.owned(880_001)["state"] == "OPEN"
    before = tuple(route.calls)
    assert [method for method, _ in before].count("POST") == 2
    for attempt in range(10):
        env.clock.now = NOW + timedelta(hours=2, minutes=35 + attempt)
        restarted = OfflineSwingScheduledService(
            SchedulerStore(env.tmp / "schedule.sqlite3"),
            OfflineSwingRunFence(env.tmp / "single-writer.sqlite3"),
            controller, clock=env.clock,
        )
        assert restarted.run_due(owner=f"partial-close-restart-{attempt}").status == "RECOVERY_REQUIRED"
        assert tuple(route.calls) == before
        assert env.ledger.open_positions()
        assert restarted.fence.state() == "UNRESOLVED"
    assert env.ledger.kill_switch_engaged()
