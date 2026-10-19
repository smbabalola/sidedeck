"""Account-scoped Saxo execution-history pagination and reconciliation.

Only injected responses are consumed here. Audit activity without execution
quantity/price is deliberately not converted into a fill.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from urllib.parse import parse_qs, quote, urlsplit

from sidedeck.infrastructure.saxo_account_scope import SaxoAccountScope
from sidedeck.infrastructure.saxo_sim import SaxoSimClient


class HistoryTransport(Protocol):
    def get(self, path: str) -> dict[str, Any]: ...


def order_history_path(scope: SaxoAccountScope, order_id: str) -> str:
    if not order_id or len(order_id) > 128 or any(ch.isspace() for ch in order_id):
        raise ValueError("invalid Saxo order ID")
    return ("/cs/v1/audit/orderactivities?AccountKey=" + quote(scope.account_key, safe="")
            + "&ClientKey=" + quote(scope.client_key, safe="")
            + "&EntryType=All&IncludeSubAccounts=false&%24top=100&OrderId="
            + quote(order_id, safe=""))


class _SaxoHistoryTransport:
    def __init__(self, client: SaxoSimClient) -> None:
        self.client = client

    def get(self, path: str) -> dict[str, Any]:
        return self.client.get(path)


def read_order_history(client: SaxoSimClient, scope: SaxoAccountScope,
                       order_id: str) -> tuple[dict[str, Any], ...]:
    """One account-scoped GET chain; no retry or fallback provider."""
    return fetch_history(_SaxoHistoryTransport(client), order_history_path(scope, order_id),
                         continuation_validator=lambda path: validate_continuation(path, scope, order_id))


def validate_continuation(path: str, scope: SaxoAccountScope, order_id: str) -> str:
    """Ensure broker cursors cannot escape the original account/order query."""
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.fragment or parsed.path != "/cs/v1/audit/orderactivities":
        raise ValueError("invalid execution history cursor boundary")
    query = parse_qs(parsed.query, keep_blank_values=True)
    expected = {
        "AccountKey": [scope.account_key], "ClientKey": [scope.client_key],
        "EntryType": ["All"], "IncludeSubAccounts": ["false"],
        "$top": ["100"], "OrderId": [order_id],
    }
    if set(query) - set(expected) - {"$skip"} or any(query.get(key) != value for key, value in expected.items()):
        raise ValueError("execution history cursor changed account or order scope")
    if "$skip" in query and (len(query["$skip"]) != 1 or not query["$skip"][0].isdigit()):
        raise ValueError("invalid execution history pagination cursor")
    return path


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
    instrument_currency: str
    account_currency: str
    price_currency: str
    fees_currency: str
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
    continuation_validator: Any | None = None,
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
        if continuation_validator is not None:
            continuation_validator(next_path)
        path = next_path
    raise ValueError("execution history pagination exceeded bound")

def parse_executions(
    rows: tuple[dict[str, Any], ...],
    *,
    account_id: str,
    order_id: str,
    external_reference: str,
    instrument_currency: str,
    account_currency: str,
    price_currency: str,
    fees_currency: str,
    authorized_quantity: Decimal,
) -> tuple[BrokerExecution, ...]:
    """Parse only fill-like rows and make execution identity durable."""
    if not account_id or not order_id or not external_reference:
        raise ValueError("execution identity is required")
    if not authorized_quantity.is_finite() or authorized_quantity <= 0:
        raise ValueError("authorized execution quantity is invalid")
    for currency in (instrument_currency, account_currency, price_currency, fees_currency):
        if not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha():
            raise ValueError("execution currency metadata is invalid")
    if price_currency != instrument_currency:
        raise ValueError("execution price currency is not instrument currency")
    seen: set[str] = set()
    result: list[BrokerExecution] = []
    cumulative = Decimal("0")
    final_seen = False
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
        if status == "FinalFill" and final_seen:
            raise ValueError("multiple final fill records")
        execution_id = row.get("ExecutionId") or row.get("LogId")
        if not isinstance(execution_id, str) or not execution_id or execution_id in seen:
            raise ValueError("missing or duplicate execution identity")
        occurred_at = row.get("ExecutionTime") or row.get("ActivityTime")
        if not isinstance(occurred_at, str) or not occurred_at:
            raise ValueError("execution timestamp missing")
        quantity = _positive(row.get("FillAmount"), "execution fill quantity")
        cumulative += quantity
        if cumulative > authorized_quantity:
            raise ValueError("execution quantity exceeds authorized order quantity")
        if status == "FinalFill" and cumulative != authorized_quantity:
            raise ValueError("final fill does not reconcile to authorized order quantity")
        result.append(BrokerExecution(
            account_id=account_id, order_id=order_id,
            external_reference=external_reference, execution_id=execution_id,
            status=status, quantity=quantity,
            price=_positive(row.get("ExecutionPrice"), "execution price"),
            fees=_nonnegative(row.get("Fees"), "execution fees"),
            instrument_currency=instrument_currency, account_currency=account_currency,
            price_currency=price_currency, fees_currency=fees_currency,
            occurred_at=occurred_at,
        ))
        seen.add(execution_id)
        final_seen = final_seen or status == "FinalFill"
    return tuple(result)

