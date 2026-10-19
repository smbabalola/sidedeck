"""Controlled Saxo SIM submission boundary.

This module constructs and validates one SOFI share request but is disabled by
default. A caller must inject a transport and explicitly enable a one-time
attempt; the normal SideDeck application never does so.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Protocol

from sidedeck.application.saxo_market_data import EvidenceOrigin, ExecutionEvidence
from sidedeck.infrastructure.saxo_precheck import PrecheckEvidence
from sidedeck.infrastructure.saxo_account_scope import SaxoAccountScope
SIM_HOST = "https://gateway.saxobank.com/sim/openapi"
SOFI_UIC = 23241352


class SimSubmitTransport(Protocol):
    def submit(self, payload: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ExecutionAuthorization:
    """One operator authorization bound to every material order fact."""

    authorization_id: str
    issued_by: str
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
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def broker_payload_digest(self) -> str:
        body = json.dumps(self.payload(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(body.encode("utf-8")).hexdigest()


class SubmissionBlocked(RuntimeError):
    """A safety gate prevented a broker submission attempt."""


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
    quote_max_age: timedelta = timedelta(minutes=2),
) -> SimOrderRequest:
    """Build the only currently supported request after all local checks."""
    if not order_key or not order_key.isascii() or len(order_key) > 100:
        raise ValueError("invalid order identity")
    if not portfolio_id or not portfolio_id.isascii():
        raise ValueError("invalid portfolio identity")
    if account_scope.account_id != expected_account_id:
        raise SubmissionBlocked("verified Saxo account identity does not match expectation")
    try:
        precheck.validate_for_order(instrument_currency="USD", account_currency="EUR")
    except ValueError as exc:
        raise SubmissionBlocked(str(exc)) from exc
    if precheck.estimated_cash_required is None:
        raise SubmissionBlocked("EUR precheck estimate is required")
    if (evidence.quote_origin is not EvidenceOrigin.AUTHENTICATED_PROVIDER
            or evidence.fx_origin is not EvidenceOrigin.AUTHENTICATED_PROVIDER):
        raise SubmissionBlocked("authenticated quote and FX evidence are required")
    cutoff = now.astimezone(timezone.utc) if now.tzinfo else None
    if cutoff is None:
        raise ValueError("submission time must be timezone-aware")
    if evidence.observed_at > cutoff or cutoff - evidence.observed_at > quote_max_age:
        raise SubmissionBlocked("market evidence is stale or future-dated")
    if not portfolio_cash_usd.is_finite() or portfolio_cash_usd < 0:
        raise ValueError("invalid portfolio cash")
    total = evidence.quote.price + evidence.total_cost_usd
    if total > Decimal("200") or total > portfolio_cash_usd:
        raise SubmissionBlocked("USD position risk limit exceeded")
    if precheck.estimated_cash_required > Decimal("200"):
        raise SubmissionBlocked("EUR broker cash limit exceeded")
    risk_material = json.dumps({
        "quote_snapshot": str(evidence.quote.snapshot_id),
        "quote_provider": evidence.quote.provider,
        "fx_provider": evidence.fx.provider,
        "costs": str(evidence.total_cost_usd),
        "cash": str(portfolio_cash_usd),
    }, sort_keys=True, separators=(",", ":"))
    return SimOrderRequest(
        order_key=order_key, portfolio_id=portfolio_id, account_id=account_scope.account_id,
        broker_account_key=account_scope.account_key, external_reference=order_key,
        ticker="SOFI", uic=SOFI_UIC, quantity=1,
        expected_price_usd=evidence.quote.price,
        expected_cost_usd=total, fx_eur_to_usd=evidence.fx.usd_per_eur,
        precheck_cash_eur=precheck.estimated_cash_required,
        precheck_sha256=hashlib.sha256(
            json.dumps(precheck.__dict__, sort_keys=True, default=str).encode()).hexdigest(),
        risk_evidence_sha256=hashlib.sha256(risk_material.encode()).hexdigest(),
    )


def authorize_execution(request: SimOrderRequest, *, authorization_id: str,
                        issued_by: str, expires_at: datetime) -> ExecutionAuthorization:
    """Create a typed authorization; no boolean can stand in for this record."""
    if not authorization_id or not issued_by:
        raise ValueError("operator authorization identity is required")
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        raise ValueError("authorization expiry must be timezone-aware")
    return ExecutionAuthorization(
        authorization_id=authorization_id, issued_by=issued_by,
        account_id=request.account_id, portfolio_id=request.portfolio_id,
        ticker=request.ticker, uic=request.uic, side="Buy", quantity=request.quantity,
        order_type="Market", request_sha256=request.digest(),
        broker_payload_sha256=request.broker_payload_digest(),
        risk_evidence_sha256=request.risk_evidence_sha256, expires_at=expires_at,
    )


class SaxoSimSubmitter:
    """Single-attempt durable submitter; production construction is disabled."""

    def __init__(self, db_path: str, *, transport: SimSubmitTransport | None = None,
                 network_enabled: bool = False) -> None:
        self._db_path = db_path
        self._transport = transport
        self._network_enabled = network_enabled
        if network_enabled and transport is None:
            raise ValueError("an explicit transport is required for an enabled attempt")

    def _prepare_db(self) -> None:
        with sqlite3.connect(self._db_path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS saxo_submit_claim_v2 ("
                       "order_key TEXT PRIMARY KEY, authorization_id TEXT UNIQUE NOT NULL, "
                       "account_id TEXT NOT NULL, portfolio_id TEXT NOT NULL, "
                       "payload_sha256 TEXT NOT NULL, status TEXT NOT NULL, "
                       "broker_order_id TEXT)")

    def submit(self, request: SimOrderRequest, authorization: ExecutionAuthorization,
               *, now: datetime) -> str:
        """Make at most one injected attempt; network submission is opt-in only."""
        self._prepare_db()
        if not self._network_enabled or self._transport is None:
            raise SubmissionBlocked("Saxo SIM submission is disabled")
        if (authorization.request_sha256 != request.digest()
                or authorization.broker_payload_sha256 != request.broker_payload_digest()
                or authorization.risk_evidence_sha256 != request.risk_evidence_sha256
                or authorization.account_id != request.account_id
                or authorization.portfolio_id != request.portfolio_id
                or authorization.ticker != request.ticker
                or authorization.uic != request.uic
                or authorization.quantity != request.quantity
                or authorization.side != "Buy"
                or authorization.order_type != "Market"):
            raise SubmissionBlocked("authorization is not bound to this exact order")
        current = now.astimezone(timezone.utc) if now.tzinfo else None
        if current is None or current > authorization.expires_at.astimezone(timezone.utc):
            raise SubmissionBlocked("approval expired")
        with sqlite3.connect(self._db_path, isolation_level="IMMEDIATE") as db:
            row = db.execute("SELECT payload_sha256, status FROM saxo_submit_claim_v2 "
                             "WHERE order_key=?", (request.order_key,)).fetchone()
            if row is not None:
                if row[0] != request.digest():
                    raise SubmissionBlocked("order key was reused with different payload")
                raise SubmissionBlocked("submission attempt already claimed")
            db.execute("INSERT INTO saxo_submit_claim_v2 VALUES (?, ?, ?, ?, ?, 'SUBMITTING', NULL)",
                       (request.order_key, authorization.authorization_id,
                        request.account_id, request.portfolio_id, request.digest()))
        try:
            response = self._transport.submit(request.payload())
        except Exception as exc:
            with sqlite3.connect(self._db_path) as db:
                db.execute("UPDATE saxo_submit_claim_v2 SET status='UNKNOWN' WHERE order_key=?",
                           (request.order_key,))
            raise SubmissionBlocked("submission outcome is uncertain; reconcile before retry") from exc
        if (not isinstance(response, dict) or response.get("ErrorInfo")
                or not isinstance(response.get("OrderId"), str)
                or not response["OrderId"]):
            with sqlite3.connect(self._db_path) as db:
                db.execute("UPDATE saxo_submit_claim_v2 SET status='REJECTED' WHERE order_key=?",
                           (request.order_key,))
            raise SubmissionBlocked("broker acknowledgement was rejected or malformed")
        broker_order_id = response.get("OrderId")
        if not isinstance(broker_order_id, str) or not broker_order_id:
            raise SubmissionBlocked("broker acknowledgement has no order identity")
        with sqlite3.connect(self._db_path) as db:
            db.execute("UPDATE saxo_submit_claim_v2 SET status='ACKNOWLEDGED', broker_order_id=? "
                       "WHERE order_key=?", (broker_order_id, request.order_key))
        return broker_order_id
