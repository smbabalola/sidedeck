"""Fail-closed Saxo SIM account readiness, before any external paper order.

Uses injected read-only responses, never places trades or mutates SideDeck ledgers.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True)
class SaxoReadiness:
    identity_verified: bool
    broker_currency: str
    orders_allowed: bool
    reason: str
    cash_available: Decimal | None
    open_order_count: int | None
    open_position_count: int | None


def _nonnegative(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("invalid amount type")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid amount") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError("nonfinite or negative amount")
    return parsed


def assess_saxo_readiness(
    accounts: dict[str, Any],
    balance: dict[str, Any],
    *,
    expected_account_id: str,
) -> SaxoReadiness:
    """Return information only; even eligible USD accounts cannot execute in P4 draft."""
    if not expected_account_id:
        raise ValueError("expected account identity required")
    records = accounts.get("Data")
    if not isinstance(records, list):
        raise ValueError("malformed account list")
    matches = [a for a in records if isinstance(a, dict)
               and a.get("AccountId") == expected_account_id]
    if len(matches) != 1 or matches[0].get("Active") is not True:
        return SaxoReadiness(False, "", False, "account_identity_unverified", None, None, None)
    currency = matches[0].get("Currency")
    if not isinstance(currency, str) or not currency:
        raise ValueError("missing account currency")
    if balance.get("Currency") != currency:
        return SaxoReadiness(True, currency, False, "balance_currency_mismatch", None, None, None)
    cash = _nonnegative(balance.get("CashAvailableForTrading"))
    orders = balance.get("OrdersCount")
    positions = balance.get("OpenPositionsCount")
    if (type(orders) is not int or type(positions) is not int
            or orders < 0 or positions < 0):
        raise ValueError("invalid broker exposure counts")
    if currency != "USD":
        return SaxoReadiness(True, currency, False, "currency_conversion_not_approved",
                             cash, orders, positions)
    if orders or positions:
        return SaxoReadiness(True, currency, False, "existing_broker_exposure_requires_reconciliation",
                             cash, orders, positions)
    return SaxoReadiness(True, currency, False, "paper_execution_not_enabled",
                         cash, orders, positions)
