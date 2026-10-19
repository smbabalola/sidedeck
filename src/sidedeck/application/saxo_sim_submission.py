"""Controlled Saxo SIM submission boundary.

This module constructs and validates one SOFI share request but is disabled by
default. Three independent switches must all be on before a POST can happen:
the module release constant (``SIM_SUBMISSION_RELEASED``), an explicitly
enabled submitter with an injected transport, and an operator approval signed
outside SideDeck. The normal SideDeck application sets none of them.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Protocol

from sidedeck.application.saxo_market_data import EvidenceOrigin, ExecutionEvidence, MarketEvidenceVerifier
from sidedeck.application.saxo_order_lifecycle import advance_lifecycle, create_lifecycle, lifecycle_state
from sidedeck.infrastructure.saxo_account_scope import SaxoAccountScope
from sidedeck.infrastructure.saxo_operator_approval import APPROVAL_NAMESPACE, valid_principal
from sidedeck.infrastructure.saxo_precheck import PrecheckEvidence, precheck_payload

SIM_HOST = "https://gateway.saxobank.com/sim/openapi"
SOFI_UIC = 23241352

# P4_DECISION=NO-GO. Only a separately approved release may change this value;
# no constructor argument, environment variable or CLI flag can override it.
SIM_SUBMISSION_RELEASED = False

MAX_REQUEST_AGE = timedelta(minutes=5)
MAX_APPROVAL_LIFETIME = timedelta(minutes=10)
FX_TOLERANCE = Decimal("0.02")
CASH_TOLERANCE = Decimal("0.05")
APPROVAL_VERSION = "sidedeck-saxo-sim-approval-v1"
_ORDER_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,49}")
_SELF_ATTESTING = ("attest", "sign", "approve", "issue")

AUTHORIZATION_DDL = (
    "CREATE TABLE IF NOT EXISTS saxo_execution_authorization ("
    "authorization_id TEXT PRIMARY KEY, order_key TEXT UNIQUE NOT NULL, "
    "account_id TEXT NOT NULL, portfolio_id TEXT NOT NULL, "
    "request_sha256 TEXT NOT NULL, broker_payload_sha256 TEXT NOT NULL, "
    "risk_evidence_sha256 TEXT NOT NULL, attestation TEXT NOT NULL, "
    "issued_by TEXT NOT NULL, expires_at TEXT NOT NULL, "
    "status TEXT NOT NULL CHECK(status IN ('ISSUED','CONSUMED','REJECTED','UNKNOWN')), "
    "broker_order_id TEXT, quantity TEXT NOT NULL DEFAULT '1', "
    "requested_by TEXT NOT NULL DEFAULT '')"
)


def ensure_authorization_table(db: sqlite3.Connection) -> None:
    db.execute(AUTHORIZATION_DDL)


class SimSubmitTransport(Protocol):
    def submit(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class ApprovalVerifier(Protocol):
    """Verify-only boundary for a human approval made outside SideDeck.

    Implementations hold public verification material only. An object that can
    also attest/sign is rejected, because it would let SideDeck approve itself.
    """

    def verify(self, attestation: str, material: str, principal: str) -> bool: ...


@dataclass(frozen=True)
class ExecutionAuthorization:
    """One operator authorization bound to every material order fact."""

    authorization_id: str
    issued_by: str
    requested_by: str
    order_key: str
    account_id: str
    portfolio_id: str
    ticker: str
    uic: int
    side: str
    quantity: int
    order_type: str
    request_sha256: str
    broker_payload_sha256: str
    risk_evidence_sha256: str
    expires_at: datetime
    attestation: str = ""


@dataclass(frozen=True)
class SimOrderRequest:
    order_key: str
    portfolio_id: str
    account_id: str
    broker_account_key: str
    external_reference: str
    ticker: str
    uic: int
    quantity: int
    expected_price_usd: Decimal
    expected_cost_usd: Decimal
    fx_eur_to_usd: Decimal
    precheck_cash_eur: Decimal
    precheck_sha256: str
    risk_evidence_sha256: str
    prepared_at: datetime
    requested_by: str

    def payload(self) -> dict[str, Any]:
        return {
            "AccountKey": self.broker_account_key,
            "Uic": self.uic,
            "AssetType": "Stock",
            "BuySell": "Buy",
            "Amount": self.quantity,
            "OrderType": "Market",
            "OrderDuration": {"DurationType": "DayOrder"},
            "ExternalReference": self.external_reference,
        }

    def digest(self) -> str:
        body = json.dumps({
            "order_key": self.order_key, "portfolio_id": self.portfolio_id,
            "account_id": self.account_id, "ticker": self.ticker, "uic": self.uic,
            "quantity": self.quantity, "expected_price_usd": str(self.expected_price_usd),
            "expected_cost_usd": str(self.expected_cost_usd),
            "fx_eur_to_usd": str(self.fx_eur_to_usd),
            "precheck_cash_eur": str(self.precheck_cash_eur),
            "precheck_sha256": self.precheck_sha256,
            "risk_evidence_sha256": self.risk_evidence_sha256,
            "prepared_at": self.prepared_at.isoformat(),
            "requested_by": self.requested_by,
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def broker_payload_digest(self) -> str:
        body = json.dumps(self.payload(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(body.encode("utf-8")).hexdigest()


class SubmissionBlocked(RuntimeError):
    """A safety gate prevented a broker submission attempt."""


def _utc(value: datetime, what: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{what} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _within(actual: Decimal, expected: Decimal, tolerance: Decimal) -> bool:
    return expected > 0 and abs(actual - expected) <= expected * tolerance + Decimal("0.01")


def _check_precheck_economics(precheck: PrecheckEvidence, evidence: ExecutionEvidence) -> None:
    """The broker's EUR figures must agree with the independent quote and FX."""
    rate = precheck.instrument_to_account_rate
    cost = precheck.estimated_total_cost
    cost_eur = precheck.estimated_total_cost_account
    cash_eur = precheck.estimated_cash_required
    if rate is None or cost is None or cost_eur is None or cash_eur is None:
        raise SubmissionBlocked("precheck conversion evidence is incomplete")
    eur_per_usd = Decimal("1") / evidence.fx.usd_per_eur
    if not _within(rate, eur_per_usd, FX_TOLERANCE):
        raise SubmissionBlocked("broker USD->EUR rate disagrees with validated EUR/USD FX")
    if not _within(cost_eur, cost * rate, FX_TOLERANCE):
        raise SubmissionBlocked("broker account-currency cost disagrees with its own rate")
    notional_eur = evidence.quote.price * rate
    low = notional_eur * (Decimal("1") - CASH_TOLERANCE)
    high = (notional_eur + cost_eur) * (Decimal("1") + CASH_TOLERANCE) + Decimal("0.01")
    if not low <= cash_eur <= high:
        raise SubmissionBlocked("broker EUR cash requirement disagrees with quote and FX")


def prepare_sofi_request(
    *,
    order_key: str,
    portfolio_id: str,
    evidence: ExecutionEvidence,
    precheck: PrecheckEvidence,
    account_scope: SaxoAccountScope,
    expected_account_id: str,
    portfolio_cash_usd: Decimal,
    now: datetime,
    market_verifier: MarketEvidenceVerifier | None = None,
    quote_max_age: timedelta = timedelta(minutes=2),
    requested_by: str = "sidedeck-automation",
) -> SimOrderRequest:
    """Build the only currently supported request after all local checks."""
    if not isinstance(order_key, str) or not _ORDER_KEY.fullmatch(order_key):
        raise ValueError("invalid order identity")
    if not portfolio_id or not portfolio_id.isascii():
        raise ValueError("invalid portfolio identity")
    if not valid_principal(requested_by):
        raise ValueError("invalid requesting principal")
    cutoff = _utc(now, "submission time")
    if account_scope.account_id != expected_account_id:
        raise SubmissionBlocked("verified Saxo account identity does not match expectation")
    request_payload = precheck_payload(account_scope, uic=SOFI_UIC, amount=1)
    request_sha256 = hashlib.sha256(
        json.dumps(request_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    try:
        precheck.validate_for_order(
            instrument_currency="USD", account_currency="EUR", account_id=account_scope.account_id,
            uic=SOFI_UIC, request_sha256=request_sha256, now=cutoff,
        )
    except ValueError as exc:
        raise SubmissionBlocked(str(exc)) from exc
    if not precheck.is_transport_sealed():
        raise SubmissionBlocked("precheck evidence did not come from the SIM precheck transport")
    if precheck.estimated_cash_required is None:
        raise SubmissionBlocked("EUR precheck estimate is required")
    if (evidence.quote_origin is not EvidenceOrigin.AUTHENTICATED_PROVIDER
            or evidence.fx_origin is not EvidenceOrigin.AUTHENTICATED_PROVIDER):
        raise SubmissionBlocked("authenticated quote and FX evidence are required")
    if market_verifier is None or not market_verifier.verify(evidence):
        raise SubmissionBlocked("trusted market-data attestation is required")
    # Check each observation against the submission time directly; the
    # evidence bundle's own max_age is caller-chosen and is not trusted here.
    for stamp in (evidence.observed_at, evidence.quote.market_timestamp,
                  evidence.quote.ingestion_timestamp, evidence.fx.observed_at,
                  evidence.fx.ingestion_at):
        observed = _utc(stamp, "market evidence time")
        if observed > cutoff or cutoff - observed > quote_max_age:
            raise SubmissionBlocked("market evidence is stale or future-dated")
    if not portfolio_cash_usd.is_finite() or portfolio_cash_usd < 0:
        raise ValueError("invalid portfolio cash")
    total = evidence.quote.price + evidence.total_cost_usd
    if total > Decimal("200") or total > portfolio_cash_usd:
        raise SubmissionBlocked("USD position risk limit exceeded")
    if precheck.estimated_cash_required > Decimal("200"):
        raise SubmissionBlocked("EUR broker cash limit exceeded")
    _check_precheck_economics(precheck, evidence)
    risk_material = json.dumps({
        "quote_snapshot": str(evidence.quote.snapshot_id),
        "quote_provider": evidence.quote.provider,
        "quote_price_usd": str(evidence.quote.price),
        "fx_provider": evidence.fx.provider,
        "fx_usd_per_eur": str(evidence.fx.usd_per_eur),
        "costs": str(evidence.total_cost_usd),
        "cash": str(portfolio_cash_usd),
        "precheck_sha256": precheck.response_sha256,
        "precheck_cash_eur": str(precheck.estimated_cash_required),
    }, sort_keys=True, separators=(",", ":"))
    return SimOrderRequest(
        order_key=order_key, portfolio_id=portfolio_id, account_id=account_scope.account_id,
        broker_account_key=account_scope.account_key, external_reference=order_key,
        ticker="SOFI", uic=SOFI_UIC, quantity=1,
        expected_price_usd=evidence.quote.price,
        expected_cost_usd=total, fx_eur_to_usd=evidence.fx.usd_per_eur,
        precheck_cash_eur=precheck.estimated_cash_required,
        precheck_sha256=precheck.response_sha256,
        risk_evidence_sha256=hashlib.sha256(risk_material.encode()).hexdigest(),
        prepared_at=cutoff, requested_by=requested_by,
    )


def approval_material(request: SimOrderRequest, *, authorization_id: str,
                      approver: str, expires_at: datetime) -> str:
    """Exact text the operator reviews and signs outside SideDeck."""
    return json.dumps({
        "version": APPROVAL_VERSION, "namespace": APPROVAL_NAMESPACE,
        "authorization_id": authorization_id, "approver": approver,
        "requested_by": request.requested_by, "order_key": request.order_key,
        "account_id": request.account_id, "portfolio_id": request.portfolio_id,
        "ticker": request.ticker, "uic": request.uic, "side": "Buy",
        "quantity": request.quantity, "order_type": "Market",
        "broker_payload": request.payload(),
        "broker_payload_sha256": request.broker_payload_digest(),
        "request_sha256": request.digest(),
        "risk_evidence_sha256": request.risk_evidence_sha256,
        "precheck_sha256": request.precheck_sha256,
        "expected_price_usd": str(request.expected_price_usd),
        "expected_cost_usd": str(request.expected_cost_usd),
        "precheck_cash_eur": str(request.precheck_cash_eur),
        "expires_at": _utc(expires_at, "authorization expiry").isoformat(),
    }, sort_keys=True, separators=(",", ":"))


def _require_verify_only(verifier: object | None) -> ApprovalVerifier:
    if verifier is None or not callable(getattr(verifier, "verify", None)):
        raise SubmissionBlocked("trusted approval verifier unavailable")
    if any(callable(getattr(verifier, name, None)) for name in _SELF_ATTESTING):
        raise SubmissionBlocked("a verifier that can attest cannot authorize its own request")
    return verifier  # type: ignore[return-value]


def accept_operator_approval(
    request: SimOrderRequest, *, authorization_id: str, approver: str,
    expires_at: datetime, attestation: str, verifier: ApprovalVerifier | None,
    now: datetime,
) -> ExecutionAuthorization:
    """Accept an operator-signed approval; SideDeck never creates the signature."""
    checked = _require_verify_only(verifier)
    if not authorization_id or not authorization_id.isascii() or len(authorization_id) > 100:
        raise SubmissionBlocked("operator authorization identity is required")
    if not valid_principal(approver):
        raise SubmissionBlocked("operator principal is invalid")
    if approver == request.requested_by:
        raise SubmissionBlocked("the requesting principal cannot approve its own order")
    current = _utc(now, "approval time")
    expiry = _utc(expires_at, "authorization expiry")
    if expiry <= current or expiry - current > MAX_APPROVAL_LIFETIME:
        raise SubmissionBlocked("authorization expiry is outside the allowed window")
    material = approval_material(request, authorization_id=authorization_id,
                                 approver=approver, expires_at=expiry)
    if not checked.verify(attestation, material, approver):
        raise SubmissionBlocked("operator approval signature is not valid for this order")
    return ExecutionAuthorization(
        authorization_id=authorization_id, issued_by=approver,
        requested_by=request.requested_by, order_key=request.order_key,
        account_id=request.account_id, portfolio_id=request.portfolio_id,
        ticker=request.ticker, uic=request.uic, side="Buy", quantity=request.quantity,
        order_type="Market", request_sha256=request.digest(),
        broker_payload_sha256=request.broker_payload_digest(),
        risk_evidence_sha256=request.risk_evidence_sha256, expires_at=expiry,
        attestation=attestation,
    )


def _classify_ack(response: object) -> tuple[str, str | None]:
    """ACKNOWLEDGED only on a clean order id; explicit errors are REJECTED."""
    if not isinstance(response, dict):
        return "UNKNOWN", None
    order_id = response.get("OrderId")
    clean_id = (isinstance(order_id, str) and 0 < len(order_id) <= 128
                and not any(ch.isspace() for ch in order_id))
    if clean_id and not response.get("ErrorInfo"):
        return "ACKNOWLEDGED", str(order_id)
    if response.get("ErrorInfo") and order_id in (None, ""):
        return "REJECTED", None
    # A 2xx body without a usable order id may still have created an order.
    return "UNKNOWN", None


class SaxoSimSubmitter:
    """Single-attempt durable submitter; production construction is disabled."""

    def __init__(self, db_path: str, *, transport: SimSubmitTransport | None = None,
                 network_enabled: bool = False,
                 approval_verifier: ApprovalVerifier | None = None) -> None:
        self._db_path = db_path
        self._transport = transport
        self._network_enabled = network_enabled
        self._approval_verifier = approval_verifier
        if network_enabled and transport is None:
            raise ValueError("an explicit transport is required for an enabled attempt")

    def _prepare_db(self) -> None:
        with sqlite3.connect(self._db_path) as db:
            ensure_authorization_table(db)

    def _set_status(self, order_key: str, status: str, broker_order_id: str | None = None) -> None:
        with sqlite3.connect(self._db_path) as db:
            db.execute("UPDATE saxo_execution_authorization SET status=?, "
                       "broker_order_id=COALESCE(?, broker_order_id) WHERE order_key=?",
                       (status, broker_order_id, order_key))

    def submit(self, request: SimOrderRequest, authorization: ExecutionAuthorization,
               *, now: datetime) -> str:
        """Make at most one injected attempt; network submission is opt-in only."""
        if not SIM_SUBMISSION_RELEASED:
            raise SubmissionBlocked("Saxo SIM submission is disabled: no approved release "
                                    "(P4_DECISION=NO-GO)")
        if not self._network_enabled or self._transport is None:
            raise SubmissionBlocked("Saxo SIM submission is disabled")
        verifier = _require_verify_only(self._approval_verifier)
        self._prepare_db()
        if (authorization.request_sha256 != request.digest()
                or authorization.broker_payload_sha256 != request.broker_payload_digest()
                or authorization.risk_evidence_sha256 != request.risk_evidence_sha256
                or authorization.order_key != request.order_key
                or authorization.requested_by != request.requested_by
                or authorization.account_id != request.account_id
                or authorization.portfolio_id != request.portfolio_id
                or authorization.ticker != request.ticker
                or authorization.uic != request.uic
                or authorization.quantity != request.quantity
                or authorization.side != "Buy"
                or authorization.order_type != "Market"):
            raise SubmissionBlocked("authorization is not bound to this exact order")
        if authorization.issued_by == request.requested_by:
            raise SubmissionBlocked("the requesting principal cannot approve its own order")
        current = _utc(now, "submission time")
        expiry = _utc(authorization.expires_at, "authorization expiry")
        material = approval_material(request, authorization_id=authorization.authorization_id,
                                     approver=authorization.issued_by, expires_at=expiry)
        if not verifier.verify(authorization.attestation, material, authorization.issued_by):
            raise SubmissionBlocked("authorization attestation is not trusted")
        if current > expiry:
            raise SubmissionBlocked("approval expired")
        age = current - _utc(request.prepared_at, "request preparation time")
        if age < timedelta(0) or age > MAX_REQUEST_AGE:
            raise SubmissionBlocked("order evidence is stale; prepare and approve again")
        if lifecycle_state(self._db_path, request.order_key) is not None:
            raise SubmissionBlocked("order key already has a broker lifecycle")
        try:
            with sqlite3.connect(self._db_path, isolation_level="IMMEDIATE") as db:
                row = db.execute("SELECT request_sha256, status FROM saxo_execution_authorization "
                                 "WHERE order_key=?", (request.order_key,)).fetchone()
                if row is not None:
                    if row[0] != request.digest():
                        raise SubmissionBlocked("order key was reused with different payload")
                    raise SubmissionBlocked("submission attempt already claimed")
                db.execute("INSERT INTO saxo_execution_authorization "
                           "(authorization_id, order_key, account_id, portfolio_id, request_sha256, "
                           "broker_payload_sha256, risk_evidence_sha256, attestation, issued_by, "
                           "expires_at, status, broker_order_id, quantity, requested_by) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ISSUED', NULL, ?, ?)",
                           (authorization.authorization_id, request.order_key,
                            request.account_id, request.portfolio_id, request.digest(),
                            request.broker_payload_digest(), request.risk_evidence_sha256,
                            authorization.attestation, authorization.issued_by,
                            expiry.isoformat(), str(request.quantity), request.requested_by))
        except sqlite3.IntegrityError as exc:
            raise SubmissionBlocked("authorization was already consumed") from exc
        # The claim is durable before the lifecycle and the POST. A crash from
        # here on leaves ISSUED/SUBMITTING for read-only reconciliation only.
        if not create_lifecycle(self._db_path, request.order_key):
            raise SubmissionBlocked("order key already has a broker lifecycle")
        advance_lifecycle(self._db_path, request.order_key, "SUBMITTING")
        try:
            response = self._transport.submit(request.payload())
        except Exception as exc:
            self._set_status(request.order_key, "UNKNOWN")
            advance_lifecycle(self._db_path, request.order_key, "UNKNOWN")
            raise SubmissionBlocked("submission outcome is uncertain; reconcile before retry") from exc
        outcome, broker_order_id = _classify_ack(response)
        if outcome == "ACKNOWLEDGED":
            self._set_status(request.order_key, "CONSUMED", broker_order_id)
            advance_lifecycle(self._db_path, request.order_key, "ACKNOWLEDGED",
                              broker_order_id=broker_order_id, broker_evidence=True)
            return str(broker_order_id)
        if outcome == "REJECTED":
            self._set_status(request.order_key, "REJECTED")
            advance_lifecycle(self._db_path, request.order_key, "REJECTED")
            raise SubmissionBlocked("broker rejected the order")
        self._set_status(request.order_key, "UNKNOWN")
        advance_lifecycle(self._db_path, request.order_key, "UNKNOWN")
        raise SubmissionBlocked("broker acknowledgement was malformed; outcome is uncertain")


def reconcile_uncertain_submission(
    db_path: str, order_key: str, *, account_id: str,
    activity_rows: tuple[dict[str, Any], ...],
) -> str:
    """Resolve an UNKNOWN/SUBMITTING order from read-only broker activity.

    Never submits or retries. Absence of evidence is not proof that no order
    exists, so a not-found result leaves the order UNKNOWN.
    """
    with sqlite3.connect(db_path) as db:
        ensure_authorization_table(db)
        row = db.execute("SELECT status, account_id FROM saxo_execution_authorization "
                         "WHERE order_key=?", (order_key,)).fetchone()
    if row is None:
        raise ValueError("no durable authorization for this order")
    status, bound_account = row
    if bound_account != account_id:
        raise ValueError("reconciliation account differs from the authorized account")
    state = lifecycle_state(db_path, order_key)
    if status not in {"ISSUED", "UNKNOWN"} or state is None:
        raise ValueError("order is not awaiting reconciliation")
    if state[0] == "STAGED":
        return "NOT_SUBMITTED"
    if state[0] not in {"SUBMITTING", "UNKNOWN"}:
        raise ValueError("order is not awaiting reconciliation")
    matches = [item for item in activity_rows
               if isinstance(item, dict) and item.get("ExternalReference") == order_key]
    for item in matches:
        if (item.get("AccountId") != account_id or item.get("Uic") != SOFI_UIC
                or item.get("BuySell") != "Buy"):
            raise ValueError("broker activity for this reference has a different identity")
    order_ids = {item.get("OrderId") for item in matches}
    if state[0] == "SUBMITTING":
        advance_lifecycle(db_path, order_key, "UNKNOWN")
    if not matches:
        with sqlite3.connect(db_path) as db:
            db.execute("UPDATE saxo_execution_authorization SET status='UNKNOWN' WHERE order_key=?",
                       (order_key,))
        return "NOT_FOUND_REMAINS_UNKNOWN"
    if len(order_ids) != 1:
        raise ValueError("multiple broker orders share this external reference")
    broker_order_id = order_ids.pop()
    if not isinstance(broker_order_id, str) or not broker_order_id:
        raise ValueError("broker activity has no order identity")
    if all(item.get("Status") == "Rejected" for item in matches):
        advance_lifecycle(db_path, order_key, "REJECTED", broker_evidence=True)
        with sqlite3.connect(db_path) as db:
            db.execute("UPDATE saxo_execution_authorization SET status='REJECTED', "
                       "broker_order_id=? WHERE order_key=?", (broker_order_id, order_key))
        return "REJECTED"
    advance_lifecycle(db_path, order_key, "ACKNOWLEDGED", broker_order_id=broker_order_id,
                      broker_evidence=True)
    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE saxo_execution_authorization SET status='CONSUMED', "
                   "broker_order_id=? WHERE order_key=?", (broker_order_id, order_key))
    return "ACKNOWLEDGED"
