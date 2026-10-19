"""SOFI SIM pre-execution acceptance report. This cannot place an order."""
from __future__ import annotations

import argparse
from decimal import Decimal

from sidedeck.application.saxo_instrument_readiness import detail_path
from sidedeck.application.saxo_shortlist_precheck import identity_valid
from sidedeck.infrastructure.saxo_account_scope import scoped_get, verified_scope
from sidedeck.infrastructure.saxo_precheck import run_sim_precheck, SaxoPrecheckError
from sidedeck.infrastructure.saxo_sim import SaxoSimClient, SaxoSimError

SOFI_UIC = 23241352
EUR_SINGLE_ORDER_CAP = Decimal("200")
USD_SINGLE_ORDER_CAP = Decimal("200")


def acceptance_reasons(*, detail_ok: bool, precheck_ok: bool,
                       estimate_eur: Decimal | None, account_currency: str,
                       positions: int, orders: int) -> tuple[str, ...]:
    reasons: list[str] = []
    if not detail_ok:
        reasons.append("account_stock_identity_unverified")
    if account_currency != "EUR":
        reasons.append("account_currency_mismatch")
    if positions != 0 or orders != 0:
        reasons.append("unexpected_existing_broker_exposure")
    if not precheck_ok or estimate_eur is None or not estimate_eur.is_finite():
        reasons.append("broker_precheck_unavailable")
    elif estimate_eur <= 0 or estimate_eur > EUR_SINGLE_ORDER_CAP:
        reasons.append("estimated_cash_exceeds_risk_cap")
    # The following are deliberately *not* considered complete based on precheck.
    reasons.extend(("verified_independent_price_missing",
                    "approved_eur_usd_fx_and_fees_missing",
                    "broker_fills_and_ambiguous_submit_recovery_missing",
                    "single_sim_order_submit_not_implemented"))
    return tuple(reasons)


def _count(data: dict, label: str) -> int:
    records = data.get("Data")
    if not isinstance(records, list) or data.get("__next") or (
        type(data.get("__count")) is int and data["__count"] > len(records)
    ):
        raise ValueError(f"{label} account exposure incomplete")
    if any(not isinstance(row, dict) for row in records):
        raise ValueError(f"{label} malformed")
    return len(records)


def main() -> int:
    parser = argparse.ArgumentParser(description="SOFI SIM acceptance, never execution")
    parser.add_argument("--expected-account-id", required=True)
    args = parser.parse_args()
    if args.expected_account_id != "22866064":
        print("NO-GO: wrong simulation account")
        return 2
    try:
        client = SaxoSimClient()
        scope = verified_scope(client, args.expected_account_id)
        details = client.get(detail_path(scope, SOFI_UIC))
        eligible = identity_valid(details, "SOFI", SOFI_UIC, scope.account_id)
        if not eligible:
            print("NO-GO: SOFI instrument/account not verified")
            return 2
        balance = scoped_get(client, "balances", scope)
        positions = _count(scoped_get(client, "positions", scope), "positions")
        orders = _count(scoped_get(client, "orders", scope), "orders")
        precheck = run_sim_precheck(scope, uic=SOFI_UIC)
        estimate = precheck.estimated_cash_required if precheck.currency == "EUR" else None
        reasons = acceptance_reasons(
            detail_ok=eligible, precheck_ok=precheck.result == "Ok",
            estimate_eur=estimate, account_currency=balance.get("Currency", ""),
            positions=positions, orders=orders)
        print(f"SOFI:xnas UIC={SOFI_UIC}; broker precheck={precheck.result}")
        print(f"Estimated broker cash={estimate} EUR; ceiling={EUR_SINGLE_ORDER_CAP} EUR")
        print(f"Current Saxo account exposure: positions={positions}; open_orders={orders}")
        print("Acceptance: NO-GO")
        for reason in reasons:
            print(" - " + reason)
        print("No order submitted; live and automatic execution disabled.")
        return 0
    except (SaxoSimError, SaxoPrecheckError, ValueError, PermissionError):
        print("NO-GO: Saxo SIM acceptance diagnostic unavailable")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
