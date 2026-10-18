"""SideDeck PAPER order control plane: offline, no broker operations."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from sidedeck.domain.accounting import Ledger, opening_event
from sidedeck.domain.contracts import MarketSnapshot, PriceType, Session, Side, TradeIntent
from sidedeck.domain.paper_desk import (
    BROKER_KEY_SLOTS, DeskOrderStatus, PaperDeskError, PaperFillEvidence,
    SideDeckPaperDesk,
)

AT = datetime(2026, 10, 16, 20, tzinfo=timezone.utc)


def fixture(portfolio_id: str = "tradingagents", side: Side = Side.BUY, qty="1"):
    ledger = Ledger()
    ledger.append(opening_event("tradingagents", AT - timedelta(minutes=1)))
    ledger.append(opening_event("ai-trading", AT - timedelta(minutes=1)))
    mark = MarketSnapshot(
        instrument_id="US:AAPL", ticker="AAPL", provider="FIXTURE-NOT-REAL",
        price_type=PriceType.EOD_CLOSE, currency="USD", price=Decimal("100"),
        market_timestamp=AT, ingestion_timestamp=AT, session=Session.CLOSED,
        quality="FIXTURE-NOT-REAL",
    )
    intent = TradeIntent(
        experiment_id="paper-test", portfolio_id=portfolio_id,
        strategy_id="strat-1", instrument_id="US:AAPL", side=side,
        quantity=Decimal(qty), rationale="offline test only",
        model_revision="stub-1", decision_timestamp=AT,
        data_as_of=AT, stop_price=Decimal("95"),
        invalidation="close below 95",
    )
    return ledger, mark, intent


def plan(desk, ledger, mark, intent):
    return desk.prepare(
        intent, ledger.replay(intent.portfolio_id),
        mark, marks={"US:AAPL": mark},
    )[0]


def paper_fill(draft, **changes):
    fields = dict(
        client_order_id=draft.client_order_id, broker_order_id="PAPER-ORDER-X",
        broker_fill_id="FILL-ONE", portfolio_id=draft.portfolio_id,
        key_slot=draft.key_slot, symbol=draft.symbol, side=draft.side,
        quantity=Decimal("1"), price=Decimal("100"),
        fee=Decimal("0"), occurred_at=AT + timedelta(minutes=1),
    )
    fields.update(changes)
    return PaperFillEvidence(**fields)


def test_two_strategies_stay_distinct_and_paper_write_is_absent():
    desk = SideDeckPaperDesk()
    ledger, mark, first = fixture()
    second = first.model_copy(update={"portfolio_id": "ai-trading"})
    a = plan(desk, ledger, mark, first)
    b = plan(desk, ledger, mark, second)
    assert a.key_slot == "ALPACA_API_KEY"
    assert b.key_slot == "ALPACA_API_KEY2"
    assert BROKER_KEY_SLOTS == {
        "tradingagents": "ALPACA_API_KEY",
        "ai-trading": "ALPACA_API_KEY2",
    }
    assert a.client_order_id != b.client_order_id
    assert a.local_order_id != b.local_order_id
    assert a.limit_price == b.limit_price == Decimal("100")
    assert a.submission_enabled is False
    assert desk.paper_write_enabled is False
    assert not hasattr(desk, "submit")
    assert not hasattr(desk, "cancel_order")
    assert a.alpaca_preview()["time_in_force"] == "day"
    assert a.alpaca_preview()["type"] == "limit"
    assert a.alpaca_preview()["extended_hours"] is False
    assert ledger.replay("tradingagents").cash == Decimal("1000")
    assert ledger.replay("ai-trading").cash == Decimal("1000")


def test_idempotent_preparation_and_prevention_of_overlapping_unreserved_orders():
    desk = SideDeckPaperDesk()
    ledger, mark, intent = fixture()
    original = plan(desk, ledger, mark, intent)
    duplicate = plan(desk, ledger, mark, intent)
    assert duplicate.client_order_id == original.client_order_id
    next_intent = intent.model_copy(update={"strategy_id": "another"})
    with pytest.raises(PaperDeskError, match="unresolved"):
        plan(desk, ledger, mark, next_intent)


@pytest.mark.parametrize("qty", ["3", "5", "0.5"])
def test_position_cap_and_fractional_orders_cannot_escape_risk(qty):
    desk = SideDeckPaperDesk()
    ledger, mark, intent = fixture(qty=qty)
    with pytest.raises(PaperDeskError):
        plan(desk, ledger, mark, intent)


def test_hold_or_notional_cannot_be_submitted_as_orders():
    desk = SideDeckPaperDesk()
    ledger, mark, intent = fixture()
    hold = intent.model_copy(update={"side": Side.HOLD, "quantity": None})
    with pytest.raises(PaperDeskError, match="HOLD"):
        plan(desk, ledger, mark, hold)
    notional = intent.model_copy(update={"quantity": None, "notional_usd": Decimal("100")})
    with pytest.raises(PaperDeskError, match="quantity"):
        plan(desk, ledger, mark, notional)


def test_mismatched_portfolio_state_and_marks_fail_closed():
    desk = SideDeckPaperDesk()
    ledger, mark, intent = fixture()
    with pytest.raises(PaperDeskError, match="identity"):
        desk.prepare(intent, ledger.replay("ai-trading"), mark, marks={"US:AAPL": mark})
    with pytest.raises(PaperDeskError, match="mark"):
        desk.prepare(intent, ledger.replay("tradingagents"), mark, marks={})


def test_broker_ack_and_fill_reconciliation_mutate_only_intended_ledger():
    desk = SideDeckPaperDesk()
    ledger, mark, first = fixture()
    second = first.model_copy(update={"portfolio_id": "ai-trading"})
    draft = plan(desk, ledger, mark, first)
    other = plan(desk, ledger, mark, second)
    desk.acknowledge(draft.client_order_id, broker_order_id="PAPER-ORDER-X")
    evidence = paper_fill(draft)
    result = desk.reconcile_fill(evidence, ledger)
    assert result.applied
    assert result.order_status is DeskOrderStatus.FILLED
    assert ledger.replay("tradingagents").cash == Decimal("900")
    assert ledger.replay("tradingagents").positions["US:AAPL"].quantity == 1
    assert ledger.replay("ai-trading").cash == Decimal("1000")
    assert ledger.replay("ai-trading").positions == {}
    assert desk.reconcile_fill(evidence, ledger).applied is False
    assert len(ledger.events) == 3
    assert other.client_order_id != draft.client_order_id
    assert any(e.causation_id == draft.local_order_id for e in ledger.events)


@pytest.mark.parametrize("change", [
    {"portfolio_id": "ai-trading"},
    {"key_slot": "ALPACA_API_KEY2"},
    {"symbol": "MSFT"},
    {"side": "sell"},
    {"broker_order_id": "MISMATCHED-BROKER-ORDER"},
    {"price": Decimal("101")},
    {"quantity": Decimal("2")},
    {"fee": Decimal("-1")},
    {"broker_fill_id": ""},
])
def test_wrong_broker_identity_or_economic_execution_rejected(change):
    desk = SideDeckPaperDesk()
    ledger, mark, intent = fixture()
    draft = plan(desk, ledger, mark, intent)
    desk.acknowledge(draft.client_order_id, broker_order_id="PAPER-ORDER-X")
    with pytest.raises(PaperDeskError):
        desk.reconcile_fill(paper_fill(draft, **change), ledger)
    assert ledger.replay("tradingagents").cash == Decimal("1000")


def test_never_fill_without_acknowledged_broker_order():
    desk = SideDeckPaperDesk()
    ledger, mark, intent = fixture()
    draft = plan(desk, ledger, mark, intent)
    with pytest.raises(PaperDeskError, match="acknowledged"):
        desk.reconcile_fill(paper_fill(draft), ledger)


def test_partial_fill_and_overfill_guard_and_evidence_conflict():
    desk = SideDeckPaperDesk()
    ledger, mark, intent = fixture(qty="2")
    draft = plan(desk, ledger, mark, intent)
    desk.acknowledge(draft.client_order_id, broker_order_id="PAPER-ORDER-X")
    first = paper_fill(draft, quantity=Decimal("1"))
    a = desk.reconcile_fill(first, ledger)
    assert a.order_status is DeskOrderStatus.PARTIALLY_FILLED
    with pytest.raises(PaperDeskError, match="conflicting"):
        desk.reconcile_fill(paper_fill(draft, quantity=Decimal("0.5")), ledger)
    with pytest.raises(PaperDeskError, match="over-executes"):
        desk.reconcile_fill(paper_fill(draft, broker_fill_id="MORE", quantity=Decimal("2")), ledger)
    result = desk.reconcile_fill(paper_fill(draft, broker_fill_id="SECOND"), ledger)
    assert result.order_status is DeskOrderStatus.FILLED
    assert len(ledger.events) == 4


def test_cancel_unfilled_draft_releases_one_portfolio_slot():
    desk = SideDeckPaperDesk()
    ledger, mark, intent = fixture()
    draft = plan(desk, ledger, mark, intent)
    desk.close_unfilled(draft.client_order_id)
    later = intent.model_copy(update={"strategy_id": "new-strategy"})
    assert plan(desk, ledger, mark, later).client_order_id != draft.client_order_id
    with pytest.raises(PaperDeskError, match="closed"):
        desk.reconcile_fill(paper_fill(draft), ledger)


def test_prepared_sell_requires_real_holding_and_supports_realized_gain():
    desk = SideDeckPaperDesk()
    ledger, mark, buy_intent = fixture()
    buy_draft = plan(desk, ledger, mark, buy_intent)
    desk.acknowledge(buy_draft.client_order_id, broker_order_id="PAPER-ORDER-X")
    desk.reconcile_fill(paper_fill(buy_draft), ledger)
    sell = buy_intent.model_copy(update={
        "side": Side.SELL, "stop_price": Decimal("95"),
        "strategy_id": "exit-1",
    })
    sell_draft = plan(desk, ledger, mark, sell)
    assert sell_draft.side == "sell"
    desk.acknowledge(sell_draft.client_order_id, broker_order_id="SELL-BROKER")
    fill = paper_fill(sell_draft, broker_order_id="SELL-BROKER", broker_fill_id="SELL-FILL", price=Decimal("101"))
    desk.reconcile_fill(fill, ledger)
    assert ledger.replay("tradingagents").positions == {}
    assert ledger.replay("tradingagents").cash == Decimal("1001")
    assert ledger.replay("ai-trading").cash == Decimal("1000")
