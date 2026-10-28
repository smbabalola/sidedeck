"""Offline ORB-to-native proposal acceptance; fixture evidence does not qualify live trading."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sidedeck.application.sd069_day_trader_methods import IntradayBar, METHOD_VERSION, orb_signal
from sidedeck.application.sd071_decision_engine import StrategyAdmission
from sidedeck.application.sd074_trusted_inputs import SourceRegistry, SourceSigner, TrustedSource
from sidedeck.application.sd123_day_demo_integration import DayResearchResult
from sidedeck.application.sd126_offline_day_controller import OfflineDayCycleController
from sidedeck.application.sd154_day_trader_offline_bridge import run_day_trader_offline_cycle

from test_sd063_autonomous_demo_policy import MSFT, _offline_gateway
from test_sd125_day_session_exits import _day_env


def test_real_orb_method_with_separately_sealed_native_fixture_drives_offline_entry_and_exit(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 11, 27, 15, 0, tzinfo=UTC)
    env = _day_env(tmp_path, now)
    gateway, planning_quote, quote_signer = _offline_gateway(
        env, fill_price="500", close_price="499",
    )
    native_source = TrustedSource("orb-native-fixture", "native_strategy_runner", b"n" * 40)
    research_source = TrustedSource("orb-research-fixture", "research_pipeline", b"s" * 40)
    # The fixture gateway normally has only quote and fill producers. Register
    # these two additional test-only producers, leaving the MAC verifier intact.
    verifier = gateway._runtime._verifier
    verifier._registry = SourceRegistry((
        TrustedSource("gateway-quotes", "broker_quotes", b"q" * 40),
        TrustedSource("gateway-recon", "broker_reconciliation", b"r" * 40),
        native_source, research_source,
    ))
    try:
        bars = tuple(
            IntradayBar(
                start=now - timedelta(minutes=30 - 5 * i),
                open=Decimal("500"),
                high=Decimal("502") if i < 3 else Decimal("505"),
                low=Decimal("499"), close=Decimal("501") if i < 3 else Decimal("504"),
                volume=Decimal("10000"),
            ) for i in range(4)
        )
        method = orb_signal(MSFT, bars, now)
        assert method is not None
        research = DayResearchResult(
            signal=method,
            admission=StrategyAdmission(
                method.source_id, METHOD_VERSION, "DAY", "RESEARCH_ONLY",
                "fixture-chart-not-oos", 0, False,
            ),
            metadata={"data_basis": "SYNTHETIC_FIXTURE"}, status="RESEARCH_ONLY",
        )
        native = SourceSigner(native_source, env.clock).seal({
            "source_kind": "NATIVE_STRATEGY", "canonical_id": MSFT,
            "track": "DAY", "strategy_id": "native_orb",
            "strategy_version": "test-v1", "direction": "LONG",
            "horizon_min_days": 0, "horizon_max_days": 0,
            "evidence": [{"kind": "backtest", "reference": "SD022.md", "sha256": "a" * 64}],
            "generated_at": now.isoformat(), "data_cutoff": method.data_cutoff.isoformat(),
            "invalidation": ["opening range invalidated"],
        })
        sealed_research = SourceSigner(research_source, env.clock).seal({
            "canonical_id": MSFT, "atr": "10", "sector": "Technology",
            "correlations": {}, "execution_eligible": True, "as_of": now.isoformat(),
        })
        controller = OfflineDayCycleController(gateway._runtime, gateway, clock=env.clock)
        # Research signals are never enough to create an entry.
        unadmitted = run_day_trader_offline_cycle(
            controller, research_result=research, native_signals=(native,),
            admissions=(), sealed_research=sealed_research,
            planning_quote=planning_quote,
        )
        assert unadmitted.cycle.open_positions == 0
        assert "INDEPENDENT_NATIVE_STRATEGY_ADMISSION_REQUIRED" in unadmitted.proposal_reasons
        assert gateway._simulator.submitted_orders == 0
        opened = run_day_trader_offline_cycle(
            controller, research_result=research, native_signals=(native,),
            admissions=(StrategyAdmission(
                "native_orb", "test-v1", "DAY", "ADMITTED", "SD022.md", 45, True,
            ),),
            sealed_research=sealed_research, planning_quote=planning_quote,
            send_quote=quote_signer.seal({
                "canonical_id": MSFT, "bid": "499.9", "ask": "500",
                "quote_time": (now - timedelta(seconds=5)).isoformat(),
            }),
        )
        assert opened.cycle.status == "ENTRY_CONFIRMED", opened
        assert opened.cycle.open_positions == 1
        assert opened.proposal_reasons == ()
        assert opened.cycle.entry_reference is not None
        assert gateway._simulator.submitted_orders == 1

        # Thanksgiving Friday is an early close. The existing DAY controller
        # manages the position and exits without a second hand-built entry.
        env.clock.now = datetime(2026, 11, 27, 17, 50, tzinfo=UTC)

        def bid():
            return quote_signer.seal({
                "canonical_id": MSFT, "bid": "499", "ask": "500",
                "quote_time": (env.clock.now - timedelta(seconds=5)).isoformat(),
            })

        closed = run_day_trader_offline_cycle(
            controller, research_result=research,
            planning_bids=(bid(),), execution_bids={MSFT: bid()},
        )
        assert closed.cycle.status == "EXITS_CONFIRMED", closed
        assert closed.cycle.open_positions == 0
        assert gateway._simulator.submitted_orders == 2
        assert not env.ledger.kill_switch_engaged()
        assert closed.report()["broker_execution"] == "DISABLED"
    finally:
        gateway._simulator.close_store()
        env.ledger.close()
