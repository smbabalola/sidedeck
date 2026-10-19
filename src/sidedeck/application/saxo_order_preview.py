"""Fail-closed Saxo simulation order eligibility preview. Never submits orders.

EUR balances are not silently converted to SideDeck's USD virtual capital.
This module does not authorize execution, regardless of result.
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sidedeck.infrastructure.saxo_account_scope import scoped_get, verified_scope
from sidedeck.infrastructure.saxo_sim import SaxoSimClient, SaxoSimError


@dataclass(frozen=True)
class SaxoOrderPreview:
    account_verified: bool
    balance_currency: str
    account_cash: Decimal | None
    approved_for_submission: bool
    reason: str


def _cash(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("invalid cash field")
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid cash field") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("invalid cash field")
    return amount


def preview_account(
    accounts: dict[str, Any], balance: dict[str, Any], *,
    expected_account_id: str,
) -> SaxoOrderPreview:
    records = accounts.get("Data")
    if not expected_account_id or not isinstance(records, list):
        raise ValueError("missing expected account or malformed response")
    matches = [a for a in records if isinstance(a, dict)
               and a.get("AccountId") == expected_account_id
               and a.get("Active") is True]
    if len(matches) != 1:
        return SaxoOrderPreview(False, "", None, False, "account_unverified")
    account_currency = matches[0].get("Currency")
    if not isinstance(account_currency, str) or not account_currency:
        raise ValueError("account currency unavailable")
    if balance.get("Currency") != account_currency:
        return SaxoOrderPreview(True, account_currency, None, False, "currency_mismatch")
    amount = _cash(balance.get("CashAvailableForTrading"))
    if account_currency != "USD":
        return SaxoOrderPreview(True, account_currency, amount, False, "eur_usd_fx_not_approved")
    if amount <= 0:
        return SaxoOrderPreview(True, account_currency, amount, False, "no_cash_available")
    return SaxoOrderPreview(True, account_currency, amount, False, "order_submission_disabled")


def main() -> int:
    parser = argparse.ArgumentParser(description="Saxo SIM pre-order readiness, no trading")
    parser.add_argument("--expected-account-id",
                        default=os.getenv("SAXO_SIM_EXPECTED_ACCOUNT_ID", ""))
    args = parser.parse_args()
    try:
        client = SaxoSimClient()
        scope = verified_scope(client, args.expected_account_id)
        result = preview_account(client.accounts(), scoped_get(client, "balances", scope),
                                 expected_account_id=args.expected_account_id)
        print(f"Saxo SIM verified: {result.account_verified}; currency: {result.balance_currency}")
        print(f"Cash available (broker currency): {result.account_cash}")
        print(f"Execution status: BLOCKED ({result.reason})")
        print("No instrument validated, no order submitted, live trading disabled.")
        return 0 if result.account_verified else 2
    except (ValueError, SaxoSimError, PermissionError):
        print("BLOCKED: Saxo SIM pre-order preview could not be verified")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
