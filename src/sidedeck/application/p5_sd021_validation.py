"""Offline admission and reporting for the authorized SD-021 bundles."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sidedeck.application.m2_market_data import MarketDataError, normalize_daily_bars
from sidedeck.application.us_equity_calendar import validate_session_coverage

_START = date(2021, 10, 21)
_END = date(2026, 10, 20)
_EXCHANGES = {"SPY": "NYSE_ARCA", "QQQ": "NASDAQ", "MSFT": "NASDAQ"}


def validate_bundle(path: str | Path, *, ticker: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate a local Alpaca bundle and return an admitted payload/report."""
    source_path = Path(path)
    raw_bytes = source_path.read_bytes()
    source_digest = hashlib.sha256(raw_bytes).hexdigest()
    payload = json.loads(raw_bytes)
    if not isinstance(payload, dict):
        raise MarketDataError("historical bundle must be an object")
    required = {
        "ticker": ticker, "instrument_id": "US:" + ticker, "feed": "sip",
        "adjustment": "split", "currency": "USD", "session": "REGULAR",
        "research_only": True, "source_identity": "alpaca_market_data_api",
    }
    mismatches = [key for key, expected in required.items() if payload.get(key) != expected]
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise MarketDataError("historical bundle records are required")
    observed = [date.fromisoformat(str(row["date"])) for row in records if isinstance(row, dict) and "date" in row]
    if len(observed) != len(records):
        raise MarketDataError("historical bundle record dates are invalid")
    coverage = validate_session_coverage(observed, start=_START, end=_END)
    corrected = dict(payload)
    metadata_corrections: list[str] = []
    expected_exchange = _EXCHANGES[ticker]
    if payload.get("exchange") != expected_exchange:
        metadata_corrections.append("EXCHANGE_IDENTITY_NORMALIZED_FROM_RETRIEVAL_METADATA")
    corrected["exchange"] = expected_exchange
    corrected["adjustment"] = "split_adjusted"
    cutoff = datetime(2026, 10, 20, 23, 59, 59, tzinfo=timezone.utc)
    bars, normalization = normalize_daily_bars(corrected, cutoff=cutoff)
    fatal = list(mismatches)
    if coverage.status != "VALIDATED":
        fatal.append("SESSION_COVERAGE")
    if normalization["earliest"] != _START.isoformat() or normalization["latest"] != _END.isoformat():
        fatal.append("DATE_RANGE")
    if len(bars) != len(coverage.expected):
        fatal.append("OBSERVATION_COUNT")
    status = "ADMITTED_RESEARCH_ONLY" if not fatal else "REJECTED"
    admitted = dict(corrected)
    admitted["source_bundle_sha256"] = source_digest
    admitted["admission_status"] = status
    admitted["admission_metadata_corrections"] = metadata_corrections
    admitted["broker_execution"] = "DISABLED"
    report = {
        "schema_version": 1, "ticker": ticker, "instrument_id": "US:" + ticker,
        "source_bundle": str(source_path), "source_bundle_sha256": source_digest,
        "source": payload.get("source"), "source_identity": payload.get("source_identity"),
        "feed": payload.get("feed"), "adjustment": "split_adjusted", "currency": payload.get("currency"),
        "exchange": expected_exchange, "session": payload.get("session"),
        "requested_start": _START.isoformat(), "requested_end": _END.isoformat(),
        "actual_start": normalization["earliest"], "actual_end": normalization["latest"],
        "observations": len(bars), "expected_sessions": len(coverage.expected),
        "session_status": coverage.status, "calendar_source": coverage.calendar_source,
        "missing_sessions": [day.isoformat() for day in coverage.missing],
        "unexpected_sessions": [day.isoformat() for day in coverage.unexpected],
        "normalization_issues": normalization["issues"],
        "metadata_corrections": metadata_corrections, "fatal_issues": fatal,
        "http_statuses": payload.get("http_statuses"), "request_count": payload.get("request_count"),
        "pagination_pages": payload.get("pagination_pages"), "status": status,
        "corporate_actions": "PENDING_INDEPENDENT_RECONCILIATION",
        "dividend_basis": "SPLIT_ADJUSTED_PRICE_NOT_TOTAL_RETURN",
        "broker_execution": "DISABLED",
    }
    return admitted, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an offline SD-021 Alpaca SIP bundle")
    parser.add_argument("--ticker", required=True, choices=sorted(_EXCHANGES))
    parser.add_argument("--input", required=True)
    parser.add_argument("--admitted-output", required=True)
    parser.add_argument("--report-output", required=True)
    args = parser.parse_args()
    admitted, report = validate_bundle(args.input, ticker=args.ticker)
    Path(args.admitted_output).write_text(json.dumps(admitted, indent=2), encoding="utf-8")
    Path(args.report_output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"{args.ticker}_ADMISSION={report['status']}; OBSERVATIONS={report['observations']}")
    return 0 if report["status"] == "ADMITTED_RESEARCH_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
