"""SD-140/152 OFFLINE scheduled SWING end-to-end and single-writer negative tests."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from sidedeck.application.sd063_autonomous_demo_policy import EntryProposal
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
