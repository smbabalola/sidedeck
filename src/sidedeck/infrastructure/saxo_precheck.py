"""Saxo SIM order precheck ONLY: never submit, amend, or cancel an order.

Unlike /trade/v2/orders, /trade/v2/orders/precheck validates an order
without placing it. A successful precheck does not authorize execution.
"""
from __future__ import annotations

import json
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sidedeck.infrastructure.saxo_account_scope import SaxoAccountScope

_PRECHECK_URL = "https://gateway.saxobank.com/sim/openapi/trade/v2/orders/precheck"
# Process-local key: evidence parsed from a hand-built dict, a fixture, or a
# previous process can never carry a valid transport seal.
_TRANSPORT_SEAL_KEY = secrets.token_bytes(32)


class SaxoPrecheckError(RuntimeError):
    """Redacted error; token, account key and response body must not be logged."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int,
                         msg: str, headers: Any, newurl: str) -> None:
        return None


def precheck_payload(scope: SaxoAccountScope, *, uic: int = 211,
                     amount: int = 1) -> dict[str, Any]:
    if uic not in (211, 23241352, 46019839, 247) or type(amount) is not int or amount != 1:
        raise ValueError("precheck restricted to one share of an allowlisted NASDAQ stock")
    return {
        "AccountKey": scope.account_key, "Uic": uic, "AssetType": "Stock",
        "BuySell": "Buy", "Amount": 1, "OrderType": "Market",
        "OrderDuration": {"DurationType": "DayOrder"},
        "FieldGroups": ["Costs"], "ManualOrder": True,
    }


@dataclass(frozen=True)
class PrecheckEvidence:
    result: str
    reason: str
    estimated_cash_required: Decimal | None
    cash_currency: str
    estimated_total_cost: Decimal | None
    total_cost_currency: str
    estimated_total_cost_account: Decimal | None
    account_cost_currency: str
    instrument_to_account_rate: Decimal | None
    request_sha256: str = ""
    response_sha256: str = ""
    collected_at: datetime | None = None
    account_id: str = ""
    uic: int = 0
    side: str = ""
    quantity: int = 0
    order_type: str = ""
    duration_type: str = ""
    transport_seal: str = ""

    def _seal_material(self) -> bytes:
        collected = self.collected_at.isoformat() if self.collected_at else ""
        return json.dumps([
            self.result, self.reason, str(self.estimated_cash_required), self.cash_currency,
            str(self.estimated_total_cost), self.total_cost_currency,
            str(self.estimated_total_cost_account), self.account_cost_currency,
            str(self.instrument_to_account_rate), self.request_sha256, self.response_sha256,
            collected, self.account_id, self.uic, self.side, self.quantity,
            self.order_type, self.duration_type,
        ], separators=(",", ":")).encode("utf-8")

    def is_transport_sealed(self) -> bool:
        """True only for evidence returned by this process's SIM precheck POST."""
        if not self.transport_seal:
            return False
        expected = hmac.new(_TRANSPORT_SEAL_KEY, self._seal_material(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, self.transport_seal)

    @property
    def currency(self) -> str:
        """Compatibility display field; never an authorization decision."""
        return self.cash_currency

    def validate_for_order(self, *, instrument_currency: str,
                           account_currency: str, account_id: str,
                           uic: int, request_sha256: str,
                           now: datetime, max_age: timedelta = timedelta(minutes=2)) -> None:
        """Validate broker facts; this is not execution authorization."""
        if self.result != "Ok" or self.reason != "broker_precheck_validated":
            raise ValueError("broker precheck is not valid")
        if (self.account_id != account_id or self.uic != uic or self.side != "Buy"
                or self.quantity != 1 or self.order_type != "Market"
                or self.duration_type != "DayOrder"):
            raise ValueError("broker precheck order identity mismatch")
        if self.request_sha256 != request_sha256 or not self.response_sha256:
            raise ValueError("broker precheck is not bound to the exact request")
        if self.collected_at is None or now.tzinfo is None or self.collected_at.tzinfo is None:
            raise ValueError("broker precheck timestamp is missing")
        age = now.astimezone(timezone.utc) - self.collected_at.astimezone(timezone.utc)
        if age < timedelta(0) or age > max_age:
            raise ValueError("broker precheck is stale or future-dated")
        if not self.estimated_cash_required or not self.cash_currency:
            raise ValueError("broker cash requirement is missing")
        if self.cash_currency != account_currency:
            raise ValueError("cash requirement currency differs from account currency")
        if self.total_cost_currency != instrument_currency:
            raise ValueError("precheck total cost currency differs from instrument currency")
        if self.account_cost_currency != account_currency:
            raise ValueError("precheck account cost currency is not the account currency")
        if (self.estimated_total_cost is None or self.estimated_total_cost_account is None
                or self.instrument_to_account_rate is None):
            raise ValueError("precheck conversion evidence is incomplete")
        if (not self.estimated_total_cost.is_finite()
                or not self.estimated_total_cost_account.is_finite()
                or not self.instrument_to_account_rate.is_finite()
                or self.estimated_total_cost <= 0
                or self.estimated_total_cost_account <= 0
                or self.instrument_to_account_rate <= 0):
            raise ValueError("precheck conversion evidence is invalid")


def parse_precheck(data: dict[str, Any], *, instrument_currency: str | None = None,
                   account_currency: str | None = None,
                   request_payload: dict[str, Any] | None = None,
                   account_id: str = "", collected_at: datetime | None = None) -> PrecheckEvidence:
    if not isinstance(data, dict):
        raise ValueError("malformed broker precheck response")
    result = data.get("PreCheckResult")
    if data.get("ErrorInfo") or result != "Ok":
        return PrecheckEvidence(str(result), "broker_precheck_not_ok", None, "",
                                None, "", None, "", None, account_id=account_id,
                                collected_at=collected_at)
    disclaimers = data.get("PreTradeDisclaimers")
    if disclaimers:
        return PrecheckEvidence("Ok", "disclaimers_require_review", None, "",
                                None, "", None, "", None, account_id=account_id,
                                collected_at=collected_at)
    currency = data.get("EstimatedCashRequiredCurrency")
    raw = data.get("EstimatedCashRequired")
    total_currency = data.get("EstimatedTotalCostCurrency") or instrument_currency
    response_account_currency = data.get("EstimatedTotalCostInAccountCurrencyCurrency")
    if (currency not in ("EUR", "USD") or not isinstance(total_currency, str)
            or not total_currency or not isinstance(account_currency, str)
            or not account_currency or (response_account_currency is not None
                                        and response_account_currency != account_currency)
            or isinstance(raw, bool)):
        return PrecheckEvidence("Ok", "cash_estimate_missing", None, "",
                                None, "", None, "", None, account_id=account_id,
                                collected_at=collected_at)
    try:
        amount = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return PrecheckEvidence("Ok", "cash_estimate_invalid", None, "",
                                None, "", None, "", None, account_id=account_id,
                                collected_at=collected_at)
    if not amount.is_finite() or amount <= 0:
        return PrecheckEvidence("Ok", "cash_estimate_invalid", None, "",
                                None, "", None, "", None, account_id=account_id,
                                collected_at=collected_at)
    canonical_request = json.dumps(request_payload or {}, sort_keys=True, separators=(",", ":"))
    request_sha256 = hashlib.sha256(canonical_request.encode()).hexdigest()
    response_sha256 = hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    payload = request_payload or {}
    def money(name: str) -> Decimal | None:
        value = data.get(name)
        if isinstance(value, bool) or value is None:
            return None
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None
        return parsed if parsed.is_finite() and parsed > 0 else None
    return PrecheckEvidence(
        "Ok", "broker_precheck_validated", amount, currency,
        money("EstimatedTotalCost"), total_currency,
        money("EstimatedTotalCostInAccountCurrency"), account_currency,
        money("InstrumentToAccountConversionRate"), request_sha256, response_sha256,
        collected_at, account_id, payload.get("Uic", 0), payload.get("BuySell", ""),
        payload.get("Amount", 0), payload.get("OrderType", ""),
        (payload.get("OrderDuration") or {}).get("DurationType", ""),
    )


def run_sim_precheck(scope: SaxoAccountScope, *, uic: int = 211,
                     instrument_currency: str = "USD",
                     account_currency: str | None = None,
                     timeout_seconds: float = 10,
                     clock: Callable[[], datetime] | None = None) -> PrecheckEvidence:
    """One broker precheck POST, strictly SIM-only; /orders is never called."""
    if timeout_seconds <= 0 or timeout_seconds > 30:
        raise ValueError("invalid timeout")
    token = os.environ.get("SAXO_SIM_ACCESS_TOKEN")
    if not token:
        raise SaxoPrecheckError("Saxo SIM token unavailable")
    payload = precheck_payload(scope, uic=uic)
    encoded_payload = json.dumps(payload).encode("utf-8")
    req = Request(
        _PRECHECK_URL, data=encoded_payload, method="POST",
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
    evidence = parse_precheck(data, instrument_currency=instrument_currency,
                              account_currency=account_currency, request_payload=payload,
                              account_id=scope.account_id,
                              collected_at=(clock or (lambda: datetime.now(timezone.utc)))())
    if evidence.reason != "broker_precheck_validated":
        return evidence
    seal = hmac.new(_TRANSPORT_SEAL_KEY, evidence._seal_material(), hashlib.sha256).hexdigest()
    return replace(evidence, transport_seal=seal)
