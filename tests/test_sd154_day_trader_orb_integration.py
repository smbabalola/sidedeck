"""Real native ORB calculation feeds the guarded Day Trader offline bridge.

Fixture chart bars exercise methodology, not genuine data or executable admission.
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sidedeck.application.sd069_day_trader_methods import IntradayBar, orb_signal, METHOD_VERSION
from sidedeck.application.sd071_decision_engine import StrategyAdmission
from sidedeck.application.sd123_day_demo_integration import DayResearchResult
from sidedeck.application.sd126_offline_day_controller import OfflineDayCycleController
from sidedeck.application.sd154_day_trader_offline_bridge import run_day_trader_offline_cycle

from test_sd063_autonomous_demo_policy import MSFT, _offline_gateway
from test_sd125_day_session_exits import _day_env


def test_actual_orb_signal_enters_bridge_but_cannot_self_admit(tmp_path: Path):
    now = datetime(2026, 11, 27, 15, 0, tzinfo=UTC)
    env = _day_env(tmp_path, now)
    gateway, _, _ = _offline_gateway(env, fill_price="500")
    try:
        # US Thanksgiving Friday 2026, 09:30 New York = 14:30 UTC.
        # Three opening-range bars then a completed breakout bar.
        prices = [
            ("499", "501", "498", "500"),
            ("500", "502", "499", "501"),
            ("501", "503", "500", "502"),
            ("502", "505", "501", "504"),
        ]
        bars = tuple(
            IntradayBar(
                start=now - timedelta(minutes=30 - 5 * i),
                open=Decimal(o), high=Decimal(h),
                low=Decimal(low), close=Decimal(c), volume=Decimal("10000"),
            )
            for i, (o, h, low, c) in enumerate(prices)
        )
        signal = orb_signal(MSFT, bars, now)
        assert signal is not None and signal.source_id == "day_trader_skill.orb"
        research = DayResearchResult(
            signal=signal,
            admission=StrategyAdmission(
                signal.source_id, METHOD_VERSION, "DAY", "RESEARCH_ONLY",
                "fixture-chart-not-oos", 0, False,
            ),
            metadata={"data_basis": "SYNTHETIC_FIXTURE"}, status="RESEARCH_ONLY",
        )
        result = run_day_trader_offline_cycle(
            OfflineDayCycleController(gateway._runtime, gateway, clock=env.clock),
            research_result=research,
        )
        assert result.research_status == "RESEARCH_ONLY"
        assert result.proposal_reasons == ("INDEPENDENT_NATIVE_STRATEGY_ADMISSION_REQUIRED",)
        assert result.cycle.status == "NO_TRADE"
        assert gateway._simulator.submitted_orders == 0
        assert not env.ledger.open_positions()
    finally:
        gateway._simulator.close_store()
        env.ledger.close()
