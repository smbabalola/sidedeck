"""Offline corporate-action and benchmark audit for the SD-021 bundles.

This module never fetches data.  It independently derives a close-to-close,
price-only benchmark from the saved bars and keeps dividend/total-return
claims separate from split-adjusted close evidence.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from sidedeck.application.p5_msft_corporate_actions import verify_msft_window


def _price_only_benchmark(records: list[dict[str, Any]]) -> dict[str, str]:
    closes = [Decimal(str(row["close"])) for row in records]
    if len(closes) < 2 or any(value <= 0 for value in closes):
        raise ValueError("at least two positive close observations are required")
    ending_equity = closes[-1] / closes[0]
    running = Decimal("1")
    peak = running
    max_drawdown = Decimal("0")
    for previous, current in zip(closes, closes[1:]):
        running *= current / previous
        peak = max(peak, running)
        max_drawdown = max(max_drawdown, (peak - running) / peak)
    return {
        "starting_close": str(closes[0]),
        "ending_close": str(closes[-1]),
        "ending_equity": f"{ending_equity:.12f}",
        "return": f"{(ending_equity - 1):.12f}",
        "max_drawdown": f"{max_drawdown:.12f}",
    }


def _action_json(action: Any) -> dict[str, Any]:
    return {
        "kind": action.kind,
        "effective_date": action.effective_date.isoformat(),
        "ratio": action.ratio,
        "amount_per_share": str(action.amount_per_share) if action.amount_per_share is not None else None,
        "source_url": action.source_url,
    }


def audit_bundle(path: str | Path, *, research_path: str | Path | None = None) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("bundle must be an object")
    ticker = str(payload.get("ticker"))
    records = payload.get("records")
    if not isinstance(records, list) or not all(isinstance(row, dict) for row in records):
        raise ValueError("bundle records must be objects")
    typed_records = [row for row in records if isinstance(row, dict)]
    dates = [date.fromisoformat(str(row["date"])) for row in typed_records]
    if dates != sorted(dates) or len(set(dates)) != len(dates):
        raise ValueError("bundle dates must be sorted and unique")

    benchmark = _price_only_benchmark(typed_records)
    research_match: dict[str, Any] = {
        "status": "NOT_ASSESSED", "ending_equity_delta": None, "drawdown_delta": None,
    }
    if research_path is not None:
        research = json.loads(Path(research_path).read_text(encoding="utf-8"))
        reported = research.get("benchmark", {}) if isinstance(research, dict) else {}
        if not reported and isinstance(research, dict):
            strategies = research.get("strategies", {})
            if isinstance(strategies, dict) and strategies:
                first_strategy = next(iter(strategies.values()))
                if isinstance(first_strategy, dict):
                    reported = {"ending_equity": first_strategy.get("benchmark_ending_equity")}
        reported_equity = reported.get("ending_equity")
        reported_drawdown = reported.get("max_drawdown")
        if reported_equity is not None:
            equity_delta = abs(Decimal(str(reported_equity)) - Decimal(benchmark["ending_equity"]))
            drawdown_delta = (abs(Decimal(str(reported_drawdown)) - Decimal(benchmark["max_drawdown"]))
                              if reported_drawdown is not None else None)
            research_match = {
                "status": "RECONCILED" if equity_delta < Decimal("0.000000001") and (drawdown_delta is None or drawdown_delta < Decimal("0.000000001")) else "MISMATCH",
                "ending_equity_delta": f"{equity_delta:.12f}",
                "drawdown_delta": f"{drawdown_delta:.12f}" if drawdown_delta is not None else None,
            }

    if ticker == "MSFT":
        corporate_actions = verify_msft_window(dates[0], dates[-1])
        action_status = "VERIFIED" if corporate_actions["status"] == "VERIFIED" else "REVIEW_REQUIRED"
        action_basis = "MSFT official split/dividend evidence recorded locally"
        dividends = cast(tuple[Any, ...], corporate_actions["dividends_in_window"])
        corporate_actions = {
            **corporate_actions,
            "latest_split": _action_json(corporate_actions["latest_split"]),
            "dividends_in_window": [_action_json(action) for action in dividends],
        }
    else:
        corporate_actions = {"status": "NOT_ASSESSED", "reason": "ETF split/distribution evidence is not in the approved local record"}
        action_status = "NOT_ASSESSED"
        action_basis = "No ETF corporate-action or distribution source was used"

    return {
        "schema_version": 1,
        "ticker": ticker,
        "instrument_id": payload.get("instrument_id"),
        "source_identity": payload.get("source_identity"),
        "feed": payload.get("feed"),
        "adjustment": payload.get("price_basis"),
        "date_range": {"start": dates[0].isoformat(), "end": dates[-1].isoformat()},
        "observations": len(typed_records),
        "benchmark": {
            **benchmark,
            "convention": "close_to_close_price_only_no_dividend_reinvestment",
            "total_return": "UNAVAILABLE",
        },
        "research_benchmark_reconciliation": research_match,
        "corporate_actions": corporate_actions,
        "corporate_action_status": action_status,
        "corporate_action_basis": action_basis,
        "dividend_treatment": "EXCLUDED_FROM_CLOSE; NOT_TOTAL_RETURN",
        "valuation_admission": "BLOCKED_EXTERNAL",
        "broker_execution": "DISABLED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit SD-021 corporate-action and benchmark conventions offline")
    parser.add_argument("--ticker", required=True, choices=("SPY", "QQQ", "MSFT"))
    parser.add_argument("--input", required=True)
    parser.add_argument("--research")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = audit_bundle(args.input, research_path=args.research)
    if result["ticker"] != args.ticker:
        raise SystemExit("ticker does not match input bundle")
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"{args.ticker}_BENCHMARK={result['research_benchmark_reconciliation']['status']}; CORPORATE_ACTIONS={result['corporate_action_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
