"""Read-only Alpaca paper interface, with injectable transport and no order methods."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Callable, Any

from sidedeck.infrastructure.alpaca_paper import AlpacaPaperBinding

Transport = Callable[[str], dict[str, Any]]


@dataclass(frozen=True)
class PaperAccount:
    account_id: str
    currency: str
    equity: Decimal
    cash: Decimal
    status: str


@dataclass(frozen=True)
class PaperPosition:
    symbol: str
    quantity: Decimal
    market_value: Decimal


class AlpacaReadOnly:
    """Transport only receives allowlisted relative GET paths; never credentials."""

    def __init__(self, binding: AlpacaPaperBinding, transport: Transport):
        if binding.enabled:
            raise ValueError("broker must remain disabled")
        self._binding = binding
        self._get = transport

    def account(self) -> PaperAccount:
        data = self._get("/v2/account")
        if not isinstance(data, dict):
            raise ValueError("invalid account response")
        if data.get("currency") != "USD":
            raise ValueError("expected USD account")
        account_id = data.get("id")
        if not isinstance(account_id, str) or not account_id:
            raise ValueError("missing account identity")
        cash = _amount(data.get("cash"))
        equity = _amount(data.get("equity"))
        status = data.get("status")
        if not isinstance(status, str) or not status:
            raise ValueError("missing account status")
        return PaperAccount(account_id, "USD", equity, cash, status)

    def positions(self) -> tuple[PaperPosition, ...]:
        records = self._get("/v2/positions")
        if not isinstance(records, list):
            raise ValueError("invalid positions response")
        result = []
        seen = set()
        for item in records:
            if not isinstance(item, dict):
                raise ValueError("invalid position")
            symbol = item.get("symbol")
            if not isinstance(symbol, str) or not symbol or symbol in seen:
                raise ValueError("invalid or duplicated symbol")
            seen.add(symbol)
            qty = _amount(item.get("qty"))
            if qty <= 0:
                raise ValueError("position quantity must be positive")
            result.append(PaperPosition(symbol, qty, _amount(item.get("market_value"))))
        return tuple(result)


def _amount(value: Any) -> Decimal:
    if not isinstance(value, str):
        raise ValueError("Alpaca numeric field must be a decimal string")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal response") from exc
    if not amount.is_finite():
        raise ValueError("nonfinite monetary value")
    return amount
