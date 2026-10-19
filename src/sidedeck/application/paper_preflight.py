"""Operator-invoked read-only SideDeck paper preflight; never places orders.

Usage (from local venv with secrets set only in the environment):
    python -m sidedeck.application.paper_preflight --expected-account-id <uuid>

Only call this on the correct machine; this CLI does not synchronize live
broker positions into the experimental ledgers or authorize trading.
"""
from __future__ import annotations

import argparse

from sidedeck.infrastructure.alpaca_paper import AlpacaPaperBinding
from sidedeck.infrastructure.alpaca_readonly import AlpacaReadOnly
from sidedeck.infrastructure.alpaca_transport import PaperReadError, make_paper_get
from sidedeck.application.account_identity import verify_side_deck_paper_account


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only SideDeck paper-account preflight")
    parser.add_argument("--expected-account-id", required=True)
    args = parser.parse_args()
    try:
        client = AlpacaReadOnly(AlpacaPaperBinding(), make_paper_get(AlpacaPaperBinding()))
        account = client.account()
        result = verify_side_deck_paper_account(
            account, expected_account_id=args.expected_account_id,
        )
        if not result.verified:
            print(f"BLOCKED: {result.reason}")
            return 2
        positions = client.positions()
        open_orders = client.open_order_count()
        print("READ-ONLY IDENTITY VERIFIED; trading is still disabled")
        print(f"Position symbols: {len(positions)}; open orders: {open_orders}")
        print("Broker balances are NOT reconciled with internal experiment portfolios.")
        return 0
    except (ValueError, PaperReadError, PermissionError):
        print("BLOCKED: paper-account preflight could not be verified")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
