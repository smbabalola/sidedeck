"""Point-in-time market-cap candidates from SEC cover shares and local closes.

Audit only. Market cap = cover-page common shares from a filing x the first
close strictly after that filing date (a same-day close may precede release).
Candidates never enter the BuffettAgent input and no numeric P/E is emitted,
matching the existing valuation-evidence rule. No network, LLM or broker.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sidedeck.application.p5_sec_bank_metrics import NET_INCOME, ttm_series
from sidedeck.application.p5_valuation_evidence import load_price_bars

PRICE_WINDOW_DAYS = 5
VALIDATION_GAPS = (
    "price feed is IEX-only, not consolidated (SIP) closing prices",
    "cover-page share count is dated before the price date",
    "share-class completeness is not independently verified",
    "split-adjusted prices are not reconciled against unadjusted share counts",
)


def _cover_shares(payload: dict[str, Any], cutoff: date) -> dict[str, list[dict[str, Any]]]:
    rows = (payload.get("facts", {}).get("dei", {})
            .get("EntityCommonStockSharesOutstanding", {}).get("units", {}).get("shares", []))
    by_accession: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("form") not in ("10-K", "10-Q"):
            continue
        try:
            filed, as_of = date.fromisoformat(row["filed"]), date.fromisoformat(row["end"])
            value, accession = row["val"], row["accn"]
        except (KeyError, TypeError, ValueError):
            continue
        if (filed > cutoff or isinstance(value, bool) or not isinstance(value, int)
                or value <= 0 or not isinstance(accession, str)):
            continue
        entry = {"filed": filed, "as_of": as_of, "value": value, "form": row["form"]}
        if entry not in by_accession.setdefault(accession, []):
            by_accession[accession].append(entry)
    return by_accession


def _report_periods(payload: dict[str, Any], cutoff: date) -> dict[str, str]:
    """Balance-sheet date of each filing: latest StockholdersEquity instant it reports."""
    rows = payload.get("facts", {}).get("us-gaap", {}).get("StockholdersEquity", {}).get(
        "units", {}).get("USD", [])
    periods: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict) or "start" in row:
            continue
        try:
            end, filed, accession = date.fromisoformat(row["end"]), date.fromisoformat(row["filed"]), row["accn"]
        except (KeyError, TypeError, ValueError):
            continue
        if end <= filed <= cutoff and isinstance(accession, str):
            if accession not in periods or end.isoformat() > periods[accession]:
                periods[accession] = end.isoformat()
    return periods


def market_cap_evidence(companyfacts: dict[str, Any], prices: dict[str, Any],
                        as_of: str, ticker: str) -> dict[str, Any]:
    cutoff = date.fromisoformat(as_of)
    bars = load_price_bars(prices, ticker, cutoff)
    shares = _cover_shares(companyfacts, cutoff)
    periods = _report_periods(companyfacts, cutoff)
    income = ttm_series(companyfacts, as_of, NET_INCOME)
    observations: list[dict[str, Any]] = []
    for accession, entries in shares.items():
        period = periods.get(accession)
        if period is None:
            continue
        filed = entries[0]["filed"]
        row: dict[str, Any] = {
            "report_period": period, "accession": accession, "filing_date": filed.isoformat(),
            "form": entries[0]["form"], "shares_outstanding": None, "shares_as_of": None,
            "price_date": None, "price_close": None, "price_source_id": None,
            "market_cap_candidate": None, "available_from": None, "included_in_input": False,
        }
        if len(entries) != 1:
            row["status"] = "MULTIPLE_SHARE_COUNTS"
        else:
            share = entries[0]
            row.update(shares_outstanding=share["value"], shares_as_of=share["as_of"].isoformat())
            price_day = next((filed + timedelta(days=i) for i in range(1, PRICE_WINDOW_DAYS + 1)
                              if filed + timedelta(days=i) in bars), None)
            if price_day is None:
                row["status"] = "PRICE_WINDOW_UNAVAILABLE"
            else:
                bar = bars[price_day]
                cap = Decimal(share["value"]) * Decimal(str(bar["close"]))
                row.update(price_date=price_day.isoformat(), price_close=bar["close"],
                           price_source_id=bar["source_id"], market_cap_candidate=str(cap),
                           available_from=price_day.isoformat(),
                           status="MARKET_CAP_CANDIDATE_UNVALIDATED")
        earnings = income.get(period)
        if earnings is None or date.fromisoformat(earnings["filing_date"]) > filed:
            row["pe_status"] = "EARNINGS_UNAVAILABLE"
        elif earnings["value"] <= 0:
            row["pe_status"] = "P_E_NOT_MEANINGFUL"
        else:
            row["pe_status"] = "P_E_VALIDATION_PENDING"
        observations.append(row)
    observations.sort(key=lambda r: r["report_period"], reverse=True)
    return {
        "ticker": ticker, "as_of": as_of,
        "definition": "cover_page_common_shares_x_first_close_after_filing_date",
        "price_feed": prices.get("feed", "unspecified"), "price_source": prices["source"],
        "candidates": sum(r["market_cap_candidate"] is not None for r in observations),
        "observations": observations, "validation_gaps": list(VALIDATION_GAPS),
        "market_cap_validated": False, "historical_pe_validated": False,
        "assessment": "NO_GO", "buffett_ready": False, "broker_execution": "DISABLED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Research-only market-cap candidate audit")
    parser.add_argument("--companyfacts", required=True)
    parser.add_argument("--prices", required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    target = Path(args.output)
    if target.exists():
        parser.error("refusing to overwrite existing report")
    report = market_cap_evidence(
        json.loads(Path(args.companyfacts).read_text(encoding="utf-8")),
        json.loads(Path(args.prices).read_text(encoding="utf-8")), args.as_of, args.ticker)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"MARKET_CAP_CANDIDATES={report['candidates']}")
    print("MARKET_CAP_VALIDATED=FALSE; BUFFETT_READY=FALSE; BROKER_EXECUTION=DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
