"""SQLite SideDeck PAPER outbox: restart, atomic local fills, kill switch."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import sqlite3

import pytest

from sidedeck.domain.contracts import MarketSnapshot, PriceType, Session, Side, TradeIntent
from sidedeck.domain.paper_desk import PaperDeskError, PaperFillEvidence
from sidedeck.domain.paper_outbox import DurablePaperDesk

AT = datetime(2026, 10, 16, 20, tzinfo=timezone.utc)


def request(portfolio: str, *, qty: str = "1", strategy: str = "v1"):
    snapshot = MarketSnapshot(
        instrument_id="US:AAPL", ticker="AAPL", provider="OFFLINE_FIXTURE",
        price_type=PriceType.EOD_CLOSE, price=Decimal("100"), session=Session.CLOSED,
        market_timestamp=AT, ingestion_timestamp=AT, quality="FIXTURE_NOT_LIVE",
    )
    intent = TradeIntent(
        experiment_id="paper-outbox-fixture", portfolio_id=portfolio,
        strategy_id=strategy, instrument_id="US:AAPL",
        side=Side.BUY, quantity=Decimal(qty), rationale="offline test",
        model_revision="fixture-v1", decision_timestamp=AT, data_as_of=AT,
        stop_price=Decimal("95"), invalidation="synthetic stop",
    )
    return intent, snapshot


def fill(draft, *, fill_id="FILL-1", qty="1", price="100", pid=None):
    return PaperFillEvidence(
        client_order_id=draft.client_order_id, broker_order_id="BROKER-ORDER-1",
        broker_fill_id=fill_id, portfolio_id=pid or draft.portfolio_id,
        key_slot=draft.key_slot, symbol=draft.symbol, side=draft.side,
        quantity=Decimal(qty), price=Decimal(price), fee=Decimal("0"),
        occurred_at=AT + timedelta(minutes=1),
    )


def test_reopen_preserves_two_independent_1000_ledgers_and_drafts(tmp_path):
    path = tmp_path / "paper.sqlite3"
    a = DurablePaperDesk(path)
    a.initialize(opened_at=AT - timedelta(days=1))
    one, mark = request("tradingagents")
    other, _ = request("ai-trading")
    first = a.prepare(one, mark, marks={"US:AAPL": mark})
    second = a.prepare(other, mark, marks={"US:AAPL": mark})
    assert first.client_order_id != second.client_order_id
    assert a.paper_write_enabled is False
    assert a.kill_switch_engaged is True
    restarted = DurablePaperDesk(path)
    assert restarted.prepare(one, mark, marks={"US:AAPL": mark}).client_order_id == first.client_order_id
    snap = restarted.snapshot()
    assert snap["strategies"]["tradingagents"]["key_slot"] == "ALPACA_API_KEY"
    assert snap["strategies"]["ai-trading"]["key_slot"] == "ALPACA_API_KEY2"
    assert snap["strategies"]["tradingagents"]["cash"] == "1000"
    assert snap["strategies"]["ai-trading"]["cash"] == "1000"
    assert all(len(s["orders"]) == 1 for s in snap["strategies"].values())
    assert snap["broker_writes_enabled"] is False


def test_restart_preserves_pending_slot_preventing_double_reservation(tmp_path):
    db = DurablePaperDesk(tmp_path / "paper.sqlite3")
    db.initialize(opened_at=AT - timedelta(days=1))
    intent, mark = request("tradingagents")
    db.prepare(intent, mark, marks={"US:AAPL": mark})
    reopened = DurablePaperDesk(db.path)
    competing = intent.model_copy(update={"strategy_id": "different"})
    with pytest.raises(PaperDeskError, match="unresolved"):
        reopened.prepare(competing, mark, marks={"US:AAPL": mark})


def test_verified_fixture_fill_recovers_exactly_once_across_restart(tmp_path):
    db = DurablePaperDesk(tmp_path / "paper.sqlite3")
    db.initialize(opened_at=AT - timedelta(days=1))
    intent, mark = request("tradingagents")
    draft = db.prepare(intent, mark, marks={"US:AAPL": mark})
    db.acknowledge(draft.client_order_id, broker_order_id="BROKER-ORDER-1")
    assert db.reconcile_fill(fill(draft)).applied
    reopened = DurablePaperDesk(db.path)
    assert reopened.reconcile_fill(fill(draft)).applied is False
    assert reopened.snapshot()["strategies"]["tradingagents"]["cash"] == "900"
    assert reopened.snapshot()["strategies"]["ai-trading"]["cash"] == "1000"
    assert reopened.snapshot()["strategies"]["tradingagents"]["positions"]["US:AAPL"] == "1"
    with sqlite3.connect(db.path) as raw:
        assert raw.execute("SELECT count(*) FROM paper_events").fetchone()[0] == 3
        assert raw.execute("SELECT count(*) FROM paper_fills").fetchone()[0] == 1


def test_partial_fills_persist_across_restart_and_stop_at_quantity(tmp_path):
    db = DurablePaperDesk(tmp_path / "paper.sqlite3")
    db.initialize(opened_at=AT - timedelta(days=1))
    intent, mark = request("ai-trading", qty="2")
    draft = db.prepare(intent, mark, marks={"US:AAPL": mark})
    db.acknowledge(draft.client_order_id, broker_order_id="BROKER-ORDER-1")
    first = db.reconcile_fill(fill(draft, qty="1"))
    assert first.order_status.value == "PARTIALLY_FILLED"
    new_db = DurablePaperDesk(db.path)
    with pytest.raises(PaperDeskError):
        new_db.reconcile_fill(fill(draft, fill_id="FILL-BAD", qty="2"))
    second = new_db.reconcile_fill(fill(draft, fill_id="FILL-2", qty="1"))
    assert second.order_status.value == "FILLED"
    assert new_db.snapshot()["strategies"]["ai-trading"]["cash"] == "800"
    assert new_db.snapshot()["strategies"]["tradingagents"]["cash"] == "1000"


def test_wrong_portfolio_conflicting_duplicate_and_bad_price_are_atomic(tmp_path):
    db = DurablePaperDesk(tmp_path / "paper.sqlite3")
    db.initialize(opened_at=AT - timedelta(days=1))
    intent, mark = request("tradingagents")
    draft = db.prepare(intent, mark, marks={"US:AAPL": mark})
    db.acknowledge(draft.client_order_id, broker_order_id="BROKER-ORDER-1")
    for evidence in (
        fill(draft, pid="ai-trading"),
        fill(draft, price="101"),
        fill(draft, qty="2"),
    ):
        with pytest.raises(PaperDeskError):
            db.reconcile_fill(evidence)
    with sqlite3.connect(db.path) as raw:
        assert raw.execute("SELECT count(*) FROM paper_fills").fetchone()[0] == 0
        assert raw.execute("SELECT count(*) FROM paper_events").fetchone()[0] == 2
    db.reconcile_fill(fill(draft))
    with pytest.raises(PaperDeskError, match="conflicting"):
        db.reconcile_fill(fill(draft, qty="0.5"))
    assert db.snapshot()["strategies"]["tradingagents"]["cash"] == "900"


def test_unrelated_sqlite_db_is_preserved_and_refused(tmp_path):
    path = tmp_path / "user.sqlite3"
    with sqlite3.connect(path) as raw:
        raw.execute("CREATE TABLE my_data(secret TEXT)")
        raw.execute("INSERT INTO my_data VALUES('DO_NOT_TOUCH')")
    with pytest.raises(PaperDeskError, match="not a SideDeck"):
        DurablePaperDesk(path)
    with sqlite3.connect(path) as raw:
        assert raw.execute("SELECT secret FROM my_data").fetchone()[0] == "DO_NOT_TOUCH"


def test_initialization_idempotent_never_resets_cash_or_broker(tmp_path):
    db = DurablePaperDesk(tmp_path / "paper.sqlite3")
    db.initialize(opened_at=AT - timedelta(days=1))
    i, mark = request("tradingagents")
    d = db.prepare(i, mark, marks={"US:AAPL": mark})
    db.acknowledge(d.client_order_id, broker_order_id="BROKER-ORDER-1")
    db.reconcile_fill(fill(d))
    db.initialize(opened_at=AT + timedelta(days=1))
    assert db.snapshot()["strategies"]["tradingagents"]["cash"] == "900"


def test_requires_initialization_and_keeps_broker_execution_disabled(tmp_path):
    db = DurablePaperDesk(tmp_path / "paper.sqlite3")
    i, mark = request("tradingagents")
    with pytest.raises(PaperDeskError, match="initialize"):
        db.prepare(i, mark, marks={"US:AAPL": mark})
    assert db.kill_switch_engaged
    assert db.paper_write_enabled is False
    assert not hasattr(db, "submit_order")
    assert not hasattr(db, "cancel_broker_order")
