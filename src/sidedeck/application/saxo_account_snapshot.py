"""Operator-only, account-scoped SIM observation. No orders or ledger changes."""
from __future__ import annotations

import argparse
import os

from sidedeck.infrastructure.saxo_account_scope import scoped_get, verified_scope
from sidedeck.infrastructure.saxo_sim import SaxoSimClient, SaxoSimError


def main() -> int:
    parser = argparse.ArgumentParser(description="Read Saxo simulation account-specific snapshot")
    parser.add_argument("--expected-account-id",
                        default=os.getenv("SAXO_SIM_EXPECTED_ACCOUNT_ID", ""))
    args = parser.parse_args()
    try:
        client = SaxoSimClient()
        scope = verified_scope(client, args.expected_account_id)
        balance = scoped_get(client, "balances", scope)
        positions = scoped_get(client, "positions", scope)
        orders = scoped_get(client, "orders", scope)
        currency = balance.get("Currency")
        if not isinstance(currency, str) or not currency:
            raise ValueError("balance currency missing")
        if not isinstance(positions.get("Data"), list) or not isinstance(orders.get("Data"), list):
            raise ValueError("position or order response malformed")
        if positions.get("__next") or orders.get("__next"):
            raise ValueError("pagination requires complete retrieval")
        for result in (positions, orders):
            count = result.get("__count")
            if isinstance(count, int) and count > len(result["Data"]):
                raise ValueError("incomplete exposure page")
        print(f"Saxo SIM account-specific currency: {currency}")
        print(f"Position records: {len(positions['Data'])}; open orders: {len(orders['Data'])}")
        print("READ ONLY: cash and positions NOT reconciled to SideDeck USD portfolios.")
        print("Broker paper execution and live trading remain disabled.")
        return 0
    except (SaxoSimError, ValueError, PermissionError):
        print("BLOCKED: account-scoped Saxo SIM snapshot could not be verified")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
