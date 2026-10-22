"""eToro DEMO order contract, strict response parsing and verified lineage (offline).

Sourced from the public eToro API reference (reviewed 2026-10-21; see
``docs/SD036_ETORO_DEMO_CONTRACT_REVIEW.md``):

* open:   ``POST /api/v2/trading/execution/demo/orders`` (200 = accepted, not executed;
  ``x-request-id`` is the idempotency key and is echoed as ``referenceId``);
* lookup: ``GET /api/v2/trading/info/demo/orders:lookup?referenceId=...|orderId=...``
  (``status.id`` and ``positionExecutions[].positionId`` with ``openingData.orderId``);
* close:  ``POST /api/v1/trading/execution/demo/market-close-orders/positions/{positionId}``;
* close outcome: ``GET /api/v1/trading/info/demo/close-orders/{orderId}``.

This module builds request *bodies* and parses *responses*. It has no HTTP
client and sends nothing. eToro Real execution is permanently excluded: any
path that is not one of the Demo templates below is refused.

Ownership rule: a position belongs to SideDeck only when an order SideDeck
submitted (known ``referenceId``) is reported by the lookup as having opened
that exact ``positionId`` (``openingData.orderId`` equals the order). Ticker or
instrument matching is never evidence of ownership.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

ETORO_REAL_EXECUTION = "PERMANENTLY_EXCLUDED"

DEMO_PNL_PATH = "/api/v1/trading/info/demo/pnl"
DEMO_OPEN_PATH = "/api/v2/trading/execution/demo/orders"
DEMO_ORDER_LOOKUP_PATH = "/api/v2/trading/info/demo/orders:lookup"
DEMO_CLOSE_PATH = "/api/v1/trading/execution/demo/market-close-orders/positions/{position_id}"
DEMO_CLOSE_INFO_PATH = "/api/v1/trading/info/demo/close-orders/{order_id}"

# (method, regex) pairs; the only shapes SideDeck may ever address.
_DEMO_ROUTES = (
    ("GET", re.compile(r"^/api/v1/trading/info/demo/pnl$")),
    ("POST", re.compile(r"^/api/v2/trading/execution/demo/orders$")),
    ("GET", re.compile(r"^/api/v2/trading/info/demo/orders:lookup$")),
    ("POST", re.compile(r"^/api/v1/trading/execution/demo/market-close-orders/positions/[1-9][0-9]{0,18}$")),
    ("GET", re.compile(r"^/api/v1/trading/info/demo/close-orders/[1-9][0-9]{0,18}$")),
)

# status.id (v2 lookup) and statusID (v1 close info) share these numbers.
ORDER_STATUS = {1: "RECEIVED", 2: "PLACED", 3: "FILLED", 4: "REJECTED", 5: "PARTIALLY_FILLED",
                6: "PENDING_CANCEL", 7: "CANCELED", 8: "EXPIRED", 9: "CANCELED_PARTIALLY_FILLED",
                10: "REJECTED_PARTIALLY_FILLED", 11: "WAITING_FOR_MARKET",
                12: "PENDING_TRIGGERED_RATE"}
TERMINAL_STATUSES = frozenset({3, 4, 7, 8, 9, 10})
NO_FILL_TERMINAL = frozenset({4, 7, 8})
ZERO = Decimal("0")


class EtoroDemoOrderError(ValueError):
    """An order request, response or lineage check failed; nothing is trusted."""


class RealExecutionExcluded(PermissionError):
    """eToro Real (or any non-allowlisted) endpoint; permanently refused."""


# Documented field shapes (SD-043). "number" = JSON int/float, never bool or string.
_OPEN_ACCEPT_SPEC: dict[str, Any] = {"orderId": "int", "referenceId": "str"}
_LOOKUP_SPEC: dict[str, Any] = {
    "orderId": "int", "action": "str", "transaction": "str",
    "status": {"id": "int", "errorCode": "int"},
    "asset": {"instrumentId": "int", "leverage": "int", "side": "str"},
    "positionExecutions": [{"positionId": "int", "state": "str", "remainingUnits": "number",
                            "openingData": {"orderId": "int", "units": "number",
                                            "avgPrice": "number", "fees": "number"}}]}
_CLOSE_ACCEPT_SPEC: dict[str, Any] = {"orderForClose": {"positionID": "int", "instrumentID": "int",
                                                        "orderID": "int"}}
_CLOSE_INFO_SPEC: dict[str, Any] = {"orderID": "int", "statusID": "int",
                                    "positions": [{"positionID": "int", "units": "number"}]}
RESPONSE_SPECS = {"open_acceptance": _OPEN_ACCEPT_SPEC, "order_lookup": _LOOKUP_SPEC,
                  "close_acceptance": _CLOSE_ACCEPT_SPEC, "close_info": _CLOSE_INFO_SPEC}


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    return {bool: "bool", int: "int", float: "float", str: "str", list: "list",
            dict: "object"}.get(type(value), "other")


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "number":
        return type(value) in (int, float)
    return _kind(value) == expected


def _walk(value: Any, spec: Any, path: str, issues: list[str]) -> None:
    if isinstance(spec, dict):
        if not isinstance(value, dict):
            issues.append(f"{path or '$'}: expected object, got {_kind(value)}")
            return
        for key, child in spec.items():
            child_path = f"{path}.{key}" if path else key
            if key not in value:
                variant = next((k for k in value if k.lower() == key.lower()), None)
                issues.append(f"{child_path}: missing" + (" (casing differs)" if variant else ""))
                continue
            _walk(value[key], child, child_path, issues)
    elif isinstance(spec, list):
        if not isinstance(value, list):
            issues.append(f"{path}: expected list, got {_kind(value)}")
            return
        for index, item in enumerate(value):
            _walk(item, spec[0], f"{path}[{index}]", issues)
    elif not _type_matches(value, spec):
        issues.append(f"{path}: expected {spec}, got {_kind(value)}")


def response_shape_issues(kind: str, payload: Any) -> tuple[str, ...]:
    """Sanitized live-schema diagnostics: field paths and JSON types only, never values."""
    issues: list[str] = []
    _walk(payload, RESPONSE_SPECS[kind], "", issues)
    return tuple(issues)


def require_demo_route(method: str, path: str) -> None:
    """Refuse every route except the documented Demo allowlist (checked pre-network)."""
    if "/demo/" not in path:
        raise RealExecutionExcluded("eToro Real endpoints are permanently excluded from SideDeck")
    if not any(method == m and pattern.fullmatch(path) for m, pattern in _DEMO_ROUTES):
        raise RealExecutionExcluded("eToro endpoint is not on the SideDeck Demo allowlist")


def _uuid(value: Any, what: str) -> str:
    try:
        parsed = uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise EtoroDemoOrderError(f"{what} must be a UUID") from None
    if str(parsed) != str(value).lower():
        raise EtoroDemoOrderError(f"{what} must be a canonical UUID")
    return str(parsed)


def _int(value: Any, what: str, *, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        raise EtoroDemoOrderError(f"{what} is invalid")
    return value


def _dec(value: Any, what: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise EtoroDemoOrderError(f"{what} is not numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise EtoroDemoOrderError(f"{what} is not numeric") from None
    if not result.is_finite():
        raise EtoroDemoOrderError(f"{what} is not finite")
    return result


def _json_number(value: Decimal, what: str) -> float:
    """Exact Decimal -> JSON number; refuses any value a float would alter."""
    as_float = float(value)
    if Decimal(repr(as_float)) != value:
        raise EtoroDemoOrderError(f"{what} cannot be represented exactly")
    return as_float


@dataclass(frozen=True)
class DemoOpenRequest:
    """One long, unleveraged, price-protected open (limitIOC by units, USD only)."""

    reference_id: str          # sent as x-request-id; never reused for another order
    instrument_id: int
    units: Decimal
    limit_rate: Decimal

    def __post_init__(self) -> None:
        _uuid(self.reference_id, "reference_id")
        _int(self.instrument_id, "instrument_id")
        for name in ("units", "limit_rate"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise EtoroDemoOrderError(f"{name} must be a positive finite Decimal")

    @property
    def max_notional_usd(self) -> Decimal:
        return self.units * self.limit_rate

    def body(self) -> dict[str, Any]:
        """The documented v2 Demo body. Leverage 1, buy only, no shorts or SL/TP."""
        return {"action": "open", "transaction": "buy", "instrumentId": self.instrument_id,
                "orderType": "limitIOC", "limitRate": _json_number(self.limit_rate, "limit_rate"),
                "units": _json_number(self.units, "units"), "leverage": 1,
                "orderCurrency": "usd"}


@dataclass(frozen=True)
class DemoCloseRequest:
    reference_id: str
    position_id: int
    instrument_id: int
    units_to_deduct: Decimal | None = None   # None = full close

    def __post_init__(self) -> None:
        _uuid(self.reference_id, "reference_id")
        _int(self.position_id, "position_id")
        _int(self.instrument_id, "instrument_id")
        units = self.units_to_deduct
        if units is not None and (not units.is_finite() or units <= 0):
            raise EtoroDemoOrderError("units_to_deduct must be positive when given")

    @property
    def path(self) -> str:
        return DEMO_CLOSE_PATH.format(position_id=self.position_id)

    def body(self) -> dict[str, Any]:
        units = self.units_to_deduct
        return {"InstrumentID": self.instrument_id,
                "UnitsToDeduct": None if units is None else _json_number(units, "units_to_deduct")}


@dataclass(frozen=True)
class OpenAcceptance:
    order_id: int
    reference_id: str


def parse_open_acceptance(payload: Any, *, reference_id: str) -> OpenAcceptance:
    """200 from the open endpoint: accepted for processing only. referenceId must echo."""
    if not isinstance(payload, dict):
        raise EtoroDemoOrderError("open response is not an object")
    echoed = _uuid(payload.get("referenceId"), "referenceId")
    if echoed != _uuid(reference_id, "reference_id"):
        raise EtoroDemoOrderError("open response referenceId does not echo the request")
    return OpenAcceptance(_int(payload.get("orderId"), "orderId"), echoed)


@dataclass(frozen=True)
class PositionExecution:
    position_id: int
    state: str                 # open | closed
    opened_by_order_id: int
    units: Decimal
    avg_price: Decimal
    fees: Decimal
    remaining_units: Decimal


@dataclass(frozen=True)
class DemoOrderOutcome:
    order_id: int
    status_id: int
    status: str
    instrument_id: int
    executions: tuple[PositionExecution, ...]
    error_code: int

    @property
    def terminal(self) -> bool:
        return self.status_id in TERMINAL_STATUSES

    @property
    def filled_units(self) -> Decimal:
        return sum((e.units for e in self.executions), ZERO)


def _execution(row: Any, order_id: int) -> PositionExecution:
    if not isinstance(row, dict) or not isinstance(row.get("openingData"), dict):
        raise EtoroDemoOrderError("positionExecutions entry is malformed")
    opening = row["openingData"]
    opened_by = _int(opening.get("orderId"), "openingData.orderId")
    if opened_by != order_id:
        raise EtoroDemoOrderError("position execution was opened by a different order")
    state = row.get("state")
    if state not in ("open", "closed"):
        raise EtoroDemoOrderError("position execution state is invalid")
    units = _dec(opening.get("units"), "openingData.units")
    price = _dec(opening.get("avgPrice"), "openingData.avgPrice")
    remaining = _dec(row.get("remainingUnits"), "remainingUnits")
    fees = _dec(opening.get("fees"), "openingData.fees")
    if units <= 0 or price <= 0 or fees < 0 or remaining < 0 or remaining > units:
        raise EtoroDemoOrderError("position execution quantities are inconsistent")
    return PositionExecution(_int(row.get("positionId"), "positionId"), state, opened_by,
                             units, price, fees, remaining)


def parse_order_lookup(payload: Any, *, request: DemoOpenRequest,
                       order_id: int | None = None) -> DemoOrderOutcome:
    """Strict ``orders:lookup`` parse, checked against the request SideDeck sent."""
    if not isinstance(payload, dict):
        raise EtoroDemoOrderError("lookup response is not an object")
    found_order = _int(payload.get("orderId"), "orderId")
    if order_id is not None and found_order != order_id:
        raise EtoroDemoOrderError("lookup returned a different order")
    if payload.get("action") != "open" or payload.get("transaction") != "buy":
        raise EtoroDemoOrderError("lookup order is not the long open SideDeck submitted")
    status = payload.get("status")
    asset = payload.get("asset")
    if not isinstance(status, dict) or not isinstance(asset, dict):
        raise EtoroDemoOrderError("lookup status or asset is missing")
    status_id = _int(status.get("id"), "status.id")
    if status_id not in ORDER_STATUS:
        raise EtoroDemoOrderError("lookup status is not a documented value")
    error_code = _int(status.get("errorCode"), "status.errorCode", minimum=0)
    if _int(asset.get("instrumentId"), "asset.instrumentId") != request.instrument_id:
        raise EtoroDemoOrderError("lookup instrument differs from the request")
    if asset.get("leverage") != 1 or asset.get("side") != "long":
        raise EtoroDemoOrderError("lookup reports leverage or direction SideDeck never requests")
    rows = payload.get("positionExecutions")
    if not isinstance(rows, list):
        raise EtoroDemoOrderError("positionExecutions is missing")
    executions = tuple(_execution(row, found_order) for row in rows)
    ids = [e.position_id for e in executions]
    if len(ids) != len(set(ids)):
        raise EtoroDemoOrderError("duplicate positionId in lookup")
    outcome = DemoOrderOutcome(found_order, status_id, ORDER_STATUS[status_id],
                               request.instrument_id, executions, error_code)
    if outcome.filled_units > request.units:
        raise EtoroDemoOrderError("filled units exceed the requested units")
    if any(e.avg_price > request.limit_rate for e in executions):
        raise EtoroDemoOrderError("execution price breaches the limit rate")
    if status_id in NO_FILL_TERMINAL and executions:
        raise EtoroDemoOrderError("a rejected/cancelled/expired order reports executions")
    if status_id == 3 and outcome.filled_units != request.units:
        raise EtoroDemoOrderError("FILLED status without the full requested units")
    if status_id in (5, 9, 10) and not executions:
        raise EtoroDemoOrderError("partial-fill status without executions")
    return outcome


@dataclass(frozen=True)
class CloseAcceptance:
    order_id: int
    position_id: int


def parse_close_acceptance(payload: Any, *, request: DemoCloseRequest) -> CloseAcceptance:
    block = payload.get("orderForClose") if isinstance(payload, dict) else None
    if not isinstance(block, dict):
        raise EtoroDemoOrderError("close response lacks orderForClose")
    if _int(block.get("positionID"), "positionID") != request.position_id:
        raise EtoroDemoOrderError("close response names a different position")
    if _int(block.get("instrumentID"), "instrumentID") != request.instrument_id:
        raise EtoroDemoOrderError("close response names a different instrument")
    return CloseAcceptance(_int(block.get("orderID"), "orderID"), request.position_id)


@dataclass(frozen=True)
class CloseOutcome:
    order_id: int
    status_id: int
    status: str
    closed_units: Decimal

    @property
    def terminal(self) -> bool:
        return self.status_id in TERMINAL_STATUSES


def parse_close_info(payload: Any, *, acceptance: CloseAcceptance) -> CloseOutcome:
    if not isinstance(payload, dict):
        raise EtoroDemoOrderError("close info is not an object")
    if _int(payload.get("orderID"), "orderID") != acceptance.order_id:
        raise EtoroDemoOrderError("close info returned a different order")
    status_id = _int(payload.get("statusID"), "statusID")
    if status_id not in ORDER_STATUS:
        raise EtoroDemoOrderError("close status is not a documented value")
    rows = payload.get("positions")
    if not isinstance(rows, list):
        raise EtoroDemoOrderError("close info positions missing")
    closed = ZERO
    for row in rows:
        if not isinstance(row, dict):
            raise EtoroDemoOrderError("close info position is malformed")
        if _int(row.get("positionID"), "positionID") != acceptance.position_id:
            raise EtoroDemoOrderError("close order touched a position SideDeck did not name")
        units = _dec(row.get("units"), "closed units")
        if units <= 0:
            raise EtoroDemoOrderError("closed units must be positive")
        closed += units
    if status_id in NO_FILL_TERMINAL and closed:
        raise EtoroDemoOrderError("a rejected/cancelled close reports closed units")
    return CloseOutcome(acceptance.order_id, status_id, ORDER_STATUS[status_id], closed)
