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
from test_sd125_day_session_exits import _day_env, _day_entry


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


def test_orb_fixture_and_separately_admitted_native_offline_round_trip(tmp_path: Path):
    """Integration acceptance: ORB research exists; native fixture approval is separate.

    Does not assert ORB caused an entry: DAY_TRADER_METHOD cannot self-admit.
    Confirms both paths can coexist across an offline entry, flatten and restart.
    """
    now = datetime(2026, 11, 27, 15, 0, tzinfo=UTC)
    env = _day_env(tmp_path, now)
    gateway, quote, signer = _offline_gateway(
        env, fill_price="500", close_price="490",
        storage_path=tmp_path / "simulator.sqlite3",
    )
    try:
        bars = tuple(
            IntradayBar(
                start=now - timedelta(minutes=30 - i * 5),
                open=Decimal("500"), high=Decimal("502") if i < 3 else Decimal("505"),
                low=Decimal("499"), close=Decimal("501") if i < 3 else Decimal("504"),
                volume=Decimal("10000"),
            ) for i in range(4)
        )
        method_signal = orb_signal(MSFT, bars, now)
        assert method_signal is not None
        controller = OfflineDayCycleController(gateway._runtime, gateway, clock=env.clock)
        # The separately admitted fixture-native signal still requires SD-063 approval.
        admitted_fixture_proposal = _day_entry(env)
        opened = controller.tick(entry=admitted_fixture_proposal, entry_quote=quote)
        assert opened.status == "ENTRY_CONFIRMED"
        assert opened.open_positions == 1

        env.clock.now = datetime(2026, 11, 27, 17, 50, tzinfo=UTC)
        research = DayResearchResult(
            signal=method_signal,
            admission=StrategyAdmission(
                method_signal.source_id, METHOD_VERSION, "DAY",
                "RESEARCH_ONLY", "fixture-chart-not-oos", 0, False,
            ),
            metadata={"data_basis": "SYNTHETIC_FIXTURE"}, status="RESEARCH_ONLY",
        )
        def bid():
            return signer.seal({
                "canonical_id": MSFT, "bid": "499", "ask": "500",
                "quote_time": (env.clock.now - timedelta(seconds=5)).isoformat(),
            })
        closed = run_day_trader_offline_cycle(
            controller, research_result=research,
            planning_bids=(bid(),), execution_bids={MSFT: bid()},
        )
        assert closed.cycle.status == "EXITS_CONFIRMED"
        assert closed.cycle.open_positions == 0
        assert gateway._simulator.submitted_orders == 1
        assert not env.ledger.kill_switch_engaged()
    finally:
        gateway._simulator.close_store()
        env.ledger.close()
