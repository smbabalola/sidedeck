"""Validate actual Saxo OrderActivities fill fields without making an order.

Order audit can contain Placed, Fill and FinalFill activities; a complete
account-scoped EntryType=All history is required before fill reconciliation.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True)
class FillEvidence:
    account_id: str
    order_id: str
    external_reference: str
    uic: int
    amount: Decimal
    price: Decimal
    activity_time: str
    status: str


def _positive_decimal(value: Any) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError("missing fill numeric field")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("invalid fill numeric field") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError("nonpositive fill numeric field")
    return result


def extract_sofi_fills(data: dict[str, Any], *, account_id: str,
                       external_reference: str, order_id: str) -> tuple[FillEvidence, ...]:
    """Reject incomplete, ambiguous, cross-account or unverified fill data."""
    if not all(isinstance(x, str) and x for x in (account_id, external_reference, order_id)):
        raise ValueError("missing expected broker identity")
    records = data.get("Data")
    if not isinstance(records, list) or data.get("__next"):
        raise ValueError("incomplete order audit history")
    count = data.get("__count")
    if type(count) is int and count > len(records):
        raise ValueError("order audit history truncated")
    fills = []
    seen_log_ids: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("invalid order activity")
        if record.get("OrderId") != order_id:
            raise ValueError("unexpected order in scoped history")
        if record.get("AccountId") != account_id or record.get("ExternalReference") != external_reference:
            raise ValueError("account or external reference mismatch")
        if record.get("Uic") != 23241352 or record.get("AssetType") != "Stock":
            raise ValueError("not the intended SOFI stock")
        if record.get("BuySell") != "Buy":
            raise ValueError("unexpected order direction")
        status = record.get("Status")
        if status not in ("Fill", "FinalFill", "Placed", "Working", "Cancelled", "Rejected"):
            raise ValueError("unrecognized Saxo order status")
        if status not in ("Fill", "FinalFill"):
            continue
        log_id = record.get("LogId")
        if not isinstance(log_id, str) or not log_id or log_id in seen_log_ids:
            raise ValueError("missing or duplicate fill log ID")
        seen_log_ids.add(log_id)
        time = record.get("ActivityTime")
        if not isinstance(time, str) or not time:
            raise ValueError("fill timestamp missing")
        fills.append(FillEvidence(
            account_id, order_id, external_reference, 23241352,
            _positive_decimal(record.get("FillAmount")),
            _positive_decimal(record.get("ExecutionPrice")), time, status,
        ))
    if sum((item.amount for item in fills), Decimal("0")) > Decimal("1"):
        raise ValueError("fill exceeds intended one-share order")
    if sum(item.status == "FinalFill" for item in fills) > 1:
        raise ValueError("multiple final fills")
    return tuple(fills)
