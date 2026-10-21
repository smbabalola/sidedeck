"""Fail-closed parser for offline ETF split/distribution evidence.

The parser validates supplied evidence only. It has no transport and rejects
authenticated or paid-source labels so a fixture cannot silently become a
total-return claim.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

_TICKERS = frozenset(("SPY", "QQQ"))
_SOURCE_CLASSES = frozenset(("public", "owner_supplied_licensed"))
_KINDS = frozenset(("split", "distribution"))


def validate_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    ticker = payload.get("ticker")
    if ticker not in _TICKERS:
        raise ValueError("ETF evidence must identify SPY or QQQ")
    source_class = payload.get("source_class")
    if source_class not in _SOURCE_CLASSES:
        raise ValueError("source must be public or owner_supplied_licensed")
    source_url = payload.get("source_url")
    if not isinstance(source_url, str) or not source_url.startswith(("https://", "file://")):
        raise ValueError("source URL or owner-supplied file reference is required")
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("evidence records are required")
    seen: set[tuple[str, str]] = set()
    normalized: list[dict[str, Any]] = []
    for raw in records:
        if not isinstance(raw, dict) or raw.get("kind") not in _KINDS:
            raise ValueError("record kind must be split or distribution")
        kind = str(raw["kind"])
        effective_date = date.fromisoformat(str(raw["effective_date"]))
        key = (kind, effective_date.isoformat())
        if key in seen:
            raise ValueError("duplicate corporate-action record")
        seen.add(key)
        payment_date = raw.get("payment_date")
        if kind == "distribution":
            amount = Decimal(str(raw.get("amount_per_share", "0")))
            if amount <= 0:
                raise ValueError("distribution amount must be positive")
            if payment_date is not None and date.fromisoformat(str(payment_date)) < effective_date:
                raise ValueError("payment date cannot precede ex-date")
        else:
            amount = None
        ratio = raw.get("ratio")
        if kind == "split" and (not isinstance(ratio, str) or ":" not in ratio):
            raise ValueError("split ratio is required")
        normalized.append({
            "kind": kind,
            "effective_date": effective_date.isoformat(),
            "payment_date": str(payment_date) if payment_date is not None else None,
            "amount_per_share": str(amount) if amount is not None else None,
            "ratio": ratio,
        })
    normalized.sort(key=lambda row: (row["effective_date"], row["kind"]))
    return {
        "schema_version": 1,
        "ticker": ticker,
        "source_class": source_class,
        "source_url": source_url,
        "records": normalized,
        "price_only_benchmark": "SUPPORTED",
        "total_return_benchmark": "AVAILABLE_IF_DISTRIBUTIONS_AND_REINVESTMENT_ARE_COMPLETE",
        "corporate_actions_status": "VERIFIED" if normalized else "NOT_ASSESSED",
        "broker_execution": "DISABLED",
    }
