"""Read-only account-scoped broker state evidence; no order submission."""
from __future__ import annotations

import argparse
from typing import Any

from sidedeck.infrastructure.saxo_account_scope import scoped_get, verified_scope
from sidedeck.infrastructure.saxo_sim import SaxoSimClient, SaxoSimError


def summarize_collection(data: dict[str, Any], kind: str) -> int:
    if not isinstance(data, dict) or not isinstance(data.get("Data"), list):
        raise ValueError(f"{kind} collection malformed")
    rows = data["Data"]
    if data.get("__next") or data.get("__skip") or (
        type(data.get("__count")) is int and data["__count"] > len(rows)
    ):
        raise ValueError(f"{kind} collection incomplete")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{kind} record malformed")
    return len(rows)


def reconcile_snapshot(client: SaxoSimClient, account_id: str) -> tuple[int, int]:
    scope = verified_scope(client, account_id)
    positions = summarize_collection(scoped_get(client, "positions", scope), "positions")
    orders = summarize_collection(scoped_get(client, "orders", scope), "orders")
    return positions, orders


def main() -> int:
    parser = argparse.ArgumentParser(description="Saxo SIM read-only orders/positions check")
    parser.add_argument("--expected-account-id", required=True)
    args = parser.parse_args()
    try:
        positions, orders = reconcile_snapshot(SaxoSimClient(), args.expected_account_id)
        print(f"Saxo SIM account-scoped snapshot: positions={positions} open_orders={orders}")
        print("Evidence only: fills/executions and historical orders NOT reconciled.")
        print("NO order submitted. Live trading disabled.")
        return 0
    except (ValueError, SaxoSimError, PermissionError):
        print("BLOCKED: complete Saxo account-scoped exposure unavailable")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
