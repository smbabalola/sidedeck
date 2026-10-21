"""eToro DEMO portfolio snapshot: strict parsing with Decimal arithmetic (read-only).

Parses the documented ``clientPortfolio`` response of
``GET /api/v1/trading/info/demo/pnl``. Nothing here places, changes or closes
orders, and nothing infers a value the broker did not report: a missing or
unconfirmed figure is returned as UNAVAILABLE with a reason, never estimated.

Cash (eToro "calculate available cash" guide), USD accounts only:
    credit - sum(ordersForOpen[].amount where mirrorID == 0) - sum(orders[].amount)
``bonusCredit`` and unrealised P&L are never treated as cash.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

ORDER_COLLECTIONS = ("orders", "ordersForOpen", "ordersForClose", "ordersForCloseMultiple",
                     "entryOrders", "exitOrders", "stockOrders")
REQUIRED_COLLECTIONS = ("positions", "mirrors") + ORDER_COLLECTIONS
MAX_SNAPSHOT_AGE = timedelta(minutes=5)
MAX_CLOCK_SKEW = timedelta(seconds=5)
ZERO = Decimal("0")
# eToro accountCurrencyId for USD, per two independently published eToro API
# schema references (owner decision 2026-10-20). The live response must match.
USD_ACCOUNT_CURRENCY_ID = 1

# Strict JSON types required before a baseline may be captured. "number" means a
# JSON int/float (never bool or a numeric string).
_PORTFOLIO_TYPES = {"credit": "number", "bonusCredit": "number", "accountCurrencyId": "int"}
_POSITION_TYPES = {"positionID": "int", "instrumentID": "int", "orderID": "int", "isBuy": "bool",
                   "units": "number", "amount": "number", "leverage": "int",
                   "openDateTime": "timestamp"}


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "bool":
        return type(value) is bool
    if expected == "int":
        return type(value) is int
    if expected == "number":
        return type(value) in (int, float)
    if expected == "timestamp":
        try:
            _utc(value, "timestamp")
        except EtoroDemoDataError:
            return False
        return True
    return False


def _json_type(value: Any) -> str:
    if value is None:
        return "missing/null"
    return {bool: "bool", int: "int", float: "number", str: "string", list: "list",
            dict: "object"}.get(type(value), type(value).__name__)


def field_type_issues(payload: Any) -> tuple[str, ...]:
    """Strict field-type check of a live response. Reports paths and types, never values."""
    portfolio = payload.get("clientPortfolio") if isinstance(payload, dict) else None
    if not isinstance(portfolio, dict):
        return ("clientPortfolio: expected object",)
    issues = []
    for name in REQUIRED_COLLECTIONS:
        if not isinstance(portfolio.get(name), list):
            issues.append(f"clientPortfolio.{name}: expected list, got "
                          f"{_json_type(portfolio.get(name))}")
    for key, expected in _PORTFOLIO_TYPES.items():
        if not _type_ok(portfolio.get(key), expected):
            issues.append(f"clientPortfolio.{key}: expected {expected}, got "
                          f"{_json_type(portfolio.get(key))}")
    raw_rows = portfolio.get("positions")
    rows: list[Any] = raw_rows if isinstance(raw_rows, list) else []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            issues.append(f"positions[{index}]: expected object, got {_json_type(row)}")
            continue
        for key, expected in _POSITION_TYPES.items():
            if not _type_ok(row.get(key), expected):
                issues.append(f"positions[{index}].{key}: expected {expected}, got "
                              f"{_json_type(row.get(key))}")
        pnl = row.get("unrealizedPnL")
        if not isinstance(pnl, dict) or not _type_ok(pnl.get("pnL"), "number"):
            issues.append(f"positions[{index}].unrealizedPnL.pnL: expected number")
    return tuple(issues)


class EtoroDemoDataError(ValueError):
    """The Demo portfolio response is malformed or inconsistent; nothing was recorded."""


def _decimal(value: Any, what: str) -> Decimal:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise EtoroDemoDataError(f"{what} is not numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise EtoroDemoDataError(f"{what} is not numeric") from exc
    if not result.is_finite():
        raise EtoroDemoDataError(f"{what} is not finite")
    return result


def _optional_decimal(container: Mapping[str, Any], key: str, what: str) -> Decimal | None:
    return None if container.get(key) is None else _decimal(container[key], what)


def _int(value: Any, what: str, *, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        raise EtoroDemoDataError(f"{what} is invalid")
    return value


def _utc(value: Any, what: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise EtoroDemoDataError(f"{what} missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EtoroDemoDataError(f"{what} invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EtoroDemoDataError(f"{what} must carry a timezone")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class DemoPosition:
    """One broker position; identity is ``position_id``, never the instrument."""

    position_id: int
    instrument_id: int
    order_id: int | None
    is_buy: bool
    units: Decimal
    amount: Decimal
    leverage: int
    opened_at: datetime
    unrealized_pnl: Decimal | None
    mirror_id: int = 0          # non-zero: a copy-trade/agent-portfolio child, never direct


@dataclass(frozen=True)
class PendingOrder:
    collection: str
    order_id: int | None
    amount: Decimal | None
    mirror_id: int | None


@dataclass(frozen=True)
class Figure:
    """A reported number, or ``None`` with the reason it is unavailable."""

    value: Decimal | None
    status: str          # AVAILABLE | UNAVAILABLE
    reason: str = ""


@dataclass(frozen=True)
class DemoPortfolioSnapshot:
    observed_at: datetime
    account_currency_id: int | None
    credit: Decimal | None
    bonus_credit: Decimal | None
    positions: tuple[DemoPosition, ...]
    pending_orders: tuple[PendingOrder, ...]
    mirror_count: int
    payload_sha256: str

    def require_fresh(self, now: datetime, max_age: timedelta = MAX_SNAPSHOT_AGE) -> None:
        if now.tzinfo is None:
            raise EtoroDemoDataError("reconciliation time must be timezone-aware")
        age = now.astimezone(timezone.utc) - self.observed_at
        if age < -MAX_CLOCK_SKEW:
            raise EtoroDemoDataError("Demo snapshot is future-dated")
        if age > max_age:
            raise EtoroDemoDataError("Demo snapshot is stale")

    def available_cash_usd(self) -> Figure:
        """Documented eToro formula; UNAVAILABLE unless every input is reported and valid.

        Only an account the response itself reports as ``accountCurrencyId == 1``
        (USD) gets a USD figure. Any other or missing ID: UNAVAILABLE, never converted.
        """
        if self.account_currency_id != USD_ACCOUNT_CURRENCY_ID:
            return Figure(None, "UNAVAILABLE", "account currency is not reported as USD (id 1)")
        if self.credit is None:
            return Figure(None, "UNAVAILABLE", "credit not reported")
        reserved = ZERO
        for order in self.pending_orders:
            if order.collection == "ordersForOpen":
                if order.mirror_id is None or order.amount is None:
                    return Figure(None, "UNAVAILABLE", "pending open order lacks amount or mirrorID")
                if order.mirror_id == 0:
                    reserved += order.amount
            elif order.collection == "orders":
                if order.amount is None:
                    return Figure(None, "UNAVAILABLE", "pending order lacks amount")
                reserved += order.amount
        return Figure(self.credit - reserved, "AVAILABLE")

    def unrealized_pnl(self, positions: tuple[DemoPosition, ...] | None = None) -> Figure:
        """Sum of reported direct-position P&L, as reported by eToro."""
        chosen = self.positions if positions is None else positions
        if self.mirror_count:
            return Figure(None, "UNAVAILABLE", "copy/mirror positions need mirror P&L components")
        if any(p.unrealized_pnl is None for p in chosen):
            return Figure(None, "UNAVAILABLE", "a position lacks reported unrealised P&L")
        return Figure(sum((p.unrealized_pnl or ZERO for p in chosen), ZERO), "AVAILABLE")


def _position(row: Any) -> DemoPosition:
    if not isinstance(row, dict):
        raise EtoroDemoDataError("position is not an object")
    if type(row.get("isBuy")) is not bool:
        raise EtoroDemoDataError("position direction is invalid")
    units = _decimal(row.get("units"), "position units")
    amount = _decimal(row.get("amount"), "position amount")
    if units <= 0 or amount <= 0:
        raise EtoroDemoDataError("position units and amount must be positive")
    pnl_block = row.get("unrealizedPnL")
    if pnl_block is not None and not isinstance(pnl_block, dict):
        raise EtoroDemoDataError("position unrealised P&L is malformed")
    pnl = None if pnl_block is None else _optional_decimal(pnl_block, "pnL", "position P&L")
    order_id = row.get("orderID")
    mirror = row.get("mirrorID")
    return DemoPosition(
        mirror_id=0 if mirror in (None, 0) else _int(mirror, "mirrorID"),
        position_id=_int(row.get("positionID"), "positionID"),
        instrument_id=_int(row.get("instrumentID"), "instrumentID"),
        order_id=None if order_id in (None, 0) else _int(order_id, "orderID"),
        is_buy=row["isBuy"], units=units, amount=amount,
        leverage=_int(row.get("leverage"), "leverage"),
        opened_at=_utc(row.get("openDateTime"), "position openDateTime"),
        unrealized_pnl=pnl)


def _pending(collection: str, row: Any) -> PendingOrder:
    if not isinstance(row, dict):
        raise EtoroDemoDataError("pending order is not an object")
    order_id = row.get("orderID")
    mirror = row.get("mirrorID")
    return PendingOrder(
        collection=collection,
        order_id=None if order_id is None else _int(order_id, "orderID"),
        amount=_optional_decimal(row, "amount", "pending order amount"),
        mirror_id=None if mirror is None else _int(mirror, "mirrorID", minimum=0))


def parse_demo_portfolio(payload: Any, *, observed_at: datetime) -> DemoPortfolioSnapshot:
    """Strictly parse one Demo ``/pnl`` response; malformed data fails closed."""
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise EtoroDemoDataError("observation time must be timezone-aware")
    portfolio = payload.get("clientPortfolio") if isinstance(payload, dict) else None
    if not isinstance(portfolio, dict):
        raise EtoroDemoDataError("clientPortfolio missing")
    for name in REQUIRED_COLLECTIONS:
        if not isinstance(portfolio.get(name), list):
            raise EtoroDemoDataError(f"clientPortfolio.{name} missing or not a list")
    positions = tuple(_position(row) for row in portfolio["positions"])
    ids = [p.position_id for p in positions]
    if len(ids) != len(set(ids)):
        raise EtoroDemoDataError("duplicate positionID in Demo portfolio")
    pending = tuple(_pending(name, row) for name in ORDER_COLLECTIONS for row in portfolio[name])
    currency = portfolio.get("accountCurrencyId")
    return DemoPortfolioSnapshot(
        observed_at=observed_at.astimezone(timezone.utc),
        account_currency_id=None if currency is None else _int(currency, "accountCurrencyId"),
        credit=_optional_decimal(portfolio, "credit", "credit"),
        bonus_credit=_optional_decimal(portfolio, "bonusCredit", "bonusCredit"),
        positions=positions, pending_orders=pending, mirror_count=len(portfolio["mirrors"]),
        payload_sha256=hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                                 default=str).encode("utf-8")).hexdigest())
