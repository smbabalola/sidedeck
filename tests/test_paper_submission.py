"""SideDeck PAPER submission protocol: simulated fixture only, no network."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from uuid import uuid4

import pytest

from sidedeck.domain.contracts import MarketSnapshot, PriceType, Session, Side, TradeIntent
from sidedeck.domain.paper_desk import PaperDeskError
from sidedeck.domain.paper_outbox import DurablePaperDesk
from sidedeck.domain.paper_submission import SideDeckPaperSubmission

NOW = datetime(2026, 10, 18, 15, tzinfo=timezone.utc)


def new_draft(db, portfolio="tradingagents"):
    mark = MarketSnapshot(
        instrument_id="US:AAPL", ticker="AAPL", provider="OFFLINE_FIXTURE",
        price_type=PriceType.EOD_CLOSE, price=Decimal("100"),
        market_timestamp=NOW, ingestion_timestamp=NOW, session=Session.CLOSED,
        quality="FIXTURE_NOT_LIVE",
    )
    intent = TradeIntent(
        experiment_id="submission-fixture", portfolio_id=portfolio,
        strategy_id="fixture", instrument_id="US:AAPL", side=Side.BUY,
        quantity=Decimal("1"), rationale="fixture",
        model_revision="offline-stub", decision_timestamp=NOW,
        data_as_of=NOW, stop_price=Decimal("95"),
        invalidation="synthetic stop",
    )
    return db.prepare(intent, mark, marks={"US:AAPL": mark})


class PaperReader:
    def __init__(self, paper_id, *, active=True, blocked=False, order=None):
        self.paper_id = paper_id
        self.active = active
        self.blocked = blocked
        self.order = order
        self.calls = []
    def get(self, path, params):
        self.calls.append((path, dict(params)))
        if path == "/v2/account":
            return 200, json.dumps({
                "id": self.paper_id, "status": "ACTIVE" if self.active else "SUSPENDED",
                "cash": "100000", "equity": "100000", "buying_power": "100000",
                "multiplier": "1", "account_blocked": self.blocked,
                "trading_blocked": False,
            }).encode()
        if path == "/v2/orders:by_client_order_id":
            return 200, json.dumps(self.order).encode()
        raise AssertionError("unapproved route")


def order_ack(d):
    return {
        "id": str(uuid4()), "client_order_id": d.client_order_id,
        "symbol": d.symbol, "side": d.side, "qty": str(d.quantity),
        "filled_qty": "0", "type": "limit", "time_in_force": "day",
        "limit_price": str(d.limit_price), "status": "new",
        "order_class": "simple", "extended_hours": False,
    }


class SimulatedWriter:
    fixture_only = True
    def __init__(self, response):
        self.response = response
        self.posts = []
    def post(self, path, payload):
        self.posts.append((path, payload))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def setup(tmp_path):
    db = DurablePaperDesk(tmp_path / "paper.sqlite3")
    db.initialize(opened_at=NOW - timedelta(minutes=1))
    d = new_draft(db)
    a, b = PaperReader("PAPER-ONE"), PaperReader("PAPER-TWO")
    return db, d, a, b, SideDeckPaperSubmission(db, a, b)


def test_ready_preview_does_not_send_or_disengage_kill_switch(tmp_path):
    db, draft, a, b, workflow = setup(tmp_path)
    plan = workflow.preview(draft.client_order_id, key_slot=draft.key_slot, now=NOW)
    assert plan.status == "READY_FOR_OFFLINE_FIXTURE"
    assert plan.preview == draft.alpaca_preview()
    assert plan.broker_write_enabled is False
    assert plan.accounts_distinct
    assert a.calls == b.calls == [("/v2/account", {})]
    assert db.kill_switch_engaged
    assert db.paper_submission_status(draft.client_order_id) == "NOT_SENT"


def test_fixture_dispatch_happens_once_and_ack_persists_after_restart(tmp_path):
    db, draft, a, b, workflow = setup(tmp_path)
    ack = order_ack(draft)
    writer = SimulatedWriter((201, ack))
    result = workflow.submit_fixture_once(
        draft.client_order_id, key_slot=draft.key_slot, now=NOW, writer=writer,
    )
    assert result.outcome == "FIXTURE_ACKNOWLEDGED"
    assert result.real_paper_orders == result.network_requests == 0
    assert len(writer.posts) == 1
    assert writer.posts[0][0] == "/v2/orders"
    assert writer.posts[0][1]["client_order_id"] == draft.client_order_id
    restarted = DurablePaperDesk(db.path)
    assert restarted.paper_submission_status(draft.client_order_id) == "ACKNOWLEDGED"
    assert restarted.order_binding(draft.client_order_id)[1] == ack["id"]
    assert restarted.snapshot()["strategies"]["tradingagents"]["cash"] == "1000"
    assert restarted.snapshot()["strategies"]["ai-trading"]["cash"] == "1000"
    with pytest.raises(PaperDeskError):
        workflow.submit_fixture_once(
            draft.client_order_id, key_slot=draft.key_slot, now=NOW,
            writer=writer,
        )
    assert len(writer.posts) == 1


def test_timeout_stays_uncertain_preventing_duplicate_submission(tmp_path):
    db, draft, a, b, workflow = setup(tmp_path)
    writer = SimulatedWriter(TimeoutError("unknown delivery"))
    result = workflow.submit_fixture_once(
        draft.client_order_id, key_slot=draft.key_slot, now=NOW, writer=writer,
    )
    assert result.outcome == "UNCERTAIN_CHECK_PAPER_GET"
    assert DurablePaperDesk(db.path).paper_submission_status(draft.client_order_id) == "UNCERTAIN"
    with pytest.raises(PaperDeskError, match="already attempted"):
        workflow.submit_fixture_once(
            draft.client_order_id, key_slot=draft.key_slot, now=NOW,
            writer=writer,
        )
    assert len(writer.posts) == 1
    assert db.kill_switch_engaged


def test_invalid_ack_leaves_uncertain_not_resubmitted(tmp_path):
    db, draft, a, b, workflow = setup(tmp_path)
    bad = {**order_ack(draft), "symbol": "BTCUSD"}
    writer = SimulatedWriter((201, bad))
    result = workflow.submit_fixture_once(
        draft.client_order_id, key_slot=draft.key_slot, now=NOW, writer=writer,
    )
    assert result.outcome == "UNCERTAIN_CHECK_PAPER_GET"
    assert db.paper_submission_status(draft.client_order_id) == "UNCERTAIN"
    assert len(writer.posts) == 1


def test_uncertain_recovery_uses_get_not_repeat_post(tmp_path):
    db, draft, a, b, workflow = setup(tmp_path)
    writer = SimulatedWriter(TimeoutError("unknown"))
    workflow.submit_fixture_once(draft.client_order_id, key_slot=draft.key_slot, now=NOW, writer=writer)
    recovery = PaperReader("PAPER-ONE", order=order_ack(draft))
    result = workflow.reconcile_uncertain_fixture(
        draft.client_order_id, key_slot=draft.key_slot, now=NOW, paper_reader=recovery,
    )
    assert result.outcome == "FIXTURE_ACKNOWLEDGED"
    assert recovery.calls == [
        ("/v2/orders:by_client_order_id", {"client_order_id": draft.client_order_id}),
    ]
    assert len(writer.posts) == 1
    assert db.paper_submission_status(draft.client_order_id) == "ACKNOWLEDGED"


@pytest.mark.parametrize("change", [
    {"key_slot": "ALPACA_API_KEY2"},
    {"now": NOW + timedelta(minutes=2)},
    {"now": NOW - timedelta(seconds=1)},
])
def test_wrong_slot_or_stale_quote_prevents_dispatch(tmp_path, change):
    db, draft, a, b, workflow = setup(tmp_path)
    writer = SimulatedWriter((201, order_ack(draft)))
    with pytest.raises(PaperDeskError):
        workflow.submit_fixture_once(
            draft.client_order_id,
            key_slot=change.get("key_slot", draft.key_slot),
            now=change.get("now", NOW),
            writer=writer,
        )
    assert writer.posts == []
    assert db.paper_submission_status(draft.client_order_id) == "NOT_SENT"


def test_same_account_or_blocked_account_fails_before_post(tmp_path):
    db, draft, a, b, workflow = setup(tmp_path)
    b.paper_id = a.paper_id
    writer = SimulatedWriter((201, order_ack(draft)))
    with pytest.raises(PaperDeskError, match="distinct"):
        workflow.submit_fixture_once(
            draft.client_order_id, key_slot=draft.key_slot, now=NOW, writer=writer,
        )
    assert writer.posts == []
    b.paper_id = "SECOND"
    b.blocked = True
    with pytest.raises(PaperDeskError):
        workflow.submit_fixture_once(
            draft.client_order_id, key_slot=draft.key_slot, now=NOW, writer=writer,
        )
    assert writer.posts == []


def test_non_fixture_writer_never_dispatches(tmp_path):
    db, draft, a, b, workflow = setup(tmp_path)
    class NonFixture:
        fixture_only = False
        def post(self, path, payload):
            raise AssertionError("must never be reached")
    with pytest.raises(PaperDeskError, match="disabled"):
        workflow.submit_fixture_once(
            draft.client_order_id, key_slot=draft.key_slot, now=NOW,
            writer=NonFixture(),  # type: ignore[arg-type]
        )
    assert a.calls == b.calls == []
    assert db.paper_submission_status(draft.client_order_id) == "NOT_SENT"


def test_fixture_ack_accepts_documented_alpaca_http_200(tmp_path):
    db, draft, _, _, workflow = setup(tmp_path)
    writer = SimulatedWriter((200, order_ack(draft)))
    result = workflow.submit_fixture_once(
        draft.client_order_id, key_slot=draft.key_slot, now=NOW, writer=writer,
    )
    assert result.outcome == "FIXTURE_ACKNOWLEDGED"
    assert len(writer.posts) == 1
    assert db.paper_submission_status(draft.client_order_id) == "ACKNOWLEDGED"
