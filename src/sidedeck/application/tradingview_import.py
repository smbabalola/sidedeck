"""Offline TradingView execution CSV ingestion. No broker access or ledger mutation.

The importer accepts an explicit normalized CSV contract, not arbitrary order exports.
A submitted/working order is never treated as a fill.
"""
from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sidedeck.domain.contracts import AUTHORIZED_PORTFOLIOS

REQUIRED = frozenset({"execution_id", "timestamp", "symbol", "side", "quantity", "price", "status"})
_ALLOWED_STATUS = frozenset({"filled", "executed"})
_MAX_BYTES = 5_000_000
_MAX_ROWS = 50_000


@dataclass(frozen=True)
class TradingViewFill:
    execution_id: str
    occurred_at: datetime
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    portfolio_id: str
    source_row: int


@dataclass(frozen=True)
class ImportReport:
    fills: tuple[TradingViewFill, ...]
    ignored_unfilled: int
    duplicate_rows: int
    source_sha256: str


def import_tradingview_csv(path: str | Path, *, portfolio_id: str) -> ImportReport:
    """Parse a verified normalized execution export, never send orders or write ledgers.

    Requires user-reviewed CSV mapping: execution_id,timestamp,symbol,side,
    quantity,price,status[,fee]. timestamp MUST be timezone-qualified ISO-8601.
    Only filled executions qualify; accepted/working/cancelled remain excluded.
    """
    if portfolio_id not in AUTHORIZED_PORTFOLIOS:
        raise ValueError("portfolio not authorized")
    raw = Path(path).read_bytes()
    if len(raw) > _MAX_BYTES:
        raise ValueError("CSV exceeds safe size limit")
    try:
        source = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV must use UTF-8") from exc
    reader = csv.DictReader(io.StringIO(source, newline=""), strict=True)
    if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError("CSV headers are missing or duplicated")
    if not REQUIRED.issubset(reader.fieldnames):
        raise ValueError("CSV requires normalized execution headers; map source export first")
    fills: list[TradingViewFill] = []
    fingerprints: dict[str, tuple[str, ...]] = {}
    ignored = 0
    duplicates = 0
    try:
        for row_num, row in enumerate(reader, start=2):
            if row_num > _MAX_ROWS + 1:
                raise ValueError("too many CSV rows")
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f"malformed CSV row {row_num}")
            status = row["status"].strip().lower()
            if status not in _ALLOWED_STATUS:
                if status in {"working", "open", "pending", "cancelled", "canceled", "rejected", "inactive"}:
                    ignored += 1
                    continue
                raise ValueError(f"unknown execution status at row {row_num}")
            execution_id = row["execution_id"].strip()
            symbol = row["symbol"].strip().upper()
            side = row["side"].strip().upper()
            if not execution_id or not symbol or not symbol.isascii() or not symbol.replace(".", "").isalnum():
                raise ValueError(f"invalid execution identity or symbol at row {row_num}")
            if side not in {"BUY", "SELL"}:
                raise ValueError(f"invalid side at row {row_num}")
            try:
                at = datetime.fromisoformat(row["timestamp"].strip().replace("Z", "+00:00"))
                quantity = Decimal(row["quantity"].strip())
                price = Decimal(row["price"].strip())
                fee = Decimal((row.get("fee") or "0").strip())
            except (InvalidOperation, ValueError) as exc:
                raise ValueError(f"invalid execution fields at row {row_num}") from exc
            if at.tzinfo is None or at.utcoffset() is None:
                raise ValueError(f"timestamp requires timezone at row {row_num}")
            if not all(d.is_finite() for d in (quantity, price, fee)):
                raise ValueError(f"nonfinite monetary amount at row {row_num}")
            if quantity <= 0 or price <= 0 or fee < 0:
                raise ValueError(f"invalid amount at row {row_num}")
            fingerprint = (at.astimezone(timezone.utc).isoformat(), symbol, side,
                           str(quantity), str(price), str(fee))
            previous = fingerprints.get(execution_id)
            if previous is not None:
                if previous != fingerprint:
                    raise ValueError(f"conflicting execution ID at row {row_num}")
                duplicates += 1
                continue
            fingerprints[execution_id] = fingerprint
            fills.append(TradingViewFill(execution_id, at, symbol, side, quantity,
                                         price, fee, portfolio_id, row_num))
    except csv.Error as exc:
        raise ValueError("malformed CSV") from exc
    return ImportReport(tuple(fills), ignored, duplicates, hashlib.sha256(raw).hexdigest())
