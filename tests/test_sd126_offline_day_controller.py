"""End-to-end offline DAY cycles with signed policy, fills and session close."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sidedeck.application.sd063_autonomous_demo_policy import EntryProposal
from sidedeck.application.sd126_offline_day_controller import OfflineDayCycleController

from test_sd063_autonomous_demo_policy import MSFT, _offline_gateway
from test_sd125_day_session_exits import _day_entry, _day_env


def _quote(signer, when: datetime) -> object:
    return signer.seal({
        "canonical_id": MSFT,
        "bid": "499", "ask": "500",
        "quote_time": (when - timedelta(seconds=5)).isoformat(),
    })


def test_day_entry_to_early_close_and_restart_proof(tmp_path: Path) -> None:
    env = _day_env(tmp_path, datetime(2026, 11, 27, 15, 0, tzinfo=UTC))
    gateway, open_quote, signer = _offline_gateway(
        env, fill_price="500", close_price="490",
        storage_path=tmp_path / "simulator.sqlite3",
    )
    try:
        controller = OfflineDayCycleController(gateway._runtime, gateway, clock=env.clock)
        proposal = _day_entry(env)
        assert isinstance(proposal, EntryProposal), proposal
        opened = controller.tick(entry=proposal, entry_quote=open_quote)
        assert opened.status == "ENTRY_CONFIRMED", opened
        assert opened.open_positions == 1
        assert gateway._simulator.submitted_orders == 1
        assert not env.ledger.kill_switch_engaged()

        # One policy lasts several days, but this DAY position flattens
        # on the current (early-close) trading session.
        env.clock.now = datetime(2026, 11, 27, 17, 50, tzinfo=UTC)
        closed = controller.tick(
            planning_bids=(_quote(signer, env.clock.now),),
            execution_bids={MSFT: _quote(signer, env.clock.now)},
        )
        assert closed.status == "EXITS_CONFIRMED", closed
        assert closed.open_positions == 0
        assert len(closed.exit_references) == 1
        assert gateway._simulator.submitted_orders == 1
        assert not env.ledger.kill_switch_engaged()

        # The same proposal is durable/resolved, not a second order.
        repeat = controller.tick(entry=proposal, entry_quote=_quote(signer, env.clock.now))
        assert repeat.status == "NO_TRADE"
        assert "ENTRY_ALREADY_RESOLVED" in repeat.alerts
        assert gateway._simulator.submitted_orders == 1
    finally:
        gateway._simulator.close_store()
        env.ledger.close()


def test_missing_close_quote_halts_without_simulated_close(tmp_path: Path) -> None:
    env = _day_env(tmp_path, datetime(2026, 11, 27, 15, 0, tzinfo=UTC))
    gateway, quote, signer = _offline_gateway(env, fill_price="500", close_price="490")
    try:
        controller = OfflineDayCycleController(gateway._runtime, gateway, clock=env.clock)
        proposal = _day_entry(env)
        assert isinstance(proposal, EntryProposal)
        assert controller.tick(entry=proposal, entry_quote=quote).status == "ENTRY_CONFIRMED"

        env.clock.now = datetime(2026, 11, 27, 17, 50, tzinfo=UTC)
        result = controller.tick(planning_bids=(_quote(signer, env.clock.now),))
        assert result.status == "HALTED"
        assert "EXIT_SEND_QUOTE_MISSING" in result.alerts
        assert env.ledger.kill_switch_engaged()
        assert len(env.ledger.open_positions()) == 1
    finally:
        gateway._simulator.close_store()
        env.ledger.close()


def test_open_position_missing_planning_quote_never_opens_another(tmp_path: Path) -> None:
    env = _day_env(tmp_path, datetime(2026, 11, 27, 15, 0, tzinfo=UTC))
    gateway, quote, signer = _offline_gateway(env, fill_price="500")
    try:
        controller = OfflineDayCycleController(gateway._runtime, gateway, clock=env.clock)
        proposal = _day_entry(env)
        assert isinstance(proposal, EntryProposal)
        assert controller.tick(entry=proposal, entry_quote=quote).status == "ENTRY_CONFIRMED"
        other = replace(proposal, reference_id="a" * 32)
        result = controller.tick(entry=other, entry_quote=_quote(signer, env.clock.now))
        assert result.status == "HALTED"
        assert any(a.startswith("QUOTE_UNAVAILABLE:") for a in result.alerts)
        assert "POSITION_PROTECTION_UNVERIFIED" in result.alerts
        assert env.ledger.kill_switch_engaged()
        assert gateway._simulator.submitted_orders == 1
    finally:
        gateway._simulator.close_store()
        env.ledger.close()


def test_non_day_proposal_is_refused_before_any_send(tmp_path: Path) -> None:
    env = _day_env(tmp_path, datetime(2026, 11, 27, 15, 0, tzinfo=UTC))
    gateway, quote, _ = _offline_gateway(env, fill_price="500")
    try:
        controller = OfflineDayCycleController(gateway._runtime, gateway, clock=env.clock)
        proposal = _day_entry(env)
        assert isinstance(proposal, EntryProposal)
        result = controller.tick(entry=replace(proposal, track="SWING"), entry_quote=quote)
        assert result.status == "NO_TRADE"
        assert "NON_DAY_PROPOSAL_REFUSED" in result.alerts
        assert gateway._simulator.submitted_orders == 0
    finally:
        gateway._simulator.close_store()
        env.ledger.close()


def test_controller_refuses_substituted_broker_client() -> None:
    with pytest.raises(TypeError, match="offline SD-107"):
        OfflineDayCycleController(object(), object())  # type: ignore[arg-type]
