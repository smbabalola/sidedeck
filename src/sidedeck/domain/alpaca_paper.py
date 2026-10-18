"""Alpaca PAPER account inspection controlled by SideDeck.

Credential-free domain logic; broker account is NOT one of SideDeck's two
strategy subledgers. No order-write, cancel, reset, live brokerage or money
movement methods exist. A single paper account is an aggregate broker view.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from typing import Any, Literal, Mapping, Protocol

from .instruments import ALLOWED_INSTRUMENTS

PAPER_HOST = "https://paper-api.alpaca.markets"
APPROVED_SYMBOLS = frozenset(ALLOWED_INSTRUMENTS)
MAX_PAYLOAD_BYTES = 1_000_000
_ALLOWED_GET = frozenset({"/v2/account", "/v2/positions", "/v2/orders"})


class AlpacaPaperError(ValueError):
    """Paper API shape or portfolio violates SideDeck's access constraints."""


class AlpacaPaperAccessBlocked(RuntimeError):
    """Paper GET denied; no retry, fallback or order submission."""


class PaperGetTransport(Protocol):
    def get(self, path: str, params: Mapping[str, str]) -> tuple[int, bytes]: ...


def validate_paper_get(path: str, params: Mapping[str, str]) -> None:
    """No arbitrary host/path, account mutation, broker write or hidden query."""
    if path not in _ALLOWED_GET:
        raise AlpacaPaperError("route outside paper account read allowlist")
    expected = {"status": "open", "limit": "100"} if path == "/v2/orders" else {}
    if dict(params) != expected:
        raise AlpacaPaperError("unapproved paper account query parameters")


def _money(value: object, field_name: str, *, nonnegative: bool = False) -> Decimal:
    try:
        if value is None or isinstance(value, bool):
            raise ValueError("missing value")
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AlpacaPaperError(f"invalid numeric broker field: {field_name}") from exc
    if not parsed.is_finite() or (nonnegative and parsed < 0):
        raise AlpacaPaperError(f"invalid numeric broker field: {field_name}")
    return parsed


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AlpacaPaperError("expected JSON object")
    return value


def _rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 100 or any(not isinstance(x, dict) for x in value):
        raise AlpacaPaperError("expected bounded JSON list of objects")
    return value


@dataclass(frozen=True)
class PaperAccount:
    status: str
    cash: Decimal
    equity: Decimal
    buying_power: Decimal
    account_blocked: bool
    trading_blocked: bool
    multiplier: Decimal


@dataclass(frozen=True)
class PaperPosition:
    symbol: str
    quantity: Decimal
    average_entry_price: Decimal
    market_value: Decimal


@dataclass(frozen=True)
class PaperOpenOrder:
    symbol: str
    side: Literal["buy", "sell"]
    quantity: Decimal
    filled_quantity: Decimal
    status: str
    client_order_id: str


@dataclass(frozen=True)
class PaperPortfolioSnapshot:
    source: Literal["ALPACA_PAPER"]
    observed_at: datetime
    account: PaperAccount
    positions: tuple[PaperPosition, ...]
    open_orders: tuple[PaperOpenOrder, ...]
    broker_scope: Literal["SINGLE_BROKER_ACCOUNT_NOT_TWO_STRATEGY_LEDGERS"]


def _approved_symbol(row: Mapping[str, Any]) -> str:
    symbol = row.get("symbol")
    if not isinstance(symbol, str) or symbol not in APPROVED_SYMBOLS:
        raise AlpacaPaperError("paper account contains an unapproved instrument")
    return symbol


def _parse_account(row: object) -> PaperAccount:
    item = _object(row)
    status = item.get("status")
    if not isinstance(status, str) or not status:
        raise AlpacaPaperError("missing paper account status")
    if any(not isinstance(item.get(k, False), bool) for k in ("account_blocked", "trading_blocked")):
        raise AlpacaPaperError("invalid account restriction flags")
    return PaperAccount(
        status=status,
        cash=_money(item.get("cash"), "cash"),
        equity=_money(item.get("equity"), "equity"),
        buying_power=_money(item.get("buying_power"), "buying_power"),
        account_blocked=item.get("account_blocked", False),
        trading_blocked=item.get("trading_blocked", False),
        multiplier=_money(item.get("multiplier", "1"), "multiplier", nonnegative=True),
    )


def _parse_positions(rows: object) -> tuple[PaperPosition, ...]:
    parsed: list[PaperPosition] = []
    seen: set[str] = set()
    for row in _rows(rows):
        symbol = _approved_symbol(row)
        if symbol in seen or row.get("side") != "long" or row.get("asset_class", "us_equity") != "us_equity":
            raise AlpacaPaperError("duplicate, short or unsupported broker position")
        qty = _money(row.get("qty"), "position qty", nonnegative=True)
        if qty <= 0:
            raise AlpacaPaperError("paper position quantity must be positive")
        parsed.append(PaperPosition(
            symbol=symbol, quantity=qty,
            average_entry_price=_money(row.get("avg_entry_price"), "average entry", nonnegative=True),
            market_value=_money(row.get("market_value"), "market value", nonnegative=True),
        ))
        seen.add(symbol)
    return tuple(sorted(parsed, key=lambda p: p.symbol))


def _parse_orders(rows: object) -> tuple[PaperOpenOrder, ...]:
    parsed: list[PaperOpenOrder] = []
    seen: set[str] = set()
    for row in _rows(rows):
        symbol = _approved_symbol(row)
        side = row.get("side")
        if side not in ("buy", "sell"):
            raise AlpacaPaperError("unapproved paper order side")
        client_id = row.get("client_order_id")
        if not isinstance(client_id, str) or not client_id or client_id in seen:
            raise AlpacaPaperError("missing or duplicated paper order identity")
        qty = _money(row.get("qty"), "open order quantity", nonnegative=True)
        filled = _money(row.get("filled_qty"), "filled quantity", nonnegative=True)
        if qty <= 0 or filled > qty:
            raise AlpacaPaperError("invalid open order quantities")
        status = row.get("status")
        if not isinstance(status, str) or status not in {
            "new", "accepted", "pending_new", "partially_filled",
            "accepted_for_bidding", "held", "calculated",
            "pending_replace", "pending_cancel", "stopped", "suspended",
        }:
            raise AlpacaPaperError("unexpected open order status")
        parsed.append(PaperOpenOrder(symbol, side, qty, filled, status, client_id))
        seen.add(client_id)
    return tuple(parsed)


class AlpacaPaperReadClient:
    """Inspect a *single aggregate* paper account. Never places an order."""

    def __init__(self, transport: PaperGetTransport) -> None:
        self._transport = transport

    def _get(self, path: str, params: Mapping[str, str]) -> object:
        validate_paper_get(path, params)
        status, body = self._transport.get(path, params)
        if len(body) > MAX_PAYLOAD_BYTES:
            raise AlpacaPaperError("paper response too large")
        if status in (401, 403):
            raise AlpacaPaperAccessBlocked(f"Alpaca PAPER access denied ({status})")
        if status != 200:
            raise AlpacaPaperError(f"Alpaca PAPER read failed ({status})")
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AlpacaPaperError("malformed paper response") from exc

    def inspect(self, *, observed_at: datetime) -> PaperPortfolioSnapshot:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise AlpacaPaperError("inspection time must have timezone")
        account = _parse_account(self._get("/v2/account", {}))
        positions = _parse_positions(self._get("/v2/positions", {}))
        orders = _parse_orders(self._get("/v2/orders", {"status": "open", "limit": "100"}))
        return PaperPortfolioSnapshot(
            source="ALPACA_PAPER",
            observed_at=observed_at.astimezone(timezone.utc),
            account=account,
            positions=positions,
            open_orders=orders,
            broker_scope="SINGLE_BROKER_ACCOUNT_NOT_TWO_STRATEGY_LEDGERS",
        )
