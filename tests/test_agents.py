from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import pytest
from alembic import command
from alembic.config import Config

from sidedeck.agents import (
    AITradingFixtureWorker,
    AgentRunCoordinator,
    AgentRunRequest,
    InMemoryAuditStore,
    MarketBundle,
    ProposalSchemaValidator,
    TradingAgentsFixtureWorker,
    SqlAuditStore,
    TradingAgentsAdapterBlocked,
    TradingAgentsProposalAdapter,
)
from sidedeck.domain.accounting import Ledger
from sidedeck.domain.contracts import MarketSnapshot, PriceType, Session, Side, TradeIntent
from sidedeck.infrastructure.database import create_database


AT = datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc)


def bundle() -> MarketBundle:
    return MarketBundle(
        bundle_id="fixture-bundle-1",
        decision_cutoff_utc=AT,
        snapshots=(
            MarketSnapshot(
                instrument_id="US:AAPL",
                ticker="AAPL",
                provider="fixture",
                price_type=PriceType.EOD_CLOSE,
                price=Decimal("100"),
                market_timestamp=AT,
                ingestion_timestamp=AT,
                session=Session.CLOSED,
                quality="fixture",
            ),
        ),
        allowed_instruments=("US:AAPL",),
        max_snapshot_age_seconds=3600,
        provenance="fixture://p2a/market-bundle-1",
    )


def request(
    adapter_id: str,
    portfolio_id: str = "tradingagents",
    adapter_revision: str = "fixture-1",
) -> AgentRunRequest:
    return AgentRunRequest(
        experiment_id="p2a-fixture",
        portfolio_id=portfolio_id,
        strategy_id="fixture-strategy",
        adapter_id=adapter_id,
        adapter_revision=adapter_revision,
        decision_cutoff_utc=AT,
        market_bundle_id="fixture-bundle-1",
        allowed_instruments=("US:AAPL",),
        configuration_ref="fixture-only",
        cash_usd=Decimal("1000"),
    )


def test_fixture_workers_are_deterministic_and_proposal_only() -> None:
    store = InMemoryAuditStore()
    coordinator = AgentRunCoordinator(store)
    trading_request = request(TradingAgentsFixtureWorker.adapter_id)
    hold_request = request(
        AITradingFixtureWorker.adapter_id,
        "ai-trading",
        AITradingFixtureWorker.revision,
    )

    first = coordinator.run(trading_request, bundle(), TradingAgentsFixtureWorker())
    second = coordinator.run(hold_request, bundle(), AITradingFixtureWorker())

    assert first.validation.accepted is True
    assert len(first.decision_ids) == 1
    assert second.validation.accepted is True
    assert second.decision_ids == ()
    assert len(store.records) == 2
    assert Ledger().events == ()


def test_gateway_rejects_spoofed_portfolio_and_unknown_instrument() -> None:
    run_request = request(TradingAgentsFixtureWorker.adapter_id)
    envelope = TradingAgentsFixtureWorker().propose(run_request, bundle())
    spoofed_intent = TradeIntent(
        experiment_id=run_request.experiment_id,
        portfolio_id="ai-trading",
        strategy_id="fixture-strategy",
        instrument_id="US:MSFT",
        side=Side.BUY,
        quantity=Decimal("1"),
        rationale="spoof",
        model_revision="fixture-1",
        decision_timestamp=AT,
        data_as_of=AT,
    )
    tampered = envelope.model_copy(update={"proposals": (spoofed_intent,)})

    result = ProposalSchemaValidator().validate(run_request, bundle(), tampered)

    assert result.accepted is False
    assert set(result.reason_codes) == {"PORTFOLIO_MISMATCH", "UNKNOWN_INSTRUMENT", "INPUT_HASH_MISMATCH"}
    assert set(result.invalid_fields) == {
        "decision_inputs_hash",
        "proposals[0].portfolio_id",
        "proposals[0].instrument_id",
    }


def test_gateway_rejects_lookahead_and_duplicate_proposals() -> None:
    run_request = request(TradingAgentsFixtureWorker.adapter_id)
    envelope = TradingAgentsFixtureWorker().propose(run_request, bundle())
    tampered = envelope.model_copy(
        update={"proposals": (envelope.proposals[0], envelope.proposals[0])}
    )
    future = envelope.proposals[0].model_copy(update={"data_as_of": AT.replace(day=3)})
    tampered = tampered.model_copy(update={"proposals": (future, future)})

    result = ProposalSchemaValidator().validate(run_request, bundle(), tampered)

    assert result.accepted is False
    assert "DUPLICATE_INSTRUMENT" in result.reason_codes
    assert "LOOKAHEAD_DATA" in result.reason_codes


def test_run_id_is_append_only_and_failed_output_is_audited() -> None:
    store = InMemoryAuditStore()
    coordinator = AgentRunCoordinator(store)
    run_request = request(TradingAgentsFixtureWorker.adapter_id)
    first = coordinator.run(run_request, bundle(), TradingAgentsFixtureWorker())
    with pytest.raises(ValueError, match="run_id"):
        coordinator.run(run_request, bundle(), TradingAgentsFixtureWorker())
    assert first.sanitized_output
    assert len(store.records) == 1


def test_both_fixture_workers_can_record_deterministic_refusal() -> None:
    store = InMemoryAuditStore()
    coordinator = AgentRunCoordinator(store)
    trading = request(TradingAgentsFixtureWorker.adapter_id)
    ai = request(AITradingFixtureWorker.adapter_id, "ai-trading", AITradingFixtureWorker.revision)

    trading_record = coordinator.run(trading, bundle(), TradingAgentsFixtureWorker(rejected=True))
    ai_record = coordinator.run(ai, bundle(), AITradingFixtureWorker(rejected=True))

    assert trading_record.validation.accepted is False
    assert ai_record.validation.accepted is False
    assert set(trading_record.validation.reason_codes) == {"MISSING_EVIDENCE", "WORKER_FAILURE"}
    assert set(ai_record.validation.reason_codes) == {"WORKER_FAILURE"}


def test_sql_audit_store_round_trips_immutable_run(tmp_path) -> None:
    url = f"sqlite:///{tmp_path / 'p2a.sqlite3'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    engine = create_database(url)
    store = SqlAuditStore(engine)
    run_request = request(TradingAgentsFixtureWorker.adapter_id)
    record = AgentRunCoordinator(store).run(run_request, bundle(), TradingAgentsFixtureWorker())

    restored = store.load_runs()

    assert restored == [record]
    with pytest.raises(ValueError, match="run_id"):
        store.append(record, TradingAgentsFixtureWorker().propose(run_request, bundle()))
    engine.dispose()


def test_tradingagents_adapter_uses_one_injected_graph_and_normalizes_proposal() -> None:
    calls: list[tuple[str, str]] = []

    class FakeGraph:
        def propagate(self, ticker: str, trade_date: str) -> tuple[object, object]:
            calls.append((ticker, trade_date))
            return {}, {"action": "BUY", "ticker": "AAPL", "quantity": "1", "stop_price": "95", "invalidation": "test stop"}

    run_request = request("tradingagents.upstream")
    run_request = run_request.model_copy(update={"upstream_sha": TradingAgentsProposalAdapter.upstream_sha})
    market_bundle = bundle()
    adapter = TradingAgentsProposalAdapter(FakeGraph(), enabled=True)
    envelope = adapter.propose(run_request, market_bundle)
    result = ProposalSchemaValidator().validate(run_request, market_bundle, envelope)

    assert result.accepted is True
    assert envelope.proposals[0].side is Side.BUY
    assert calls == [("AAPL", "2026-01-02")]


def test_tradingagents_adapter_is_blocked_without_explicit_runtime() -> None:
    run_request = request("tradingagents.upstream")
    with pytest.raises(TradingAgentsAdapterBlocked):
        TradingAgentsProposalAdapter().propose(run_request, bundle())
