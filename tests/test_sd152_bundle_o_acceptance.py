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


def test_day_scheduled_missing_exit_quote_halts_and_preserves_open_position(tmp_path):
    """A due early-close tick cannot claim flat without an executable close quote."""
    from datetime import UTC, datetime
    from sidedeck.application.sd068_track_scheduler import SchedulerStore
    from sidedeck.application.sd126_offline_day_controller import OfflineDayCycleController
    from sidedeck.application.sd152_offline_swing_runner import (
        OfflineDayScheduledService, OfflineSwingRunFence,
    )
    from test_sd063_autonomous_demo_policy import _offline_gateway
    from test_sd125_day_session_exits import _day_env, _day_entry
    from test_sd126_offline_day_controller import _quote

    env = _day_env(tmp_path, datetime(2026, 11, 27, 15, 5, tzinfo=UTC))
    gateway, send_quote, signer = _offline_gateway(
        env, storage_path=tmp_path / "day-sim.sqlite3",
    )
    scheduler = SchedulerStore(tmp_path / "day-schedule.sqlite3")
    fence = OfflineSwingRunFence(tmp_path / "day-fence.sqlite3")
    scheduler.set_track("DAY", enabled=True, mode="SIMULATION_ONLY")
    scheduler.set_exchange_track("XNYS", "DAY", enabled=True, mode="SIMULATION_ONLY")
    service = OfflineDayScheduledService(
        scheduler, fence,
        OfflineDayCycleController(gateway._runtime, gateway, clock=env.clock),
        clock=env.clock,
    )
    try:
        assert service.run_due(owner="entry", entry=_day_entry(env),
                               entry_quote=send_quote)["status"] == "ENTRY_CONFIRMED"
        assert len(env.ledger.open_positions()) == 1
        env.clock.now = datetime(2026, 11, 27, 17, 50, tzinfo=UTC)
        failed = service.run_due(
            owner="exit-without-send-quote",
            planning_bids=(_quote(signer, env.clock.now),),
        )
        assert failed["status"] == "HALTED"
        assert "EXIT_SEND_QUOTE_MISSING" in failed["cycle"]["alerts"]
        assert failed["cycle"]["open_positions"] == 1
        assert len(env.ledger.open_positions()) == 1
        assert env.ledger.kill_switch_engaged()
        assert fence.state() == "UNRESOLVED"
        assert gateway._simulator.submitted_orders == 1
        restarted = OfflineDayScheduledService(
            SchedulerStore(tmp_path / "day-schedule.sqlite3"),
            OfflineSwingRunFence(tmp_path / "day-fence.sqlite3"),
            OfflineDayCycleController(gateway._runtime, gateway, clock=env.clock),
            clock=env.clock,
        )
        assert restarted.run_due(owner="restart")["status"] == "RECOVERY_REQUIRED"
        assert len(env.ledger.open_positions()) == 1
        assert gateway._simulator.submitted_orders == 1
    finally:
        gateway._simulator.close_store()
        env.ledger.close()


def test_day_multi_tick_unattended_driver_simulates_open_monitor_close(tmp_path):
    """A deterministic offline clock drives successive scheduled ticks without trade prompts.

    This exercises the scheduler API, not an installed background daemon.
    No actual broker route, market data or external trading authority is used.
    """
    from datetime import UTC, datetime
    from sidedeck.application.sd068_track_scheduler import SchedulerStore
    from sidedeck.application.sd126_offline_day_controller import OfflineDayCycleController
    from sidedeck.application.sd152_offline_swing_runner import (
        OfflineDayScheduledService, OfflineSwingRunFence,
    )
    from test_sd063_autonomous_demo_policy import MSFT, _offline_gateway
    from test_sd125_day_session_exits import _day_entry, _day_env
    from test_sd126_offline_day_controller import _quote

    env = _day_env(tmp_path, datetime(2026, 11, 27, 15, 5, tzinfo=UTC))
    gateway, entry_quote, signer = _offline_gateway(
        env, fill_price="500", close_price="490",
        storage_path=tmp_path / "day-sim.sqlite3",
    )
    schedule_file, fence_file = (
        tmp_path / "day-schedule.sqlite3", tmp_path / "day-fence.sqlite3",
    )
    scheduler = SchedulerStore(schedule_file)
    scheduler.set_track("DAY", enabled=True, mode="SIMULATION_ONLY")
    scheduler.set_exchange_track("XNYS", "DAY", enabled=True, mode="SIMULATION_ONLY")

    def worker():
        # Reconstruct the scheduled worker and durable stores at every tick,
        # as an independently restarted offline process would.
        return OfflineDayScheduledService(
            SchedulerStore(schedule_file), OfflineSwingRunFence(fence_file),
            OfflineDayCycleController(gateway._runtime, gateway, clock=env.clock),
            clock=env.clock,
        )

    try:
        entry = _day_entry(env)
        opened = worker().run_due(owner="tick-entry", entry=entry, entry_quote=entry_quote)
        assert opened["status"] == "ENTRY_CONFIRMED", opened
        assert opened["cycle"]["open_positions"] == 1
        assert gateway._simulator.submitted_orders == 1

        # Several unattended decision ticks are processed with no new entry.
        # The position remains owned and actively monitored between ticks.
        for minute in (10, 15, 20):
            env.clock.now = datetime(2026, 11, 27, 15, minute, tzinfo=UTC)
            observed = worker().run_due(
                owner=f"tick-monitor-{minute}",
                planning_bids=(_quote(signer, env.clock.now),),
            )
            assert observed["status"] == "NO_TRADE", observed
            assert observed["cycle"]["open_positions"] == 1
            assert len(env.ledger.open_positions()) == 1
            assert gateway._simulator.submitted_orders == 1
            assert not env.ledger.kill_switch_engaged()

        # The real exchange calendar marks this Thanksgiving Friday as an
        # early close. At T-10 the scheduler must still issue a protective exit.
        env.clock.now = datetime(2026, 11, 27, 17, 50, tzinfo=UTC)
        final = worker().run_due(
            owner="tick-close",
            planning_bids=(_quote(signer, env.clock.now),),
            execution_bids={MSFT: _quote(signer, env.clock.now)},
        )
        assert final["status"] == "EXITS_CONFIRMED", final
        assert final["cycle"]["open_positions"] == 0
        assert final["cycle"]["exit_references"]
        assert env.ledger.open_positions() == ()
        assert gateway._simulator.submitted_orders == 1
        assert worker().run_due(owner="replay-after-flat")["status"] == "NO_DUE_SLOT"
        assert OfflineSwingRunFence(fence_file).state() == "IDLE"
        assert len([row for row in SchedulerStore(schedule_file).history("day_candidate_scan")
                    if row[1] == "COMPLETED"]) == 5
        assert final["execution_release"] == "ETORO_DEMO_NOT_RELEASED"
    finally:
        gateway._simulator.close_store()
        env.ledger.close()


def test_day_bounded_driver_runs_and_stops_on_unresolved_restart(tmp_path):
    """One driver call traverses due ticks and stops rather than retrying a failed close."""
    from datetime import UTC, datetime
    from sidedeck.application.sd068_track_scheduler import SchedulerStore
    from sidedeck.application.sd126_offline_day_controller import OfflineDayCycleController
    from sidedeck.application.sd152_offline_swing_runner import (
        OfflineDayScheduledService, OfflineSwingRunFence,
        drive_offline_day_sequence,
    )
    from test_sd063_autonomous_demo_policy import _offline_gateway
    from test_sd125_day_session_exits import _day_entry, _day_env
    from test_sd126_offline_day_controller import _quote

    env = _day_env(tmp_path, datetime(2026, 11, 27, 15, 5, tzinfo=UTC))
    gateway, entry_quote, signer = _offline_gateway(env)
    scheduler_path = tmp_path / "schedule.sqlite3"
    fence_path = tmp_path / "fence.sqlite3"
    scheduler = SchedulerStore(scheduler_path)
    scheduler.set_track("DAY", enabled=True, mode="SIMULATION_ONLY")
    scheduler.set_exchange_track("XNYS", "DAY", enabled=True, mode="SIMULATION_ONLY")

    def service():
        return OfflineDayScheduledService(
            SchedulerStore(scheduler_path), OfflineSwingRunFence(fence_path),
            OfflineDayCycleController(gateway._runtime, gateway, clock=env.clock),
            clock=env.clock,
        )

    def tick(moment, **kwargs):
        def action():
            env.clock.now = moment
            return service().run_due(owner="bounded-driver", **kwargs)
        return action

    try:
        entry = _day_entry(env)
        monitoring_at = datetime(2026, 11, 27, 15, 10, tzinfo=UTC)
        exit_at = datetime(2026, 11, 27, 17, 50, tzinfo=UTC)
        ticks = (
            tick(datetime(2026, 11, 27, 15, 5, tzinfo=UTC),
                 entry=entry, entry_quote=entry_quote),
            tick(monitoring_at, planning_bids=(_quote(signer, monitoring_at),)),
            tick(exit_at, planning_bids=(_quote(signer, exit_at),)),
            tick(exit_at),  # Must not run: the previous exit halts the service
        )
        outcomes = drive_offline_day_sequence(service, ticks)
        assert [o["status"] for o in outcomes] == [
            "ENTRY_CONFIRMED", "NO_TRADE", "HALTED",
        ]
        assert "EXIT_SEND_QUOTE_MISSING" in outcomes[-1]["cycle"]["alerts"]
        assert len(env.ledger.open_positions()) == 1
        assert env.ledger.kill_switch_engaged()
        assert OfflineSwingRunFence(fence_path).state() == "UNRESOLVED"
        assert gateway._simulator.submitted_orders == 1
        assert service().run_due(owner="after-crash")["status"] == "RECOVERY_REQUIRED"
    finally:
        gateway._simulator.close_store()
        env.ledger.close()
