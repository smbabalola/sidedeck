"""Alpaca paper order and FILL reader: entirely fixture/injected offline."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from uuid import UUID

import pytest

from sidedeck.domain.accounting import Ledger, opening_event
from sidedeck.domain.alpaca_paper import (
    AlpacaPaperAccessBlocked, AlpacaPaperError, validate_paper_get,
)
from sidedeck.domain.alpaca_paper_execution import (
    AlpacaPaperOrderReader, compare_paper_order,
)
from sidedeck.domain.contracts import MarketSnapshot, PriceType, Session, Side, TradeIntent
from sidedeck.domain.paper_desk import SideDeckPaperDesk

AT = datetime(2026, 10, 16, 20, tzinfo=timezone.utc)
BID = "be2aaf31-b414-4f76-a12b-7c272ef40565"
AID = "20261016200000000::0b94864f-27b6-42d3-9c94-101d6ed97fb1"


def draft(portfolio="tradingagents"):
    ledger = Ledger()
    ledger.append(opening_event(portfolio, AT - timedelta(minutes=1)))
    snap = MarketSnapshot(
        instrument_id="US:AAPL", ticker="AAPL", provider="FIXTURE",
        price_type=PriceType.EOD_CLOSE, price=Decimal("100"),
        market_timestamp=AT, ingestion_timestamp=AT, session=Session.CLOSED,
        quality="FIXTURE-NOT-LIVE",
    )
    intent = TradeIntent(
        experiment_id="paper-reconciliation-fixture", portfolio_id=portfolio,
        strategy_id="sd-12f", instrument_id="US:AAPL", side=Side.BUY,
        quantity=Decimal("2"), rationale="offline fixture",
        model_revision="fixture-1", decision_timestamp=AT,
        data_as_of=AT, stop_price=Decimal("95"),
        invalidation="synthetic stop",
    )
    return SideDeckPaperDesk().prepare(
        intent, ledger.replay(portfolio), snap, marks={"US:AAPL": snap}
    )[0]


def order_json(d):
    return {
        "id": BID, "client_order_id": d.client_order_id,
        "symbol": d.symbol, "side": d.side, "qty": "2",
        "filled_qty": "2", "type": "limit", "time_in_force": "day",
        "limit_price": str(d.limit_price), "order_class": "simple",
        "extended_hours": False, "status": "filled",
    }


def fill_json(d):
    return [{
        "id": AID, "activity_type": "FILL", "type": "fill",
        "order_id": BID, "side": d.side, "symbol": d.symbol,
        "qty": "2", "price": "99.5", "cum_qty": "2",
        "transaction_time": "2026-10-16T20:01:00Z",
    }]


class FixtureTransport:
    def __init__(self, order, activities, status=200):
        self.order = order
        self.activities = activities
        self.status = status
        self.calls = []

    def get(self, path, params):
        self.calls.append((path, dict(params)))
        if self.status != 200:
            return self.status, b'{"secret":"not-exposed"}'
        data = self.order if path.endswith(":by_client_order_id") else self.activities
        return 200, json.dumps(data).encode()


def test_bounded_get_order_and_activities_and_no_auto_post():
    d = draft()
    t = FixtureTransport(order_json(d), fill_json(d))
    order, fills = AlpacaPaperOrderReader(t, key_slot=d.key_slot).fetch(
        d, observed_at=AT + timedelta(minutes=5),
    )
    assert len(t.calls) == 2
    assert t.calls[0] == (
        "/v2/orders:by_client_order_id", {"client_order_id": d.client_order_id},
    )
    assert t.calls[1] == (
        "/v2/account/activities/FILL",
        {"order_id": BID, "direction": "asc", "page_size": "100"},
    )
    assert order.filled_qty == Decimal("2")
    assert len(fills) == 1 and fills[0].fee_verified is False
    report = compare_paper_order(
        d, order, fills, [{"client_order_id": d.client_order_id, "filled_quantity": "0"}],
    )
    assert report.needs_review
    assert report.paper_filled_qty == 2
    assert report.auto_post_enabled is False
    assert report.paper_trading_enabled is False
    assert report.missing_fill_activity_ids == (AID,)


def test_ai_trading_key_slot_is_not_interchangeable():
    d = draft("ai-trading")
    t = FixtureTransport(order_json(d), fill_json(d))
    with pytest.raises(AlpacaPaperError, match="slot"):
        AlpacaPaperOrderReader(t, key_slot="ALPACA_API_KEY").fetch(
            d, observed_at=AT + timedelta(minutes=5),
        )
    assert t.calls == []


@pytest.mark.parametrize("path,params", [
    ("/v2/orders:by_client_order_id", {"client_order_id": "not-sidedeck"}),
    ("/v2/orders:by_client_order_id", {}),
    ("/v2/account/activities/FILL", {"order_id": "not-uuid"}),
    ("/v2/account/activities/FILL", {"order_id": BID, "direction": "desc", "page_size": "100"}),
    ("/v2/account/activities/FILL", {"order_id": BID, "direction": "asc", "page_size": "500"}),
    ("/v2/account/activities/FILL", {"order_id": BID, "direction": "asc", "page_size": "100", "page_token": "bad/path"}),
    ("/v2/account/activities/DIV", {}),
    ("/v2/orders", {"status": "all", "limit": "100"}),
])
def test_read_routes_fail_closed(path, params):
    with pytest.raises(AlpacaPaperError):
        validate_paper_get(path, params)


@pytest.mark.parametrize("change", [
    {"id": "invalid-id"},
    {"client_order_id": "other"},
    {"symbol": "TSLA"},
    {"side": "sell"},
    {"type": "market"},
    {"time_in_force": "gtc"},
    {"qty": "5"},
    {"filled_qty": "3"},
    {"limit_price": "101"},
    {"order_class": "bracket"},
    {"extended_hours": True},
    {"status": "unknown"},
])
def test_wrong_paper_order_rejected_before_fill_get(change):
    d = draft()
    t = FixtureTransport({**order_json(d), **change}, fill_json(d))
    with pytest.raises(AlpacaPaperError):
        AlpacaPaperOrderReader(t, key_slot=d.key_slot).fetch(
            d, observed_at=AT + timedelta(minutes=5),
        )
    assert len(t.calls) == 1


@pytest.mark.parametrize("change", [
    {"activity_type": "DIV"}, {"type": "trade_correct"},
    {"order_id": "unrelated"}, {"symbol": "BTCUSD"},
    {"side": "sell"}, {"qty": "-1"}, {"price": "101"},
    {"cum_qty": "3"}, {"transaction_time": "2026-10-16T22:00:00Z"},
    {"id": ""},
])
def test_wrong_fill_rejected_without_journal_mutation(change):
    d = draft()
    t = FixtureTransport(order_json(d), [{**fill_json(d)[0], **change}])
    with pytest.raises(AlpacaPaperError):
        AlpacaPaperOrderReader(t, key_slot=d.key_slot).fetch(
            d, observed_at=AT + timedelta(minutes=5),
        )


def test_missing_fill_gaps_fail_closed():
    d = draft()
    t = FixtureTransport(order_json(d), [])
    with pytest.raises(AlpacaPaperError, match="total"):
        AlpacaPaperOrderReader(t, key_slot=d.key_slot).fetch(
            d, observed_at=AT + timedelta(minutes=5),
        )


def test_status_403_stops_after_one_get():
    d = draft()
    t = FixtureTransport(order_json(d), fill_json(d), status=403)
    with pytest.raises(AlpacaPaperAccessBlocked):
        AlpacaPaperOrderReader(t, key_slot=d.key_slot).fetch(
            d, observed_at=AT + timedelta(minutes=5),
        )
    assert len(t.calls) == 1


def test_reconciled_quantity_is_read_only_not_double_posted():
    d = draft()
    t = FixtureTransport(order_json(d), fill_json(d))
    order, fills = AlpacaPaperOrderReader(t, key_slot=d.key_slot).fetch(
        d, observed_at=AT + timedelta(minutes=5),
    )
    report = compare_paper_order(
        d, order, fills,
        [{"client_order_id": d.client_order_id, "filled_quantity": "2"}],
    )
    assert report.needs_review is False
    assert report.missing_fill_activity_ids == ()
    assert not report.auto_post_enabled


def test_broker_uuid_is_exact_and_this_reader_has_no_broker_writes():
    assert BID == str(UUID(BID))
    assert not hasattr(AlpacaPaperOrderReader, "submit")
    assert not hasattr(AlpacaPaperOrderReader, "cancel")
