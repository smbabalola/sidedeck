"""Full local journal → paper GET evidence → discrepancy report, all offline."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import sqlite3
from uuid import uuid4

import pytest

from sidedeck.domain.alpaca_paper import AlpacaPaperError
from sidedeck.domain.contracts import MarketSnapshot, PriceType, Session, Side, TradeIntent
from sidedeck.domain.paper_desk import PaperDeskError
from sidedeck.domain.paper_outbox import DurablePaperDesk
from sidedeck.domain.paper_receipt_review import SideDeckPaperReceiptReview

AT = datetime(2026, 10, 16, 20, tzinfo=timezone.utc)
BID = "cc5ad190-739f-4520-b5e1-d616dff729aa"
FILL_ID = "20261016200100000::d39f7dde-bd83-4b91-8b3b-9672aacbcdf5"


def draft(db, portfolio):
    mark = MarketSnapshot(
        instrument_id="US:AAPL", ticker="AAPL", provider="FIXTURE",
        price_type=PriceType.EOD_CLOSE, price=Decimal("100"),
        market_timestamp=AT, ingestion_timestamp=AT, session=Session.CLOSED,
        quality="FIXTURE_NOT_LIVE",
    )
    intent = TradeIntent(
        experiment_id="paper-receipt-review", portfolio_id=portfolio,
        strategy_id=f"strat-{portfolio}", instrument_id="US:AAPL",
        side=Side.BUY, quantity=Decimal("1"),
        rationale="offline fixture", model_revision="fixture-no-llm",
        decision_timestamp=AT, data_as_of=AT, stop_price=Decimal("95"),
        invalidation="synthetic stop",
    )
    return db.prepare(intent, mark, marks={"US:AAPL": mark})


class FixturePaper:
    def __init__(self, order_draft):
        self.draft = order_draft
        self.calls = []
    def get(self, path, params):
        self.calls.append((path, dict(params)))
        if path.endswith(":by_client_order_id"):
            payload = {
                "id": BID, "client_order_id": self.draft.client_order_id,
                "symbol": "AAPL", "side": "buy", "qty": "1",
                "filled_qty": "1", "type": "limit", "time_in_force": "day",
                "limit_price": "100", "status": "filled",
            }
        else:
            payload = [{
                "id": FILL_ID, "activity_type": "FILL", "type": "fill",
                "order_id": BID, "side": "buy", "symbol": "AAPL",
                "qty": "1", "price": "99.50", "cum_qty": "1",
                "transaction_time": "2026-10-16T20:01:00Z",
            }]
        return 200, json.dumps(payload).encode()


def test_receipt_lookup_matches_local_durable_order_and_never_posts_fills(tmp_path):
    db = DurablePaperDesk(tmp_path / "paper.sqlite3")
    db.initialize(opened_at=AT - timedelta(minutes=3))
    first = draft(db, "tradingagents")
    second = draft(db, "ai-trading")
    t = FixturePaper(first)
    result = SideDeckPaperReceiptReview(
        db, t, key_slot=first.key_slot,
    ).inspect(first.client_order_id, observed_at=AT + timedelta(minutes=5))
    assert result.portfolio_id == "tradingagents"
    assert result.needs_review and not result.auto_post_enabled
    assert result.paper_filled_qty == Decimal("1")
    assert result.journal_filled_qty == Decimal("0")
    assert result.unverified_activity_ids == (FILL_ID,)
    assert len(t.calls) == 2
    assert db.snapshot()["strategies"]["tradingagents"]["cash"] == "1000"
    assert db.snapshot()["strategies"]["ai-trading"]["cash"] == "1000"
    assert second.client_order_id != first.client_order_id
    with sqlite3.connect(db.path) as connection:
        assert connection.execute("SELECT count(*) FROM paper_fills").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM paper_events").fetchone()[0] == 2


def test_key_slot_mismatch_makes_no_paper_get(tmp_path):
    db = DurablePaperDesk(tmp_path / "paper.sqlite3")
    db.initialize(opened_at=AT - timedelta(minutes=3))
    first = draft(db, "tradingagents")
    t = FixturePaper(first)
    with pytest.raises(AlpacaPaperError, match="slot"):
        SideDeckPaperReceiptReview(db, t, key_slot="ALPACA_API_KEY2").inspect(
            first.client_order_id, observed_at=AT + timedelta(minutes=5),
        )
    assert t.calls == []


def test_unknown_durable_order_does_not_contact_alpaca(tmp_path):
    db = DurablePaperDesk(tmp_path / "paper.sqlite3")
    db.initialize(opened_at=AT - timedelta(minutes=3))
    first = draft(db, "tradingagents")
    t = FixturePaper(first)
    with pytest.raises(PaperDeskError, match="unknown"):
        SideDeckPaperReceiptReview(db, t, key_slot=first.key_slot).inspect(
            f"sd-ta-{uuid4().hex}", observed_at=AT,
        )
    assert t.calls == []


def test_restart_reconciliation_only_reports_and_never_creates_orders(tmp_path):
    db = DurablePaperDesk(tmp_path / "paper.sqlite3")
    db.initialize(opened_at=AT - timedelta(minutes=3))
    first = draft(db, "tradingagents")
    db2 = DurablePaperDesk(db.path)
    t = FixturePaper(first)
    viewer = SideDeckPaperReceiptReview(db2, t, key_slot=first.key_slot)
    old = db2.snapshot()
    a = viewer.inspect(first.client_order_id, observed_at=AT + timedelta(minutes=5))
    b = viewer.inspect(first.client_order_id, observed_at=AT + timedelta(minutes=5))
    assert a == b
    assert db2.snapshot() == old
    assert a.paper_trading_enabled is False
