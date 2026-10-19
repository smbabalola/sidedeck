"""Operator-only read-only Saxo SIM client-wide exposure inspection.

Counts are client-wide, NOT specific-account reconciliation. If paging is present,
refuse to treat first page as complete. No broker order operations exist.
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import Any

from sidedeck.application.saxo_preflight import check
from sidedeck.infrastructure.saxo_sim import SaxoSimClient, SaxoSimError


@dataclass(frozen=True)
class ExposureInspection:
    currency: str
    open_position_count: int
    open_order_count: int
    complete: bool
    reason: str


def _collection_count(value: Any, label: str) -> int:
    if not isinstance(value, dict) or not isinstance(value.get("Data"), list):
        raise ValueError(f"invalid {label} response")
    if value.get("__next") or (isinstance(value.get("__count"), int)
                                and value["__count"] > len(value["Data"])):
        raise ValueError(f"{label} requires paginated retrieval")
    return len(value["Data"])


def inspect_exposure(
    balance: dict[str, Any],
    positions: dict[str, Any],
    orders: dict[str, Any],
) -> ExposureInspection:
    currency = balance.get("Currency")
    if not isinstance(currency, str) or not currency:
        raise ValueError("missing balance currency")
    position_count = _collection_count(positions, "positions")
    order_count = _collection_count(orders, "orders")
    broker_pos = balance.get("OpenPositionsCount")
    broker_orders = balance.get("OrdersCount")
    if type(broker_pos) is not int or type(broker_orders) is not int:
        raise ValueError("missing broker exposure counts")
    if broker_pos < 0 or broker_orders < 0:
        raise ValueError("invalid broker exposure counts")
    if position_count != broker_pos or order_count != broker_orders:
        return ExposureInspection(currency, position_count, order_count, False,
                                  "broker_counts_disagree")
    return ExposureInspection(currency, position_count, order_count, True,
                              "client_wide_snapshot_only")


def main() -> int:
    parser = argparse.ArgumentParser(description="Saxo SIM read-only exposure inspection")
    parser.add_argument("--expected-account-id",
                        default=os.getenv("SAXO_SIM_EXPECTED_ACCOUNT_ID", ""))
    args = parser.parse_args()
    try:
        client = SaxoSimClient()
        verified, reason = check(client, expected_account_id=args.expected_account_id)
        if not verified:
            print(f"BLOCKED: {reason}")
            return 2
        result = inspect_exposure(client.client_balance(), client.client_positions(),
                                  client.client_orders())
        print(f"Client-wide currency: {result.currency}; positions: {result.open_position_count}; "
              f"open orders: {result.open_order_count}")
        print(f"Snapshot: {result.reason}")
        print("No broker account reconciliation or paper order permission granted.")
        return 0 if result.complete else 2
    except (SaxoSimError, ValueError, PermissionError):
        print("BLOCKED: Saxo SIM exposure inspection could not be verified")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
