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

from sidedeck.application.saxo_market_data import ExecutionEvidence
from sidedeck.infrastructure.saxo_precheck import PrecheckDecision
from sidedeck.infrastructure.saxo_account_scope import SaxoAccountScope
SIM_HOST = "https://gateway.saxobank.com/sim/openapi"
SOFI_UIC = 23241352


class SimSubmitTransport(Protocol):
    def submit(self, payload: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class OperatorApproval:
    approval_id: str
    payload_sha256: str
    expires_at: datetime


@dataclass(frozen=True)
class SimOrderRequest:
    order_key: str
    portfolio_id: str
    broker_account_key: str
    external_reference: str
    ticker: str
    uic: int
    quantity: int
    expected_price_usd: Decimal
    expected_cost_usd: Decimal
    fx_eur_to_usd: Decimal
    precheck_cash_eur: Decimal

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
        body = json.dumps(self.payload(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(body.encode("utf-8")).hexdigest()


class SubmissionBlocked(RuntimeError):
    """A safety gate prevented a broker submission attempt."""


def prepare_sofi_request(
    *,
    order_key: str,
    portfolio_id: str,
    evidence: ExecutionEvidence,
    precheck: PrecheckDecision,
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
    if precheck.result != "Ok" or not precheck.safe_to_submit:
        raise SubmissionBlocked("fresh successful broker precheck is required")
    if precheck.currency != "EUR" or precheck.estimated_cash_required is None:
        raise SubmissionBlocked("EUR precheck estimate is required")
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
    return SimOrderRequest(
        order_key=order_key, portfolio_id=portfolio_id,
        broker_account_key=account_scope.account_key, external_reference=order_key,
        ticker="SOFI", uic=SOFI_UIC, quantity=1,
        expected_price_usd=evidence.quote.price,
        expected_cost_usd=total, fx_eur_to_usd=evidence.fx.usd_per_eur,
        precheck_cash_eur=precheck.estimated_cash_required,
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
            db.execute("CREATE TABLE IF NOT EXISTS saxo_submit_claim ("
                       "order_key TEXT PRIMARY KEY, payload_sha256 TEXT NOT NULL, "
                       "status TEXT NOT NULL, broker_order_id TEXT)")

    def submit(self, request: SimOrderRequest, approval: OperatorApproval, *, now: datetime) -> str:
        """Make at most one injected attempt; network submission is opt-in only."""
        self._prepare_db()
        if not self._network_enabled or self._transport is None:
            raise SubmissionBlocked("Saxo SIM submission is disabled")
        if approval.payload_sha256 != request.digest():
            raise SubmissionBlocked("approval is not bound to this exact order payload")
        current = now.astimezone(timezone.utc) if now.tzinfo else None
        if current is None or current > approval.expires_at.astimezone(timezone.utc):
            raise SubmissionBlocked("approval expired")
        with sqlite3.connect(self._db_path, isolation_level="IMMEDIATE") as db:
            row = db.execute("SELECT payload_sha256, status FROM saxo_submit_claim "
                             "WHERE order_key=?", (request.order_key,)).fetchone()
            if row is not None:
                if row[0] != request.digest():
                    raise SubmissionBlocked("order key was reused with different payload")
                raise SubmissionBlocked("submission attempt already claimed")
            db.execute("INSERT INTO saxo_submit_claim VALUES (?, ?, 'SUBMITTING', NULL)",
                       (request.order_key, request.digest()))
        try:
            response = self._transport.submit(request.payload())
        except Exception as exc:
            with sqlite3.connect(self._db_path) as db:
                db.execute("UPDATE saxo_submit_claim SET status='UNKNOWN' WHERE order_key=?",
                           (request.order_key,))
            raise SubmissionBlocked("submission outcome is uncertain; reconcile before retry") from exc
        if not isinstance(response, dict) or response.get("Status") != "Acknowledged":
            with sqlite3.connect(self._db_path) as db:
                db.execute("UPDATE saxo_submit_claim SET status='REJECTED' WHERE order_key=?",
                           (request.order_key,))
            raise SubmissionBlocked("broker acknowledgement was rejected or malformed")
        broker_order_id = response.get("OrderId")
        if not isinstance(broker_order_id, str) or not broker_order_id:
            raise SubmissionBlocked("broker acknowledgement has no order identity")
        with sqlite3.connect(self._db_path) as db:
            db.execute("UPDATE saxo_submit_claim SET status='ACKNOWLEDGED', broker_order_id=? "
                       "WHERE order_key=?", (broker_order_id, request.order_key))
        return broker_order_id
