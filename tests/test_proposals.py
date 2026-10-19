from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sidedeck.application.proposals import evaluate_proposal
from sidedeck.domain.contracts import (
    ExperimentManifest, MarketSnapshot, PriceType, Session, Side, TradeIntent,
)

AT = datetime(2026, 10, 19, 16, 0, tzinfo=timezone.utc)


def make_case():
    manifest = ExperimentManifest(
        experiment_id="exp-p2", configuration_revision="v1",
        created_at=AT - timedelta(days=1), instruments=("US:AAPL",),
        data_policy="verified-eod",
    )
    snap = MarketSnapshot(
        instrument_id="US:AAPL", ticker="AAPL", provider="test-fixture",
        price_type=PriceType.EOD_CLOSE, currency="USD", price=Decimal("150"),
        market_timestamp=AT - timedelta(hours=1),
        ingestion_timestamp=AT - timedelta(minutes=30),
        session=Session.CLOSED, quality="synthetic-test-only",
    )
    intent = TradeIntent(
        experiment_id="exp-p2", portfolio_id="tradingagents", strategy_id="test",
        instrument_id="US:AAPL", side=Side.BUY, quantity=Decimal("1"),
        rationale="deterministic unit test", model_revision="test-v1",
        decision_timestamp=AT, data_as_of=snap.market_timestamp,
    )
    return manifest, snap, intent


def test_accepts_proposal_without_order():
    manifest, snap, intent = make_case()
    result = evaluate_proposal(intent, manifest, snap, max_market_age=timedelta(hours=2))
    assert result.accepted and result.reason == "proposal_only"
    assert result.intent is intent


def test_rejects_wrong_portfolio():
    manifest, snap, intent = make_case()
    intent = intent.model_copy(update={"portfolio_id": "other"})
    result = evaluate_proposal(intent, manifest, snap, max_market_age=timedelta(hours=2))
    assert not result.accepted and result.reason == "portfolio_not_authorized"


def test_rejects_wrong_snapshot():
    manifest, snap, intent = make_case()
    snap = snap.model_copy(update={"instrument_id": "US:SPY"})
    result = evaluate_proposal(intent, manifest, snap, max_market_age=timedelta(hours=2))
    assert not result.accepted and result.reason == "snapshot_instrument_mismatch"


def test_rejects_stale_snapshot():
    manifest, snap, intent = make_case()
    result = evaluate_proposal(intent, manifest, snap, max_market_age=timedelta(minutes=5))
    assert not result.accepted


def test_rejects_asof_mismatch():
    manifest, snap, intent = make_case()
    intent = intent.model_copy(update={"data_as_of": AT})
    result = evaluate_proposal(intent, manifest, snap, max_market_age=timedelta(hours=2))
    assert not result.accepted and result.reason == "snapshot_asof_mismatch"


def test_rejects_nonallowlisted_instrument():
    manifest, snap, intent = make_case()
    intent = intent.model_copy(update={"instrument_id": "US:XYZ"})
    result = evaluate_proposal(intent, manifest, snap, max_market_age=timedelta(hours=2))
    assert not result.accepted and result.reason == "instrument_not_in_experiment"
