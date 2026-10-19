"""Verify and precheck shortlisted US stocks on Saxo SIM; never place orders."""
from __future__ import annotations

import argparse
from typing import Any
from decimal import Decimal

from sidedeck.application.saxo_instrument_readiness import detail_path
from sidedeck.infrastructure.saxo_account_scope import verified_scope
from sidedeck.infrastructure.saxo_precheck import SaxoPrecheckError, run_sim_precheck
from sidedeck.infrastructure.saxo_sim import SaxoSimClient, SaxoSimError

SHORTLIST = {"SOFI": 23241352, "PLTR": 46019839, "INTC": 247}
CASH_CAP_EUR = Decimal("200")


def identity_valid(details: dict[str, Any], ticker: str, uic: int, account_key: str) -> bool:
    return (details.get("Uic") == uic
            and details.get("Symbol") == ticker + ":xnas"
            and details.get("AssetType") == "Stock"
            and details.get("CurrencyCode") == "USD"
            and details.get("TradingStatus") == "Tradable"
            and isinstance(details.get("TradableOn"), list)
            and account_key in details["TradableOn"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Saxo SIM shortlist broker precheck only")
    parser.add_argument("--expected-account-id", required=True)
    args = parser.parse_args()
    if args.expected_account_id != "22866064":
        print("BLOCKED: not the verified Saxo SIM test account")
        return 2
    try:
        client = SaxoSimClient()
        scope = verified_scope(client, args.expected_account_id)
        for ticker, uic in SHORTLIST.items():
            try:
                details = client.get(detail_path(scope, uic))
                if not identity_valid(details, ticker, uic, scope.account_key):
                    print(f"{ticker}: BLOCKED instrument/account eligibility not established")
                    continue
                result = run_sim_precheck(scope, uic=uic)
                affordable = (result.result == "Ok"
                              and result.estimated_cash_required is not None
                              and result.currency == "EUR"
                              and result.estimated_cash_required <= CASH_CAP_EUR)
                print(f"{ticker} UIC={uic}: precheck={result.result} "
                      f"broker_cash={result.estimated_cash_required} {result.currency} "
                      f"cap={'WITHIN_EUR_200' if affordable else 'BLOCKED'} "
                      f"reason={result.reason}")
            except (SaxoSimError, SaxoPrecheckError, ValueError, PermissionError):
                print(f"{ticker}: BLOCKED broker check unavailable")
        print("Prechecks only. No trades placed; price, FX and fills still unverified.")
        return 0
    except (SaxoSimError, ValueError, PermissionError):
        print("BLOCKED: unable to verify Saxo SIM account")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
