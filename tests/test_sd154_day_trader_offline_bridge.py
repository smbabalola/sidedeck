"""Day Trader research is integrated without granting entry authority."""
from datetime import UTC, datetime
from pathlib import Path

from sidedeck.application.sd071_decision_engine import StrategyAdmission
from sidedeck.application.sd123_day_demo_integration import DayResearchResult
from sidedeck.application.sd126_offline_day_controller import OfflineDayCycleController
from sidedeck.application.sd154_day_trader_offline_bridge import run_day_trader_offline_cycle

from test_sd063_autonomous_demo_policy import _offline_gateway
from test_sd125_day_session_exits import _day_env


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
