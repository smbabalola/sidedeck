"""Alpaca PAPER Trading API: read-only orders and legacy FILL activities.

Injected GET-only transport, fixed paper host in the existing transport, no
order submission or broker writes. Retrieved executions are *candidates* for
SideDeck journal reconciliation, not validated fee/correction/account postings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Mapping
from uuid import UUID

from .alpaca_paper import AlpacaPaperError, AlpacaPaperReadClient, PaperGetTransport
from .paper_desk import BROKER_KEY_SLOTS, PaperOrderDraft

_STATES = frozenset({
    "accepted", "accepted_for_bidding", "pending_new", "new", "partially_filled",
    "held", "pending_cancel", "pending_replace", "calculated", "done_for_day",
    "stopped", "suspended", "filled", "canceled", "expired", "rejected", "replaced",
})


def _number(value: object, field: str, *, zero: bool = False) -> Decimal:
    if value is None or isinstance(value, bool):
        raise AlpacaPaperError(f"invalid paper numeric field: {field}")
    try:
        num = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AlpacaPaperError(f"invalid paper numeric field: {field}") from exc
    if not num.is_finite() or num < 0 or (num == 0 and not zero):
        raise AlpacaPaperError(f"invalid paper numeric field: {field}")
    return num


def _timestamp(value: object, cutoff: datetime) -> datetime:
    if not isinstance(value, str):
        raise AlpacaPaperError("missing FILL timestamp")
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AlpacaPaperError("invalid FILL timestamp") from exc
    if at.tzinfo is None or at.utcoffset() is None:
        raise AlpacaPaperError("FILL timestamp is naive")
    at = at.astimezone(timezone.utc)
    if at > cutoff:
        raise AlpacaPaperError("FILL is newer than cutoff")
    return at


@dataclass(frozen=True)
class PaperOrderRead:
    order_id: str
    client_order_id: str
    status: str
    symbol: str
    side: Literal["buy", "sell"]
    qty: Decimal
    filled_qty: Decimal


@dataclass(frozen=True)
class PaperFillRead:
    activity_id: str
    order_id: str
    qty: Decimal
    price: Decimal
    cum_qty: Decimal
    executed_at: datetime
    fee_verified: Literal[False] = False


@dataclass(frozen=True)
class PaperOrderDiscrepancy:
    portfolio_id: str
    key_slot: str
    client_order_id: str
    paper_order_status: str
    paper_filled_qty: Decimal
    journal_filled_qty: Decimal
    missing_fill_activity_ids: tuple[str, ...]
    needs_review: bool
    # Never turn a legacy FILL activity into ledger money by guessing fees.
    auto_post_enabled: Literal[False] = False
    paper_trading_enabled: Literal[False] = False


def _order(raw: object, draft: PaperOrderDraft) -> PaperOrderRead:
    if not isinstance(raw, dict):
        raise AlpacaPaperError("paper order response must be object")
    try:
        uid = str(UUID(str(raw.get("id"))))
    except (TypeError, ValueError) as exc:
        raise AlpacaPaperError("paper order id must be UUID") from exc
    if raw.get("client_order_id") != draft.client_order_id:
        raise AlpacaPaperError("client order identity mismatch")
    if raw.get("symbol") != draft.symbol or raw.get("side") != draft.side:
        raise AlpacaPaperError("paper order symbol or side mismatch")
    if raw.get("type") != "limit" or raw.get("time_in_force") != "day":
        raise AlpacaPaperError("paper order execution type mismatch")
    if raw.get("order_class", "simple") not in ("simple", ""):
        raise AlpacaPaperError("unapproved contingent order")
    if raw.get("extended_hours", False) is not False:
        raise AlpacaPaperError("unapproved extended-hours paper order")
    qty = _number(raw.get("qty"), "qty")
    filled = _number(raw.get("filled_qty"), "filled_qty", zero=True)
    limit = _number(raw.get("limit_price"), "limit_price")
    if qty != draft.quantity or limit != draft.limit_price or filled > qty:
        raise AlpacaPaperError("paper order size or limit disagrees with SideDeck")
    state = raw.get("status")
    if not isinstance(state, str) or state not in _STATES:
        raise AlpacaPaperError("unrecognized paper order status")
    if state == "filled" and filled != qty:
        raise AlpacaPaperError("filled order lacks full quantity")
    return PaperOrderRead(uid, draft.client_order_id, state, draft.symbol, draft.side, qty, filled)


def _activity(row: Mapping[str, Any], order: PaperOrderRead, draft: PaperOrderDraft,
              cutoff: datetime) -> PaperFillRead:
    uid = row.get("id")
    if not isinstance(uid, str) or not (5 <= len(uid) <= 200):
        raise AlpacaPaperError("missing stable paper FILL activity ID")
    if row.get("activity_type") != "FILL" or row.get("type") not in ("fill", "partial_fill"):
        raise AlpacaPaperError("unexpected paper activity/correction")
    if (row.get("order_id") != order.order_id
        or row.get("symbol") != order.symbol or row.get("side") != order.side):
        raise AlpacaPaperError("FILL belongs to different paper order")
    qty = _number(row.get("qty"), "FILL qty")
    px = _number(row.get("price"), "FILL price")
    cum = _number(row.get("cum_qty"), "FILL cumulative")
    if ((order.side == "buy" and px > draft.limit_price)
        or (order.side == "sell" and px < draft.limit_price)):
        raise AlpacaPaperError("execution price violates SideDeck limit")
    at = _timestamp(row.get("transaction_time"), cutoff)
    if at < draft.created_at.astimezone(timezone.utc):
        raise AlpacaPaperError("execution predates SideDeck decision")
    return PaperFillRead(uid, order.order_id, qty, px, cum, at)


class AlpacaPaperOrderReader:
    """Injected HTTP GET-only order+FILL lookup; paging is fail-closed."""

    def __init__(self, transport: PaperGetTransport, *, key_slot: str,
                 max_pages: int = 3) -> None:
        if key_slot not in BROKER_KEY_SLOTS.values():
            raise AlpacaPaperError("unapproved paper key slot")
        if not 1 <= max_pages <= 5:
            raise ValueError("paper activity page limit must be 1..5")
        self._client = AlpacaPaperReadClient(transport)
        self._slot = key_slot
        self._max_pages = max_pages

    def fetch(self, draft: PaperOrderDraft, *, observed_at: datetime
              ) -> tuple[PaperOrderRead, tuple[PaperFillRead, ...]]:
        if draft.portfolio_id not in BROKER_KEY_SLOTS or (
            BROKER_KEY_SLOTS[draft.portfolio_id] != self._slot
            or draft.key_slot != self._slot
        ):
            raise AlpacaPaperError("paper key slot does not own strategy")
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise AlpacaPaperError("paper observation timestamp must be aware")
        cutoff = observed_at.astimezone(timezone.utc)
        order = _order(self._client._get(
            "/v2/orders:by_client_order_id", {"client_order_id": draft.client_order_id},
        ), draft)
        found: list[PaperFillRead] = []
        by_id: dict[str, PaperFillRead] = {}
        token: str | None = None
        for i in range(self._max_pages):
            args = {
                "order_id": order.order_id, "direction": "asc", "page_size": "100",
            }
            if token:
                args["page_token"] = token
            payload = self._client._get("/v2/account/activities/FILL", args)
            if not isinstance(payload, list) or len(payload) > 100 or any(
                not isinstance(row, dict) for row in payload
            ):
                raise AlpacaPaperError("invalid bounded paper FILL page")
            for row in payload:
                activity = _activity(row, order, draft, cutoff)
                prior = by_id.get(activity.activity_id)
                if prior is not None:
                    if prior != activity:
                        raise AlpacaPaperError("conflicting paper FILL activity id")
                    continue
                by_id[activity.activity_id] = activity
                found.append(activity)
            if len(payload) < 100:
                break
            if i == self._max_pages - 1:
                raise AlpacaPaperError("paper FILL pagination incomplete")
            page_id = payload[-1].get("id")
            if not isinstance(page_id, str) or page_id == token:
                raise AlpacaPaperError("invalid paper FILL cursor")
            token = page_id
        ordered = sorted(found, key=lambda value: (value.executed_at, value.activity_id))
        total = Decimal("0")
        for activity in ordered:
            total += activity.qty
            if activity.cum_qty != total:
                raise AlpacaPaperError("FILL cumulative quantity gap or correction")
        if total != order.filled_qty:
            raise AlpacaPaperError("broker order FILL total differs from activities")
        return order, tuple(ordered)


def compare_paper_order(
    draft: PaperOrderDraft, broker_order: PaperOrderRead,
    fills: tuple[PaperFillRead, ...], journal_orders: list[dict[str, str]],
) -> PaperOrderDiscrepancy:
    """Calculate discrepancy, never mutate ledger or fabricate commission."""
    rows = [row for row in journal_orders if row.get("client_order_id") == draft.client_order_id]
    if len(rows) != 1:
        raise AlpacaPaperError("SideDeck persisted order not uniquely found")
    if broker_order.client_order_id != draft.client_order_id:
        raise AlpacaPaperError("order mismatch")
    stored = _number(rows[0].get("filled_quantity"), "journal qty", zero=True)
    if stored > broker_order.filled_qty:
        raise AlpacaPaperError("journal records more shares than paper broker")
    differing = stored != broker_order.filled_qty
    return PaperOrderDiscrepancy(
        portfolio_id=draft.portfolio_id,
        key_slot=draft.key_slot,
        client_order_id=draft.client_order_id,
        paper_order_status=broker_order.status,
        paper_filled_qty=broker_order.filled_qty,
        journal_filled_qty=stored,
        missing_fill_activity_ids=(
            tuple(activity.activity_id for activity in fills) if differing else ()
        ),
        needs_review=differing or broker_order.status in {"canceled", "rejected", "expired", "replaced"},
    )
