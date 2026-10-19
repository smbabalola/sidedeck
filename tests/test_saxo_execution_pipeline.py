from datetime import datetime, timezone
from decimal import Decimal

from sidedeck.application.saxo_execution_history import BrokerExecution
from sidedeck.application.saxo_execution_pipeline import SaxoExecutionPipeline
from sidedeck.application.saxo_market_data import FxSnapshot
from sidedeck.application.saxo_order_lifecycle import advance_lifecycle, create_lifecycle, lifecycle_state
from sidedeck.application.foundation import initialise_two_portfolios
from sidedeck.domain.contracts import ExperimentManifest


def execution(status="FinalFill"):
    return BrokerExecution("22866064", "broker-1", "sofi-1", "fill-1", status,
                           Decimal("1"), Decimal("40"), Decimal("0.10"), "USD", "EUR",
                           "USD", "EUR",
                           "2026-10-19T14:00:00Z")


def test_fill_is_converted_posted_and_deduplicated(tmp_path):
    at = datetime(2026, 10, 19, 14, tzinfo=timezone.utc)
    ledger = initialise_two_portfolios(
        ExperimentManifest(experiment_id="p4", configuration_revision="r1",
                           created_at=at, instruments=("US:SOFI",), data_policy="licensed"), at)
    db = tmp_path / "p4.sqlite"
    create_lifecycle(db, "sofi-1")
    advance_lifecycle(db, "sofi-1", "SUBMITTING")
    advance_lifecycle(db, "sofi-1", "ACKNOWLEDGED", broker_order_id="broker-1",
                      broker_evidence=True)
    pipeline = SaxoExecutionPipeline(str(db), ledger)
    fx = FxSnapshot("fx", "EUR/USD", Decimal("1.10"), at, at, "verified")
    first = pipeline.apply_buy_fill(execution(), order_key="sofi-1",
                                    portfolio_id="tradingagents", fx=fx,
                                    account_id="22866064", now=at)
    second = pipeline.apply_buy_fill(execution(), order_key="sofi-1",
                                     portfolio_id="tradingagents", fx=fx,
                                     account_id="22866064", now=at)
    assert not first.duplicate and second.duplicate
    state = ledger.replay("tradingagents")
    assert state.positions["US:SOFI"].quantity == Decimal("1")
    assert state.cash == Decimal("1000") - Decimal("40") - Decimal("0.11")
    assert lifecycle_state(db, "sofi-1") == ("FILLED", "broker-1", 3)


def test_execution_cannot_cross_portfolio_or_account(tmp_path):
    at = datetime(2026, 10, 19, 14, tzinfo=timezone.utc)
    ledger = initialise_two_portfolios(
        ExperimentManifest(experiment_id="p4", configuration_revision="r1",
                           created_at=at, instruments=("US:SOFI",), data_policy="licensed"), at)
    pipeline = SaxoExecutionPipeline(str(tmp_path / "p4.sqlite"), ledger)
    fx = FxSnapshot("fx", "EUR/USD", Decimal("1.10"), at, at, "verified")
    try:
        pipeline.apply_buy_fill(execution(), order_key="sofi-1", portfolio_id="ai-trading",
                                fx=fx, account_id="wrong", now=at)
    except ValueError as exc:
        assert "matched" in str(exc)
    else:
        raise AssertionError("cross-account execution was accepted")


def test_pending_fill_recovers_after_ledger_failure(tmp_path):
    at = datetime(2026, 10, 19, 14, tzinfo=timezone.utc)
    original = initialise_two_portfolios(
        ExperimentManifest(experiment_id="p4", configuration_revision="r1",
                           created_at=at, instruments=("US:SOFI",), data_policy="licensed"), at)
    db = tmp_path / "recover.sqlite"
    create_lifecycle(db, "sofi-1")
    advance_lifecycle(db, "sofi-1", "SUBMITTING")
    advance_lifecycle(db, "sofi-1", "ACKNOWLEDGED", broker_order_id="broker-1",
                      broker_evidence=True)
    pipeline = SaxoExecutionPipeline(str(db), original)
    real_append = original.append

    def crash(event):
        raise RuntimeError("simulated ledger failure")

    original.append = crash  # type: ignore[method-assign]
    fx = FxSnapshot("fx", "EUR/USD", Decimal("1.10"), at, at, "verified")
    try:
        pipeline.apply_buy_fill(execution(), order_key="sofi-1", portfolio_id="tradingagents",
                                fx=fx, account_id="22866064", now=at)
    except RuntimeError:
        pass
    else:
        raise AssertionError("simulated ledger failure did not propagate")
    recovered_ledger = initialise_two_portfolios(
        ExperimentManifest(experiment_id="p4", configuration_revision="r1",
                           created_at=at, instruments=("US:SOFI",), data_policy="licensed"), at)
    recovered = SaxoExecutionPipeline(str(db), recovered_ledger)
    recovered_count = recovered.recover()
    assert recovered_count == 1
    assert recovered_ledger.replay("tradingagents").positions["US:SOFI"].quantity == Decimal("1")
    assert lifecycle_state(db, "sofi-1") == ("FILLED", "broker-1", 3)
    assert real_append is not None
