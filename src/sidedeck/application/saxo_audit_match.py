"""Conservative Saxo audit-to-order evidence matching. No trading endpoints.

Order activities are not necessarily fill records. Only acknowledge a
locally SUBMITTING/UNKNOWN order after independent matching broker evidence.
Do not derive FILLED from an audit event until execution quantities exist.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sidedeck.application.saxo_order_lifecycle import (
    LifecycleConflict, advance_lifecycle, lifecycle_state,
)


@dataclass(frozen=True)
class MatchedOrder:
    external_reference: str
    broker_order_id: str
    evidence_status: str


def match_order_activity(
    activity: dict[str, Any], *, account_id: str, external_reference: str,
) -> MatchedOrder | None:
    """Only uniquely identified activity; unspecified account or ID fails closed."""
    if not account_id or not external_reference:
        raise ValueError("explicit account and reference required")
    if activity.get("AccountId") != account_id:
        return None
    if activity.get("ExternalReference") != external_reference:
        return None
    order_id = activity.get("OrderId")
    if not isinstance(order_id, str) or not order_id or len(order_id) > 128:
        return None
    return MatchedOrder(external_reference, order_id, "ORDER_ACTIVITY_ONLY")


def match_unique_activity(
    response: dict[str, Any], *, account_id: str, external_reference: str,
) -> MatchedOrder | None:
    records = response.get("Data")
    if not isinstance(records, list) or response.get("__next"):
        raise ValueError("audit evidence incomplete")
    count = response.get("__count")
    if type(count) is int and count > len(records):
        raise ValueError("audit evidence truncated")
    matches = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("audit record malformed")
        found = match_order_activity(
            record, account_id=account_id, external_reference=external_reference,
        )
        if found is not None:
            matches.append(found)
    if len(matches) > 1:
        raise ValueError("ambiguous audit references")
    return matches[0] if matches else None


def note_broker_order_reference(
    journal_path: str, *, order_key: str, match: MatchedOrder,
) -> bool:
    """Attach account-scoped broker order ID, never falsely claim a fill."""
    if match.external_reference != order_key or match.evidence_status != "ORDER_ACTIVITY_ONLY":
        raise ValueError("broker order evidence identity mismatch")
    state = lifecycle_state(journal_path, order_key)
    if state is None:
        raise LifecycleConflict("unregistered order")
    if state[0] not in ("SUBMITTING", "UNKNOWN"):
        raise LifecycleConflict("order not awaiting broker evidence")
    advance_lifecycle(
        journal_path, order_key, "ACKNOWLEDGED",
        broker_order_id=match.broker_order_id, broker_evidence=True,
    )
    return True
