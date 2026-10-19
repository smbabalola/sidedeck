"""Account-scoped Saxo execution-history pagination and reconciliation.

Only injected responses are consumed here. Audit activity without execution
quantity/price is deliberately not converted into a fill.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol


class HistoryTransport(Protocol):
    def get(self, path: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class BrokerExecution:
    account_id: str
    order_id: str
    external_reference: str
    execution_id: str
    status: str
    quantity: Decimal
    price: Decimal
    fees: Decimal
    currency: str
    occurred_at: str


def _positive(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError(f"invalid {field}")
    return result


def _nonnegative(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}") from exc
    if not result.is_finite() or result < 0:
        raise ValueError(f"invalid {field}")
    return result


def fetch_history(
    transport: HistoryTransport,
    first_path: str,
    *,
    max_pages: int = 10,
) -> tuple[dict[str, Any], ...]:
    """Fetch a bounded complete collection; reject loops and malformed cursors."""
    if not first_path or max_pages < 1 or max_pages > 100:
        raise ValueError("invalid history pagination bounds")
    path = first_path
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for _ in range(max_pages):
        if path in seen:
            raise ValueError("history pagination loop")
        seen.add(path)
        response = transport.get(path)
        data = response.get("Data")
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise ValueError("malformed execution history page")
        rows.extend(data)
        next_path = response.get("__next")
        if not next_path:
            count = response.get("__count")
            if type(count) is int and count != len(rows):
                raise ValueError("execution history count is incomplete")
            return tuple(rows)
        if not isinstance(next_path, str) or not next_path.startswith("/"):
            raise ValueError("invalid execution history cursor")
        path = next_path
    raise ValueError("execution history pagination exceeded bound")

def parse_executions(
    rows: tuple[dict[str, Any], ...],
    *,
    account_id: str,
    order_id: str,
    external_reference: str,
) -> tuple[BrokerExecution, ...]:
    """Parse only fill-like rows and make execution identity durable."""
    if not account_id or not order_id or not external_reference:
        raise ValueError("execution identity is required")
    seen: set[str] = set()
    result: list[BrokerExecution] = []
    for row in rows:
        if row.get("AccountId") != account_id or row.get("OrderId") != order_id:
            raise ValueError("execution account or order mismatch")
        if row.get("ExternalReference") != external_reference:
            raise ValueError("execution external reference mismatch")
        status = row.get("Status")
        if status in {"Placed", "Working", "Cancelled", "Rejected"}:
            continue
        if status not in {"Fill", "FinalFill"}:
            raise ValueError("unknown execution status")
        execution_id = row.get("ExecutionId") or row.get("LogId")
        if not isinstance(execution_id, str) or not execution_id or execution_id in seen:
            raise ValueError("missing or duplicate execution identity")
        if row.get("Currency") != "EUR":
            raise ValueError("unexpected execution currency")
        occurred_at = row.get("ExecutionTime") or row.get("ActivityTime")
        if not isinstance(occurred_at, str) or not occurred_at:
            raise ValueError("execution timestamp missing")
        result.append(BrokerExecution(
            account_id=account_id, order_id=order_id,
            external_reference=external_reference, execution_id=execution_id,
            status=status, quantity=_positive(row.get("Amount"), "execution quantity"),
            price=_positive(row.get("ExecutionPrice"), "execution price"),
            fees=_nonnegative(row.get("Fees", "0"), "execution fees"),
            currency="EUR", occurred_at=occurred_at,
        ))
        seen.add(execution_id)
    return tuple(result)

