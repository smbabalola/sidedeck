"""Dual Alpaca PAPER key-pair configuration and identity comparison.

No default network access. Identity check requires deliberate read-only
opt-in and exactly one GET /v2/account for each paper credential pair.
No account IDs or secrets are emitted; no broker orders exist here.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os

from sidedeck.domain.alpaca_paper import PaperGetTransport
from sidedeck.domain.alpaca_paper_pair import DualPaperAccountInspector
from sidedeck.paper import AlpacaPaperHttpTransport, PaperCredentials


def _secret_from_env(names: tuple[str, ...]) -> str:
    found = [os.environ[name] for name in names if os.environ.get(name)]
    if not found:
        raise ValueError("paired paper API secret missing for a strategy")
    if any(value != found[0] for value in found):
        raise ValueError("conflicting paper secret aliases for a strategy")
    return found[0]


def _paper_pair_credentials() -> tuple[PaperCredentials, PaperCredentials]:
    """Return local in-memory credentials; values NEVER used as log material."""
    first_key = os.environ.get("ALPACA_API_KEY")
    second_key = os.environ.get("ALPACA_API_KEY2")
    if not first_key or not second_key:
        raise ValueError("both ALPACA_API_KEY and ALPACA_API_KEY2 must be present")
    first_secret = _secret_from_env(
        ("ALPACA_SECRET_KEY", "ALPACA_API_SECRET_KEY", "APCA_API_SECRET_KEY")
    )
    second_secret = _secret_from_env(
        ("ALPACA_SECRET_KEY2", "ALPACA_API_SECRET_KEY2", "APCA_API_SECRET_KEY2")
    )
    if first_key == second_key:
        raise ValueError("paper key IDs are identical; independent account binding is unverified")
    if first_secret == second_secret:
        raise ValueError("paper secret values are identical; account binding is unverified")
    return (
        PaperCredentials(api_key=first_key, secret_key=first_secret),
        PaperCredentials(api_key=second_key, secret_key=second_secret),
    )


class _DryPairTransport(PaperGetTransport):
    def __init__(self, account_label: str) -> None:
        self._label = account_label

    def get(self, path: str, params: dict[str, str]) -> tuple[int, bytes]:
        if path != "/v2/account" or params:
            raise AssertionError("dry-run accesses only account identity")
        return 200, json.dumps({
            "id": f"FIXTURE-PAPER-{self._label}",
            "status": "ACTIVE", "cash": "1000", "equity": "1000",
            "buying_power": "1000", "multiplier": "1",
            "account_blocked": False, "trading_blocked": False,
        }).encode()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check separate SideDeck Alpaca PAPER accounts")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--paper-only", action="store_true")
    parser.add_argument("--allow-read-network", action="store_true")
    parser.add_argument("--confirm-owner-paper-read-only", action="store_true")
    args = parser.parse_args()
    if args.dry_run:
        first: PaperGetTransport = _DryPairTransport("A")
        second: PaperGetTransport = _DryPairTransport("B")
    else:
        if not (args.paper_only and args.allow_read_network and args.confirm_owner_paper_read_only):
            parser.error("requires --paper-only --allow-read-network --confirm-owner-paper-read-only")
        try:
            a, b = _paper_pair_credentials()
        except ValueError as exc:
            parser.error(str(exc))
        first = AlpacaPaperHttpTransport(a)
        second = AlpacaPaperHttpTransport(b)
    result = DualPaperAccountInspector(first, second).inspect()
    print(json.dumps({
        "source": "FIXTURE_NOT_REAL" if args.dry_run else "ALPACA_PAPER_READ_ONLY",
        **asdict(result),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
