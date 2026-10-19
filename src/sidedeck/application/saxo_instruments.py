"""Account-scoped Saxo SIM stock instrument discovery; never trades."""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from sidedeck.infrastructure.saxo_account_scope import SaxoAccountScope, verified_scope
from sidedeck.infrastructure.saxo_sim import SaxoSimClient, SaxoSimError


@dataclass(frozen=True)
class StockCandidate:
    uic: int
    symbol: str
    asset_type: str
    description: str


def stock_lookup_path(scope: SaxoAccountScope, ticker: str) -> str:
    if not re.fullmatch(r"[A-Z]{1,6}", ticker):
        raise ValueError("ticker must consist of 1-6 uppercase letters")
    return ("/ref/v1/instruments?AccountKey=" + quote(scope.account_key, safe="")
            + "&AssetTypes=Stock&Keywords=" + ticker + "&%24top=20")


def parse_stock_candidates(data: dict[str, Any], *, ticker: str) -> tuple[StockCandidate, ...]:
    records = data.get("Data")
    if not isinstance(records, list) or data.get("__next") or len(records) > 20:
        raise ValueError("instrument search incomplete")
    count = data.get("__count")
    if isinstance(count, int) and count > len(records):
        raise ValueError("instrument search truncated")
    output = []
    seen: set[int] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("invalid instrument")
        if record.get("AssetType") != "Stock":
            continue
        uic = record.get("Identifier")
        symbol = record.get("Symbol")
        if type(uic) is not int or uic <= 0 or not isinstance(symbol, str):
            raise ValueError("invalid instrument identity")
        if uic in seen:
            raise ValueError("duplicate instrument UIC")
        seen.add(uic)
        if symbol.split(":")[0].upper() != ticker:
            continue
        description = record.get("Description", "")
        if not isinstance(description, str):
            raise ValueError("invalid description")
        output.append(StockCandidate(uic, symbol, "Stock", description))
    return tuple(output)


def main() -> int:
    parser = argparse.ArgumentParser(description="Saxo SIM stock discovery (read only)")
    parser.add_argument("--expected-account-id", required=True)
    parser.add_argument("--ticker", default="AAPL")
    args = parser.parse_args()
    try:
        client = SaxoSimClient()
        scope = verified_scope(client, args.expected_account_id)
        results = parse_stock_candidates(client.get(stock_lookup_path(scope, args.ticker)),
                                         ticker=args.ticker)
        print(f"Saxo SIM Stock matches: {len(results)}")
        for item in results:
            print(f"UIC={item.uic} Symbol={item.symbol} Description={item.description[:70]}")
        print("Candidates only: exchange, currency, tradability and quotes NOT verified.")
        print("Order submission remains disabled.")
        return 0
    except (SaxoSimError, ValueError, PermissionError):
        print("BLOCKED: Saxo SIM instrument lookup could not be verified")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
