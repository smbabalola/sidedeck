"""Day Trader research is integrated without granting entry authority."""
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sidedeck.application.sd070_research_signal import EvidenceRef, ResearchSignal
from sidedeck.application.sd071_decision_engine import StrategyAdmission
from sidedeck.application.sd123_day_demo_integration import DayResearchResult
from sidedeck.application.sd126_offline_day_controller import OfflineDayCycleController
from sidedeck.application.sd154_day_trader_offline_bridge import run_day_trader_offline_cycle

from test_sd063_autonomous_demo_policy import MSFT, _offline_gateway
from test_sd125_day_session_exits import _day_env, _day_entry


def test_day_trader_research_without_independent_admission_cannot_order(tmp_path: Path):
    env = _day_env(tmp_path, datetime(2026, 11, 27, 15, 0, tzinfo=UTC))
    gateway, _, _ = _offline_gateway(env, fill_price="500")
    try:
        controller = OfflineDayCycleController(gateway._runtime, gateway, clock=env.clock)
        research = DayResearchResult(
            signal=None,
            admission=StrategyAdmission("day_trader_skill.orb", "dts-2.0.0-native.1",
                                        "DAY", "RESEARCH_ONLY", "fixture-research", 0, False),
            metadata={}, status="INSUFFICIENT_OPENING_RANGE",
        )
        result = run_day_trader_offline_cycle(controller, research_result=research)
        assert result.cycle.status == "NO_TRADE"
        assert result.proposal_reasons == ("DAY_TRADER_NO_ENTRY_SIGNAL",)
        assert result.report()["broker_execution"] == "DISABLED"
        assert gateway._simulator.submitted_orders == 0
    finally:
        gateway._simulator.close_store()
        env.ledger.close()


def test_bridge_rejects_substituted_execution_controller():
    research = DayResearchResult(
        signal=None, admission=StrategyAdmission(
            "day_trader_skill.orb", "1", "DAY", "RESEARCH_ONLY", "fixture", 0, False),
        metadata={}, status="NO_SIGNAL",
    )
    try:
        run_day_trader_offline_cycle(object(), research_result=research)
    except TypeError as exc:
        assert "exact offline DAY controller" in str(exc)
    else:
        raise AssertionError("substituted controller unexpectedly accepted")


def test_day_trader_bridge_closes_existing_day_position_without_new_signal(
    tmp_path: Path,
):
    """Research outage cannot prevent an already-owned DAY position's exit."""
    env = _day_env(tmp_path, datetime(2026, 11, 27, 15, 0, tzinfo=UTC))
    gateway, open_quote, signer = _offline_gateway(
        env, fill_price="500", close_price="490",
        storage_path=tmp_path / "simulator.sqlite3",
    )
    try:
        controller = OfflineDayCycleController(gateway._runtime, gateway, clock=env.clock)
        proposal = _day_entry(env)
        assert controller.tick(entry=proposal, entry_quote=open_quote).status == "ENTRY_CONFIRMED"
        env.clock.now = datetime(2026, 11, 27, 17, 50, tzinfo=UTC)
        research = DayResearchResult(
            signal=None,
            admission=StrategyAdmission("day_trader_skill.orb", "dts-2.0.0-native.1",
                                        "DAY", "RESEARCH_ONLY", "no-live-research", 0, False),
            metadata={}, status="NO_SIGNAL",
        )
        def fresh_quote():
            return signer.seal({
                "canonical_id": MSFT, "bid": "499", "ask": "500",
                "quote_time": (env.clock.now - timedelta(seconds=5)).isoformat(),
            })
        result = run_day_trader_offline_cycle(
            controller, research_result=research,
            planning_bids=(fresh_quote(),),
            execution_bids={MSFT: fresh_quote()},
        )
        assert result.cycle.status == "EXITS_CONFIRMED"
        assert result.cycle.open_positions == 0
        assert result.proposal_reasons == ("EXISTING_POSITION_EXIT_PRIORITY",)
        assert not env.ledger.kill_switch_engaged()
    finally:
        gateway._simulator.close_store()
        env.ledger.close()


def test_open_day_position_has_exit_priority_over_new_day_trader_signal(tmp_path: Path):
    env = _day_env(tmp_path, datetime(2026, 11, 27, 15, 0, tzinfo=UTC))
    gateway, open_quote, signer = _offline_gateway(
        env, fill_price="500", close_price="490",
        storage_path=tmp_path / "simulator.sqlite3",
    )
    try:
        controller = OfflineDayCycleController(gateway._runtime, gateway, clock=env.clock)
        proposal = _day_entry(env)
        assert controller.tick(entry=proposal, entry_quote=open_quote).status == "ENTRY_CONFIRMED"
        env.clock.now = datetime(2026, 11, 27, 17, 50, tzinfo=UTC)
        signal = ResearchSignal(
            canonical_id=MSFT, track="DAY", source_kind="DAY_TRADER_METHOD",
            source_id="day_trader_skill.orb", source_version="dts-2.0.0-native.1",
            horizon_min_days=0, horizon_max_days=0, direction="LONG",
            evidence=(EvidenceRef("bars", "test:orb", "a" * 64),),
            generated_at=env.clock.now, data_cutoff=env.clock.now,
            invalidation=("below opening range",),
        )
        research = DayResearchResult(
            signal=signal,
            admission=StrategyAdmission("day_trader_skill.orb", "dts-2.0.0-native.1",
                                        "DAY", "RESEARCH_ONLY", "test-research", 0, False),
            metadata={}, status="RESEARCH_ONLY",
        )
        def fresh_quote():
            return signer.seal({
                "canonical_id": MSFT, "bid": "499", "ask": "500",
                "quote_time": (env.clock.now - timedelta(seconds=5)).isoformat(),
            })
        result = run_day_trader_offline_cycle(
            controller, research_result=research,
            planning_bids=(fresh_quote(),),
            execution_bids={MSFT: fresh_quote()},
        )
        assert result.proposal_reasons == ("EXISTING_POSITION_EXIT_PRIORITY",)
        assert result.cycle.status == "EXITS_CONFIRMED"
        assert result.cycle.open_positions == 0
        assert gateway._simulator.submitted_orders == 1
    finally:
        gateway._simulator.close_store()
        env.ledger.close()
