"""Mock-only paper acknowledgement/fill reconciliation contract."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class MockEvent:
    sequence: int
    intent_id: str
    event_type: str
    quantity: Decimal = Decimal("0")


def reconcile_mock_events(events: tuple[MockEvent, ...]) -> dict[str, Any]:
    """Detect duplicate, missing, out-of-order and attribution errors."""
    discrepancies: list[str] = []
    seen_sequences: set[int] = set()
    seen_events: set[tuple[str, str, int]] = set()
    states: dict[str, str] = {}
    filled: dict[str, Decimal] = {}
    exited: dict[str, Decimal] = {}
    expected_sequence = 1
    allowed = {
        "ACK": {"CLAIMED", "SUBMITTED"}, "PARTIAL_FILL": {"ACKED", "PARTIAL"},
        "FILL": {"ACKED", "PARTIAL"}, "CANCEL": {"ACKED", "PARTIAL"},
        "REJECT": {"CLAIMED", "SUBMITTED", "ACKED"}, "EXIT": {"FILLED"},
    }
    for event in events:
        if event.sequence in seen_sequences:
            discrepancies.append("DUPLICATE_SEQUENCE")
        if event.sequence != expected_sequence:
            discrepancies.append("OUT_OF_ORDER_OR_MISSING_SEQUENCE")
        expected_sequence = max(expected_sequence, event.sequence + 1)
        seen_sequences.add(event.sequence)
        identity = (event.intent_id, event.event_type, event.sequence)
        if identity in seen_events:
            discrepancies.append("DUPLICATE_EVENT")
        seen_events.add(identity)
        if event.intent_id not in states:
            states[event.intent_id] = "CLAIMED"
            filled[event.intent_id] = Decimal("0")
            exited[event.intent_id] = Decimal("0")
        state = states[event.intent_id]
        if event.event_type not in allowed or state not in allowed.get(event.event_type, set()):
            discrepancies.append(f"INVALID_ORDER:{event.intent_id}:{event.event_type}")
            continue
        if event.quantity < 0:
            discrepancies.append("NEGATIVE_QUANTITY")
            continue
        if event.event_type in {"PARTIAL_FILL", "FILL"}:
            filled[event.intent_id] += event.quantity
            states[event.intent_id] = "FILLED" if event.event_type == "FILL" else "PARTIAL"
        elif event.event_type == "EXIT":
            exited[event.intent_id] += event.quantity
            if exited[event.intent_id] > filled[event.intent_id]:
                discrepancies.append("EXIT_EXCEEDS_FILL")
            states[event.intent_id] = "EXITED"
        elif event.event_type == "ACK":
            states[event.intent_id] = "ACKED"
        else:
            states[event.intent_id] = event.event_type
    return {
        "status": "RECONCILED" if not discrepancies else "DISCREPANCY",
        "broker_execution": "DISABLED",
        "discrepancies": sorted(set(discrepancies)),
        "positions": [{"intent_id": key, "filled": str(filled[key]), "exited": str(exited[key]),
                        "state": states[key]} for key in sorted(states)],
    }


def dormant_alpaca_read_proposal() -> dict[str, Any]:
    """Describe a future owner decision without performing or enabling it."""
    return {
        "status": "DORMANT_OWNER_PROPOSAL",
        "provider": "Alpaca PAPER",
        "purpose": "read-only account identity and portfolio mapping verification",
        "endpoints": ["GET /v2/account", "GET /v2/positions", "GET /v2/orders"],
        "request_cap": 3,
        "cost": "NO_PAID_CALLS",
        "credentials": "LOCAL_ONLY_NOT_READ",
        "account_ids": "NOT_LOGGED",
        "orders": "DISABLED",
        "approval_required": True,
        "execution_enabled": False,
    }
