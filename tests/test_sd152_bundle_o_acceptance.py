"""SD-152 Bundle O consolidated offline regression acceptance entrypoint.

This suite intentionally invokes existing tests rather than reimplementing the
simulation. It is not broker qualification, a release grant, or an external audit.
Run with: pytest -q tests/test_sd152_bundle_o_acceptance.py
"""
from __future__ import annotations

import pytest

import test_sd140_sd152_offline_swing_runner as scenarios


@pytest.mark.parametrize("scenario", [
    scenarios.test_sd140_sd152_two_sessions_open_and_close_via_real_fake_adapter,
    scenarios.test_sd152_twenty_restart_attempts_do_not_repeat_simulated_entry,
    scenarios.test_sd152_repeated_restart_after_unresolved_fence_never_reposts,
    scenarios.test_sd152_ambiguous_close_ten_restarts_preserve_single_exit_post,
    scenarios.test_sd152_close_ledger_mismatch_blocks_twelve_restarts_without_replay,
    scenarios.test_sd152_tampered_final_close_units_blocks_ten_clean_slot_restarts,
    scenarios.test_sd152_inconsistent_remaining_units_never_rearms_synthetic_entry,
    scenarios.test_sd152_partial_entry_then_full_reduce_across_two_slots,
    scenarios.test_sd152_partial_close_ten_restarts_never_infer_flat_or_repost,
], ids=lambda test: test.__name__.removeprefix("test_"))
def test_bundle_o_offline_acceptance_scenarios(setup, scenario):
    scenario(setup)


@pytest.fixture
def setup(tmp_path):
    # Keep one fresh fixture per parametrized scenario: never share ledgers
    # across fault cases. The underlying test module owns the lifecycle.
    iterator = scenarios.setup.__wrapped__(tmp_path)
    value = next(iterator)
    try:
        yield value
    finally:
        try:
            next(iterator)
        except StopIteration:
            pass


def test_day_orb_test_only_autonomous_entry_to_exit_and_replay(tmp_path):
    """Run the native ORB fixture lifecycle inside the same acceptance suite.

    Admission is explicitly a synthetic test fixture, never production evidence.
    eToro transport stays disabled; the scenario itself checks entry, exit,
    flatness, replay and the no-admission refusal.
    """
    from test_sd155_orb_native_signal_lifecycle import (
        test_real_orb_method_with_separately_sealed_native_fixture_drives_offline_entry_and_exit,
    )

    test_real_orb_method_with_separately_sealed_native_fixture_drives_offline_entry_and_exit(
        tmp_path,
    )


def test_day_orb_no_self_admission(tmp_path):
    """A genuine method invocation on fixture bars cannot grant its own orders."""
    from test_sd154_day_trader_orb_integration import (
        test_actual_orb_signal_enters_bridge_but_cannot_self_admit,
    )

    test_actual_orb_signal_enters_bridge_but_cannot_self_admit(tmp_path)


def test_day_missing_execution_quote_halts_without_simulated_submit(tmp_path):
    """A DAY proposal may not be sent without its distinct signed send quote."""
    from datetime import UTC, datetime

    from sidedeck.application.sd063_autonomous_demo_policy import EntryProposal
    from sidedeck.application.sd126_offline_day_controller import OfflineDayCycleController
    from test_sd125_day_session_exits import _day_entry, _day_env
    from test_sd063_autonomous_demo_policy import _offline_gateway

    env = _day_env(tmp_path, datetime(2026, 11, 27, 15, 0, tzinfo=UTC))
    gateway, _planning_quote, _signer = _offline_gateway(env)
    try:
        proposal = _day_entry(env)
        assert isinstance(proposal, EntryProposal)
        controller = OfflineDayCycleController(gateway._runtime, gateway, clock=env.clock)
        result = controller.tick(entry=proposal, entry_quote=None)
        assert result.status == "HALTED"
        assert "ENTRY_SEND_QUOTE_MISSING" in result.alerts
        assert gateway._simulator.submitted_orders == 0
        assert env.ledger.kill_switch_engaged()
        # Reconstruct the controller over durable state: neither a restart nor
        # a repeated proposal is authority to send after a missing quote.
        restarted = OfflineDayCycleController(gateway._runtime, gateway, clock=env.clock)
        replay = restarted.tick(entry=proposal)
        assert replay.status == "HALTED"
        assert gateway._simulator.submitted_orders == 0
        assert restarted.gateway._runtime.ledger.kill_switch_engaged()
        assert result.execution_release == "ETORO_DEMO_NOT_RELEASED"
    finally:
        gateway._simulator.close_store()
        env.ledger.close()


def test_day_scheduled_service_locked_then_single_slot_no_replay(tmp_path):
    """One simulated DAY slot is consumed once, even across worker reconstruction."""
    from datetime import UTC, datetime
    from sidedeck.application.sd068_track_scheduler import SchedulerStore
    from sidedeck.application.sd126_offline_day_controller import OfflineDayCycleController
    from sidedeck.application.sd152_offline_swing_runner import (
        OfflineDayScheduledService, OfflineSwingRunFence,
    )
    from test_sd125_day_session_exits import _day_env
    from test_sd063_autonomous_demo_policy import _offline_gateway

    env = _day_env(tmp_path, datetime(2026, 11, 27, 15, 5, tzinfo=UTC))
    gateway, _, _ = _offline_gateway(env)
    scheduler = SchedulerStore(tmp_path / "day-schedule.sqlite3")
    fence = OfflineSwingRunFence(tmp_path / "day-fence.sqlite3")
    controller = OfflineDayCycleController(gateway._runtime, gateway, clock=env.clock)
    service = OfflineDayScheduledService(scheduler, fence, controller, clock=env.clock)
    try:
        assert service.run_due(owner="worker-one")["status"] == "LOCKED"
        assert gateway._simulator.submitted_orders == 0
        scheduler.set_track("DAY", enabled=True, mode="SIMULATION_ONLY")
        scheduler.set_exchange_track("XNYS", "DAY", enabled=True, mode="SIMULATION_ONLY")
        first = service.run_due(owner="worker-one")
        assert first["status"] == "NO_TRADE"
        assert first["execution_release"] == "ETORO_DEMO_NOT_RELEASED"
        assert fence.state() == "IDLE"
        assert len(scheduler.history("day_candidate_scan")) >= 1
        reconstructed = OfflineDayScheduledService(
            SchedulerStore(tmp_path / "day-schedule.sqlite3"),
            OfflineSwingRunFence(tmp_path / "day-fence.sqlite3"),
            controller, clock=env.clock,
        )
        assert reconstructed.run_due(owner="worker-two")["status"] == "NO_DUE_SLOT"
        assert gateway._simulator.submitted_orders == 0
    finally:
        gateway._simulator.close_store()
        env.ledger.close()


def test_day_scheduled_service_crashed_worker_never_auto_takes_over(tmp_path):
    """An abandoned DAY fence blocks a new process, irrespective of schedule lease."""
    from datetime import UTC, datetime
    from sidedeck.application.sd068_track_scheduler import SchedulerStore, slots_for
    from sidedeck.application.sd126_offline_day_controller import OfflineDayCycleController
    from sidedeck.application.sd152_offline_swing_runner import (
        OfflineDayScheduledService, OfflineSwingRunFence,
    )
    from test_sd125_day_session_exits import _day_env
    from test_sd063_autonomous_demo_policy import _offline_gateway

    now = datetime(2026, 11, 27, 15, 5, tzinfo=UTC)
    env = _day_env(tmp_path, now)
    gateway, _, _ = _offline_gateway(env)
    scheduler = SchedulerStore(tmp_path / "day-schedule.sqlite3")
    fence = OfflineSwingRunFence(tmp_path / "day-fence.sqlite3")
    controller = OfflineDayCycleController(gateway._runtime, gateway, clock=env.clock)
    try:
        scheduler.set_track("DAY", enabled=True, mode="SIMULATION_ONLY")
        scheduler.set_exchange_track("XNYS", "DAY", enabled=True, mode="SIMULATION_ONLY")
        slot = slots_for(scheduler.jobs["day_candidate_scan"], now.date())[0]
        token = fence.acquire(slot, owner="crashed-worker", at=now)
        assert token is not None
        restarted = OfflineDayScheduledService(
            SchedulerStore(tmp_path / "day-schedule.sqlite3"),
            OfflineSwingRunFence(tmp_path / "day-fence.sqlite3"),
            controller, clock=env.clock,
        )
        assert restarted.run_due(owner="new-worker")["status"] == "RECOVERY_REQUIRED"
        fence.finish(token, at=now, safe=False, outcome="CRASH_SIMULATED")
        assert restarted.run_due(owner="another-worker")["status"] == "RECOVERY_REQUIRED"
        assert gateway._simulator.submitted_orders == 0
    finally:
        gateway._simulator.close_store()
        env.ledger.close()


def test_day_scheduled_entry_early_close_exit_and_cold_restart(tmp_path):
    """Real DAY scheduler slots drive the existing offline entry and exit gateway."""
    from datetime import UTC, datetime
    from sidedeck.application.sd068_track_scheduler import SchedulerStore
    from sidedeck.application.sd126_offline_day_controller import OfflineDayCycleController
    from sidedeck.application.sd152_offline_swing_runner import (
        OfflineDayScheduledService, OfflineSwingRunFence,
    )
    from test_sd063_autonomous_demo_policy import _offline_gateway, MSFT
    from test_sd125_day_session_exits import _day_env, _day_entry
    from test_sd126_offline_day_controller import _quote

    env = _day_env(tmp_path, datetime(2026, 11, 27, 15, 5, tzinfo=UTC))
    gateway, send_quote, signer = _offline_gateway(
        env, fill_price="500", close_price="490",
        storage_path=tmp_path / "day-sim.sqlite3",
    )
    scheduler_path = tmp_path / "day-schedule.sqlite3"
    fence_path = tmp_path / "day-fence.sqlite3"
    scheduler = SchedulerStore(scheduler_path)
    scheduler.set_track("DAY", enabled=True, mode="SIMULATION_ONLY")
    scheduler.set_exchange_track("XNYS", "DAY", enabled=True, mode="SIMULATION_ONLY")
    controller = OfflineDayCycleController(gateway._runtime, gateway, clock=env.clock)
    service = OfflineDayScheduledService(
        scheduler, OfflineSwingRunFence(fence_path), controller, clock=env.clock,
    )
    try:
        entry = _day_entry(env)
        from sidedeck.application.sd063_autonomous_demo_policy import EntryProposal
        assert isinstance(entry, EntryProposal)
        opened = service.run_due(owner="day-a", entry=entry, entry_quote=send_quote)
        assert opened["status"] == "ENTRY_CONFIRMED", opened
        assert opened["cycle"]["open_positions"] == 1
        assert gateway._simulator.submitted_orders == 1

        env.clock.now = datetime(2026, 11, 27, 17, 50, tzinfo=UTC)
        restarted = OfflineDayScheduledService(
            SchedulerStore(scheduler_path), OfflineSwingRunFence(fence_path),
            OfflineDayCycleController(gateway._runtime, gateway, clock=env.clock),
            clock=env.clock,
        )
        closed = restarted.run_due(
            owner="day-b", planning_bids=(_quote(signer, env.clock.now),),
            execution_bids={MSFT: _quote(signer, env.clock.now)},
        )
        assert closed["status"] == "EXITS_CONFIRMED", closed
        assert closed["cycle"]["open_positions"] == 0
        assert env.ledger.open_positions() == ()
        assert gateway._simulator.submitted_orders == 1
        assert restarted.run_due(owner="day-c")["status"] == "NO_DUE_SLOT"
        assert len([x for x in scheduler.history("day_candidate_scan")
                    if x[1] == "COMPLETED"]) == 2
        assert not env.ledger.kill_switch_engaged()
        assert closed["execution_release"] == "ETORO_DEMO_NOT_RELEASED"
    finally:
        gateway._simulator.close_store()
        env.ledger.close()
