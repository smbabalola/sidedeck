from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import pytest

from sidedeck.application.saxo_execution_history import BrokerExecution
from sidedeck.application.saxo_execution_pipeline import SaxoExecutionPipeline
from sidedeck.application.saxo_market_data import FxSnapshot
from sidedeck.application.saxo_order_lifecycle import advance_lifecycle, create_lifecycle, lifecycle_state
from sidedeck.application.foundation import initialise_two_portfolios
from sidedeck.domain.contracts import ExperimentManifest


def execution(status="FinalFill", quantity="1", execution_id="fill-1"):
    return BrokerExecution("22866064", "broker-1", "sofi-1", execution_id, status,
                           Decimal(quantity), Decimal("40"), Decimal("0.10"), "USD", "EUR",
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


def test_successful_posting_reloads_all_economic_state_after_restart(tmp_path):
    at = datetime(2026, 10, 19, 14, tzinfo=timezone.utc)
    manifest = ExperimentManifest(experiment_id="p4", configuration_revision="r1",
                                  created_at=at, instruments=("US:SOFI",), data_policy="licensed")
    ledger = initialise_two_portfolios(manifest, at)
    db = tmp_path / "restart.sqlite"
    create_lifecycle(db, "sofi-1")
    advance_lifecycle(db, "sofi-1", "SUBMITTING")
    advance_lifecycle(db, "sofi-1", "ACKNOWLEDGED", broker_order_id="broker-1", broker_evidence=True)
    fx = FxSnapshot("fx", "EUR/USD", Decimal("1.10"), at, at, "verified")
    SaxoExecutionPipeline(str(db), ledger).apply_buy_fill(
        execution(), order_key="sofi-1", portfolio_id="tradingagents", fx=fx,
        account_id="22866064", now=at)
    restarted_ledger = initialise_two_portfolios(manifest, at)
    restarted = SaxoExecutionPipeline(str(db), restarted_ledger)
    assert restarted.recover() == 1
    state = restarted_ledger.replay("tradingagents")
    assert state.cash == Decimal("959.89")
    assert state.positions["US:SOFI"].quantity == Decimal("1")
    assert state.positions["US:SOFI"].cost_basis == Decimal("40")
    assert state.fees == Decimal("0.11")
    assert restarted.recover() == 0
    assert len(restarted_ledger.events) == 3


def test_recovery_is_concurrent_and_final_fill_cannot_overfill(tmp_path):
    at = datetime(2026, 10, 19, 14, tzinfo=timezone.utc)
    manifest = ExperimentManifest(experiment_id="p4", configuration_revision="r1",
                                  created_at=at, instruments=("US:SOFI",), data_policy="licensed")
    source = initialise_two_portfolios(manifest, at)
    db = tmp_path / "concurrent.sqlite"
    create_lifecycle(db, "sofi-1")
    advance_lifecycle(db, "sofi-1", "SUBMITTING")
    advance_lifecycle(db, "sofi-1", "ACKNOWLEDGED", broker_order_id="broker-1", broker_evidence=True)
    fx = FxSnapshot("fx", "EUR/USD", Decimal("1.10"), at, at, "verified")
    pipeline = SaxoExecutionPipeline(str(db), source)
    pipeline.apply_buy_fill(execution(status="Fill", execution_id="fill-part", quantity="1"),
                            order_key="sofi-1", portfolio_id="tradingagents", fx=fx,
                            account_id="22866064", now=at, authorized_quantity=Decimal("2"))
    with pytest.raises(ValueError, match="quantity"):
        pipeline.apply_buy_fill(execution(status="FinalFill", execution_id="fill-over", quantity="2"),
                                order_key="sofi-1", portfolio_id="tradingagents", fx=fx,
                                account_id="22866064", now=at, authorized_quantity=Decimal("2"))
    ledgers = [initialise_two_portfolios(manifest, at) for _ in range(2)]
    pipelines = [SaxoExecutionPipeline(str(db), item) for item in ledgers]
    with ThreadPoolExecutor(max_workers=2) as pool:
        counts = list(pool.map(lambda item: item.recover(), pipelines))
    assert counts == [1, 1]
    assert all(item.replay("tradingagents").positions["US:SOFI"].quantity == Decimal("1")
               for item in ledgers)
