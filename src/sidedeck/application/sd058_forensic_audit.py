"""Privacy-safe, append-only SD-058 preflight evidence.

This module never stores a broker payload. It stores field paths, JSON types and
non-sensitive three-letter currency codes only, together with durable request
and parser outcomes. SQLite's full synchronous commits and update/delete
triggers make the audit useful after a restart without making it an authority
for trading state.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sidedeck.domain.etoro_demo_orders import normalize_currency_code

# Currency values are retained only after normalization and membership in this
# explicit ISO-4217 allowlist; arbitrary three-letter response values are not evidence.
_SAFE_CURRENCY_CODES = frozenset({
    "AUD", "CAD", "CHF", "CZK", "DKK", "EUR", "GBP", "HKD", "HUF", "ILS",
    "JPY", "MXN", "NOK", "NZD", "PLN", "SEK", "SGD", "USD", "ZAR",
})
_SENSITIVE = frozenset({"authorization", "cookie", "set-cookie", "token", "secret",
                        "apikey", "api-key", "accountid", "account_id", "balance",
                        "email", "name", "phone"})
_MAX_FIELDS = 200
_MAX_DEPTH = 6


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    if type(value) is bool:
        return "bool"
    if type(value) is int:
        return "int"
    if type(value) is float:
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "other"


def _time_shape(value: str) -> str:
    """Timestamp layout without its value: digits -> 9; ISO separators, T, Z and offset signs
    kept; anything else -> ?. e.g. '9999-99-99T99:99:99.9999999' (no offset) or '...+99:99'."""
    return "".join("9" if c.isdigit() and c.isascii() else c if c in "-:.T Z+tz" else "?"
                   for c in value[:40])


def summarize_schema(payload: Any) -> dict[str, Any]:
    """Return field names/types and safe currency codes, never arbitrary values."""
    fields: list[dict[str, Any]] = []

    def visit(value: Any, path: str, depth: int) -> None:
        if len(fields) >= _MAX_FIELDS:
            return
        kind = _kind(value)
        item: dict[str, Any] = {"path": path or "$", "type": kind}
        key = path.rsplit(".", 1)[-1].lower()
        if "currency" in key and isinstance(value, str):
            normalized = normalize_currency_code(value)      # same normalizer as the parser
            if normalized is not None and normalized in _SAFE_CURRENCY_CODES:
                item["currency_code"] = normalized
                # Safe boolean only: was the raw value already the exact code?
                item["currency_exact"] = value == normalized
        if key in ("date", "timestamp", "time") and isinstance(value, str):
            item["format_shape"] = _time_shape(value)      # shape only, never the value
        fields.append(item)
        if depth >= _MAX_DEPTH:
            return
        if isinstance(value, dict):
            for name, child in value.items():
                lowered = str(name).lower().replace("-", "_")
                if lowered in _SENSITIVE or any(token in lowered for token in _SENSITIVE):
                    fields.append({"path": f"{path}.{name}" if path else str(name),
                                   "type": "redacted"})
                    continue
                visit(child, f"{path}.{name}" if path else str(name), depth + 1)
        elif isinstance(value, list):
            for index, child in enumerate(value[:20]):
                visit(child, f"{path}[{index}]", depth + 1)

    visit(payload, "", 0)
    return {"root_type": _kind(payload), "fields": fields[:_MAX_FIELDS]}


class PreflightAudit:
    """Durable append-only audit ledger for one signed pilot digest."""

    def __init__(self, path: str | Path, pilot_digest: str) -> None:
        target = Path(path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        self._path = target
        self._db = sqlite3.connect(str(target), isolation_level=None)
        self._db.execute("PRAGMA journal_mode=DELETE")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS sd058_preflight_audit ("
            "seq INTEGER PRIMARY KEY AUTOINCREMENT, recorded_at TEXT NOT NULL, "
            "pilot_digest TEXT NOT NULL, request_type TEXT NOT NULL, "
            "budget_json TEXT NOT NULL, outcome TEXT NOT NULL, "
            "error_classification TEXT, error_detail TEXT, schema_json TEXT NOT NULL)"
        )
        self._db.execute(
            "CREATE TRIGGER IF NOT EXISTS sd058_audit_no_update BEFORE UPDATE ON "
            "sd058_preflight_audit BEGIN SELECT RAISE(ABORT, 'append-only audit'); END"
        )
        self._db.execute(
            "CREATE TRIGGER IF NOT EXISTS sd058_audit_no_delete BEFORE DELETE ON "
            "sd058_preflight_audit BEGIN SELECT RAISE(ABORT, 'append-only audit'); END"
        )
        self._pilot_digest = pilot_digest

    def record(self, *, request_type: str, budget: dict[str, int], outcome: str,
               payload: Any = None, error: BaseException | None = None) -> None:
        error_class = None if error is None else type(error).__name__
        error_detail = None if error is None else str(error)[:300]
        schema = summarize_schema(payload)
        now = datetime.now(UTC).isoformat()
        self._db.execute(
            "INSERT INTO sd058_preflight_audit "
            "(recorded_at,pilot_digest,request_type,budget_json,outcome,error_classification,"
            "error_detail,schema_json) VALUES (?,?,?,?,?,?,?,?)",
            (now, self._pilot_digest, request_type, json.dumps(budget, sort_keys=True), outcome,
             error_class, error_detail, json.dumps(schema, sort_keys=True)),
        )
        self._db.commit()
        with self._path.open("r+b") as handle:
            os.fsync(handle.fileno())

    def rows(self) -> tuple[dict[str, Any], ...]:
        columns = ("seq", "recorded_at", "pilot_digest", "request_type", "budget_json",
                   "outcome", "error_classification", "error_detail", "schema_json")
        return tuple(dict(zip(columns, row)) for row in self._db.execute(
            "SELECT seq,recorded_at,pilot_digest,request_type,budget_json,outcome,"
            "error_classification,error_detail,schema_json FROM sd058_preflight_audit "
            "ORDER BY seq"))

    def close(self) -> None:
        self._db.close()
