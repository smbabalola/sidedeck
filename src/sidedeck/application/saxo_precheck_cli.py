"""Operator-initiated Saxo SIM precheck; cannot place an order."""
from __future__ import annotations

import argparse
from sidedeck.infrastructure.saxo_account_scope import verified_scope
from sidedeck.infrastructure.saxo_sim import SaxoSimClient, SaxoSimError
from sidedeck.infrastructure.saxo_precheck import SaxoPrecheckError, run_sim_precheck


def main() -> int:
    parser = argparse.ArgumentParser(description="Saxo SIM single-share AAPL precheck only")
    parser.add_argument("--expected-account-id", required=True)
    args = parser.parse_args()
    if args.expected_account_id != "22866064":
        print("BLOCKED: SideDeck SIM account identity not approved")
        return 2
    try:
        scope = verified_scope(SaxoSimClient(), args.expected_account_id)
        result = run_sim_precheck(scope)
        print(f"Saxo SIM precheck: {result.result}; gate: {result.reason}")
        print(f"Broker estimated cash: {result.estimated_cash_required} {result.currency}")
        print("ORDER NOT SUBMITTED. Automatic paper and real-money orders disabled.")
        return 0 if result.result == "Ok" else 2
    except (SaxoSimError, SaxoPrecheckError, ValueError, PermissionError):
        print("BLOCKED: Saxo SIM broker precheck unavailable or rejected")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
