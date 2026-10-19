"""Saxo SIM order precheck ONLY: never submit, amend, or cancel an order.

Unlike /trade/v2/orders, /trade/v2/orders/precheck validates an order
without placing it. A successful precheck does not authorize execution.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sidedeck.infrastructure.saxo_account_scope import SaxoAccountScope

_PRECHECK_URL = "https://gateway.saxobank.com/sim/openapi/trade/v2/orders/precheck"


class SaxoPrecheckError(RuntimeError):
    """Redacted error; token, account key and response body must not be logged."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int,
                         msg: str, headers: Any, newurl: str) -> None:
        return None


def precheck_payload(scope: SaxoAccountScope, *, uic: int = 211,
                     amount: int = 1) -> dict[str, Any]:
    if uic != 211 or type(amount) is not int or amount != 1:
        raise ValueError("precheck restricted to one AAPL:xnas Stock share")
    return {
        "AccountKey": scope.account_key, "Uic": 211, "AssetType": "Stock",
        "BuySell": "Buy", "Amount": 1, "OrderType": "Market",
        "OrderDuration": {"DurationType": "DayOrder"},
        "FieldGroups": ["Costs"], "ManualOrder": True,
    }


@dataclass(frozen=True)
class PrecheckDecision:
    result: str
    safe_to_submit: bool
    reason: str
    estimated_cash_required: Decimal | None
    currency: str


def parse_precheck(data: dict[str, Any]) -> PrecheckDecision:
    if not isinstance(data, dict):
        raise ValueError("malformed broker precheck response")
    result = data.get("PreCheckResult")
    if data.get("ErrorInfo") or result != "Ok":
        return PrecheckDecision(str(result), False, "broker_precheck_not_ok", None, "")
    disclaimers = data.get("PreTradeDisclaimers")
    if disclaimers:
        return PrecheckDecision("Ok", False, "disclaimers_require_review", None, "")
    currency = data.get("EstimatedCashRequiredCurrency")
    raw = data.get("EstimatedCashRequired")
    if currency not in ("EUR", "USD") or isinstance(raw, bool):
        return PrecheckDecision("Ok", False, "cash_estimate_missing", None, "")
    try:
        amount = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return PrecheckDecision("Ok", False, "cash_estimate_invalid", None, "")
    if not amount.is_finite() or amount <= 0:
        return PrecheckDecision("Ok", False, "cash_estimate_invalid", None, "")
    # No independent market quote or approved EUR/USD accounting currently exists.
    return PrecheckDecision("Ok", False, "execution_gate_still_disabled", amount, currency)


def run_sim_precheck(scope: SaxoAccountScope, *, timeout_seconds: float = 10) -> PrecheckDecision:
    """One broker precheck POST, strictly SIM-only; /orders is never called."""
    if timeout_seconds <= 0 or timeout_seconds > 30:
        raise ValueError("invalid timeout")
    token = os.environ.get("SAXO_SIM_ACCESS_TOKEN")
    if not token:
        raise SaxoPrecheckError("Saxo SIM token unavailable")
    payload = json.dumps(precheck_payload(scope)).encode("utf-8")
    req = Request(
        _PRECHECK_URL, data=payload, method="POST",
        headers={"Authorization": "Bearer " + token, "Accept": "application/json",
                 "Content-Type": "application/json"},
    )
    try:
        with build_opener(_NoRedirect()).open(req, timeout=timeout_seconds) as response:
            raw = response.read(200_001)
            if len(raw) > 200_000:
                raise SaxoPrecheckError("precheck response oversized")
            data = json.loads(raw)
    except HTTPError as exc:
        raise SaxoPrecheckError(f"Saxo SIM precheck HTTP {exc.code}") from None
    except (URLError, OSError, ValueError):
        raise SaxoPrecheckError("Saxo SIM precheck connection or response failed") from None
    return parse_precheck(data)
