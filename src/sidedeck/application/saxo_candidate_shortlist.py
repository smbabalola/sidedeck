"""Read-only shortlist of NASDAQ-listed Saxo SIM stock candidates.

Discovery does not imply broker trade eligibility, affordability or an approved order.
"""
from __future__ import annotations

import argparse
from typing import Any

from sidedeck.application.saxo_instruments import (
    parse_stock_candidates,
    stock_lookup_path,
)
from sidedeck.application.saxo_instrument_readiness import detail_path
from sidedeck.infrastructure.saxo_account_scope import verified_scope
from sidedeck.infrastructure.saxo_sim import SaxoSimClient, SaxoSimError

# Fixed, reviewable universe; do not pick tickers dynamically from untrusted data.
TICKERS = ("F", "SOFI", "PLTR", "PFE", "T", "INTC")


def evaluate_candidate(candidate: object, detail: dict[str, Any]) -> tuple[bool, str]:
    uic = getattr(candidate, "uic", None)
    symbol = getattr(candidate, "symbol", None)
    if not isinstance(symbol, str) or not symbol.endswith(":xnas"):
        return False, "not_nasdaq"
    if (type(uic) is not int or detail.get("Uic") != uic
            or detail.get("Symbol") != symbol or detail.get("AssetType") != "Stock"):
        return False, "instrument_mismatch"
    if detail.get("CurrencyCode") != "USD":
        return False, "currency_not_usd"
    if detail.get("TradingStatus") != "Tradable" or not detail.get("TradableOn"):
        return False, "tradability_unverified"
    return True, "detail_candidate_only"


def main() -> int:
    parser = argparse.ArgumentParser(description="Saxo SIM NASDAQ stock shortlist, read-only")
    parser.add_argument("--expected-account-id", required=True)
    args = parser.parse_args()
    try:
        client = SaxoSimClient()
        scope = verified_scope(client, args.expected_account_id)
        for ticker in TICKERS:
            try:
                candidates = parse_stock_candidates(
                    client.get(stock_lookup_path(scope, ticker)), ticker=ticker
                )
                nasdaq = [c for c in candidates if c.symbol == f"{ticker}:xnas"]
                if len(nasdaq) != 1:
                    print(f"{ticker}: no_unique_nasdaq_stock")
                    continue
                c = nasdaq[0]
                eligible, reason = evaluate_candidate(
                    c, client.get(detail_path(scope, c.uic))
                )
                print(f"{ticker}: UIC={c.uic} Symbol={c.symbol} "
                      f"Detail={'CANDIDATE' if eligible else 'BLOCKED'} ({reason})")
            except (ValueError, SaxoSimError, PermissionError):
                print(f"{ticker}: lookup_or_details_unavailable")
        print("No price or broker cash estimate checked; all candidates require fresh precheck.")
        print("NO ORDER SUBMITTED; automatic and live trading disabled.")
        return 0
    except (ValueError, SaxoSimError, PermissionError):
        print("BLOCKED: Saxo SIM identity or scope not verified")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
