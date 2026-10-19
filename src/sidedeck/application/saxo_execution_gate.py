"""Durable, fail-closed one-off Saxo SIM order intent staging. Never submits orders."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from sidedeck.domain.contracts import AUTHORIZED_PORTFOLIOS


@dataclass(frozen=True)
class StagedOrder:
    order_key: str
    portfolio_id: str
    ticker: str
    uic: int
    quantity: int
    broker_account_id: str
    max_usd_notional: Decimal
    max_eur_cash: Decimal


def stage_one_share(
    db_path: str | Path, *, order_key: str, portfolio_id: str,
    max_usd_notional: Decimal, max_eur_cash: Decimal,
) -> bool:
    """Return True only for first committed intent. Never auto-retry an ambiguous submit."""
    if (portfolio_id not in AUTHORIZED_PORTFOLIOS or not order_key
            or len(order_key) > 100 or not order_key.isascii()
            or not all(ch.isalnum() or ch in "-_" for ch in order_key)):
        raise ValueError("invalid intent identity")
    for value in (max_usd_notional, max_eur_cash):
        if not value.is_finite() or value <= 0:
            raise ValueError("invalid spending limit")
    if max_usd_notional > Decimal("200") or max_eur_cash > Decimal("200"):
        raise ValueError("single-order cap is USD 200 / EUR 200; precheck estimate exceeds cap")
    payload = {"account": "22866064", "portfolio": portfolio_id, "ticker": "AAPL",
               "uic": 211, "quantity": 1, "max_usd_notional": str(max_usd_notional),
               "max_eur_cash": str(max_eur_cash)}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    with sqlite3.connect(str(db_path), timeout=10, isolation_level="IMMEDIATE") as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS saxo_intents (order_key TEXT PRIMARY KEY, "
                     "payload_sha256 TEXT NOT NULL, status TEXT NOT NULL CHECK(status='STAGED'))")
        row = conn.execute("SELECT payload_sha256 FROM saxo_intents WHERE order_key=?",
                           (order_key,)).fetchone()
        if row:
            if row[0] != digest:
                raise ValueError("conflicting reuse of order key")
            return False
        conn.execute("INSERT INTO saxo_intents VALUES(?, ?, 'STAGED')",
                     (order_key, digest))
    return True


def execution_gate(
    *, account_currency: str, precheck_ok: bool,
    broker_estimate_eur: Decimal | None, independent_quote_verified: bool,
    fx_conversion_verified: bool, broker_fill_reconciliation_ready: bool,
) -> tuple[bool, str]:
    """A conservative acceptance decision, NOT a live switch."""
    if account_currency != "EUR":
        return False, "account_currency_changed"
    if not precheck_ok or broker_estimate_eur is None:
        return False, "broker_precheck_missing"
    if not broker_estimate_eur.is_finite() or broker_estimate_eur <= 0:
        return False, "invalid_broker_estimate"
    if broker_estimate_eur > Decimal("200"):
        return False, "single_order_risk_cap"
    if not independent_quote_verified:
        return False, "price_validation_missing"
    if not fx_conversion_verified:
        return False, "eur_usd_reconciliation_missing"
    if not broker_fill_reconciliation_ready:
        return False, "fill_reconciliation_missing"
    return False, "sim_order_submission_not_implemented"
