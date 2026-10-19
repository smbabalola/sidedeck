"""Saxo SIM stock detail and indicative price validation, no order placement."""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

from sidedeck.infrastructure.saxo_account_scope import verified_scope, SaxoAccountScope
from sidedeck.infrastructure.saxo_sim import SaxoSimClient, SaxoSimError


@dataclass(frozen=True)
class InstrumentReadiness:
    instrument_verified: bool
    currency: str
    tradable: bool
    reason: str


def detail_path(scope: SaxoAccountScope, uic: int) -> str:
    if type(uic) is not int or uic < 1:
        raise ValueError("invalid UIC")
    return (f"/ref/v1/instruments/details/{uic}/Stock?AccountKey="
            + quote(scope.account_key, safe="") + "&ClientKey="
            + quote(scope.client_key, safe=""))


def price_path(scope: SaxoAccountScope, uic: int) -> str:
    if type(uic) is not int or uic < 1:
        raise ValueError("invalid UIC")
    return ("/trade/v1/infoprices?AccountKey="
            + quote(scope.account_key, safe="") + f"&AssetType=Stock&Uic={uic}")


def assess_detail(detail: dict[str, Any], *, expected_uic: int,
                  expected_symbol: str = "AAPL:xnas") -> InstrumentReadiness:
    if detail.get("Uic") != expected_uic or detail.get("AssetType") != "Stock":
        return InstrumentReadiness(False, "", False, "instrument_identity_mismatch")
    if detail.get("Symbol") != expected_symbol:
        return InstrumentReadiness(False, "", False, "exchange_symbol_mismatch")
    currency = detail.get("CurrencyCode")
    if currency != "USD" or detail.get("PriceCurrency", "USD") != "USD":
        return InstrumentReadiness(False, str(currency), False, "non_usd_stock")
    status = detail.get("TradingStatus")
    accounts = detail.get("TradableOn")
    if status != "Tradable" or not isinstance(accounts, list) or not accounts:
        return InstrumentReadiness(True, "USD", False, "tradability_not_verified")
    return InstrumentReadiness(True, "USD", True, "detail_candidate_only")


def inspect_price(data: dict[str, Any]) -> str:
    """Info price is indicative, NEVER an executable fill/verified fresh quote."""
    if not isinstance(data, dict):
        raise ValueError("malformed info price")
    q = data.get("Quote")
    if not isinstance(q, dict):
        return "quote_not_available"
    for key in ("Bid", "Ask"):
        v = q.get(key)
        if v is None:
            return "bid_ask_not_available"
        try:
            d = Decimal(str(v))
        except InvalidOperation as exc:
            raise ValueError("invalid quote") from exc
        if not d.is_finite() or d <= 0:
            raise ValueError("invalid quote")
    if Decimal(str(q["Bid"])) > Decimal(str(q["Ask"])):
        raise ValueError("crossed quote")
    return "indicative_bid_ask_observed_freshness_unverified"


def main() -> int:
    parser = argparse.ArgumentParser(description="Saxo SIM AAPL NASDAQ read-only detail and info price")
    parser.add_argument("--expected-account-id",
                        default=os.getenv("SAXO_SIM_EXPECTED_ACCOUNT_ID", ""))
    args = parser.parse_args()
    try:
        client = SaxoSimClient()
        scope = verified_scope(client, args.expected_account_id)
        detail = client.get(detail_path(scope, 211))
        decision = assess_detail(detail, expected_uic=211)
        print(f"AAPL:xnas UIC 211: {decision.reason}; currency={decision.currency}")
        if not decision.tradable:
            print("BLOCKED: instrument not verified for trading. No order placed.")
            return 2
        quote = client.get(price_path(scope, 211))
        print("Info price:", inspect_price(quote))
        print("NOT EXECUTION READY: indicative quotes, USD/EUR accounting and precheck outstanding.")
        print("No orders placed; live trading disabled.")
        return 0
    except (SaxoSimError, ValueError, PermissionError):
        print("BLOCKED: Saxo instrument detail or quote inspection failed")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
