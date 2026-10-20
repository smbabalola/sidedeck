"""Read-only valuation evidence coverage; never certify corporate actions or P/E."""
from __future__ import annotations

import argparse
import json
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sidedeck.application.p5_historical_prices import PriceEvidenceError


def load_price_bars(prices: dict[str, Any], ticker: Any, cutoff: date) -> dict[date, dict[str, Any]]:
    """Validated daily closes by date; fails closed on any malformed or future bar."""
    if ticker != prices.get("ticker"):
        raise PriceEvidenceError("ticker mismatch")
    if prices.get("currency") != "USD" or prices.get("price_basis") != "split_adjusted_close":
        raise PriceEvidenceError("incorrect price currency/basis")
    if not isinstance(prices.get("source"), str) or not prices["source"].startswith("https://"):
        raise PriceEvidenceError("price source missing")
    raw_bars = prices.get("records")
    if not isinstance(raw_bars, list):
        raise PriceEvidenceError("invalid price records")
    bars: dict[date, dict[str, Any]] = {}
    for bar in raw_bars:
        if not isinstance(bar, dict):
            raise PriceEvidenceError("invalid bar")
        try:
            day = date.fromisoformat(bar["date"])
            close = bar["close"]
            identifier = bar["source_id"]
        except (KeyError, TypeError, ValueError) as exc:
            raise PriceEvidenceError("incomplete price evidence") from exc
        if (day > cutoff or day in bars or isinstance(close, bool)
                or not isinstance(close, (int, float)) or not math.isfinite(close)
                or close <= 0 or not isinstance(identifier, str) or not identifier):
            raise PriceEvidenceError("invalid or duplicate market-price evidence")
        bars[day] = bar
    return bars


def valuation_evidence_report(fundamentals: dict[str, Any], prices: dict[str, Any]) -> dict[str, Any]:
    cutoff = date.fromisoformat(fundamentals["as_of"])
    bars = load_price_bars(prices, fundamentals.get("ticker"), cutoff)
    rows = fundamentals.get("metrics", {}).get("annual_diluted_eps_ttm")
    if not isinstance(rows, list):
        raise PriceEvidenceError("missing annual SEC diluted EPS records")
    matches: list[dict[str, Any]] = []
    for row in rows:
        try:
            period = date.fromisoformat(row["report_period"])
            filed = date.fromisoformat(row["filing_date"])
            value = row["eps_ttm"]
            source = row["source"]
        except (KeyError, TypeError, ValueError) as exc:
            raise PriceEvidenceError("malformed SEC EPS evidence") from exc
        if (filed > cutoff or filed < period or source.get("filed") != filed.isoformat()
                or source.get("unit") != "USD/shares" or not source.get("accession")
                or isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value)):
            raise PriceEvidenceError("unverified or future SEC EPS evidence")
        price_day: date | None = next((filed + timedelta(days=i) for i in range(4)
                                      if filed + timedelta(days=i) in bars), None)
        if price_day is None:
            status = "PRICE_WINDOW_UNAVAILABLE"
        elif value <= 0:
            status = "P_E_NOT_MEANINGFUL"
        else:
            status = "P_E_VALIDATION_PENDING"
        evidence = {
            "eps_period": period.isoformat(), "eps_filed": filed.isoformat(),
            "eps": value, "eps_source": source, "status": status,
            "price_date": price_day.isoformat() if price_day else None,
            "price_close": bars[price_day]["close"] if price_day else None,
            "price_source_id": bars[price_day]["source_id"] if price_day else None,
        }
        # Do not produce a numeric P/E until independently attested share
        # adjustment, release timing, and price provenance are available.
        matches.append(evidence)
    matches.sort(key=lambda entry: entry["eps_period"], reverse=True)
    return {
        "ticker": fundamentals["ticker"], "as_of": cutoff.isoformat(),
        "price_feed": prices.get("feed", "unspecified"),
        "price_source": prices["source"],
        "price_records": len(bars), "annual_eps_records": len(matches),
        "aligned_price_records": sum(row["price_date"] is not None for row in matches),
        "corporate_actions_verified": False,
        "eps_price_share_basis_verified": False,
        "release_timing_verified": False,
        "historical_pe_validated": False,
        "assessment": "NO_GO", "buffett_ready": False,
        "broker_execution": "DISABLED", "matches": matches,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Research-only annual EPS/price evidence report")
    parser.add_argument("--fundamentals", required=True)
    parser.add_argument("--prices", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    target = Path(args.output)
    if target.exists():
        parser.error("refusing to overwrite existing report")
    f = json.loads(Path(args.fundamentals).read_text(encoding="utf-8"))
    p = json.loads(Path(args.prices).read_text(encoding="utf-8"))
    report = valuation_evidence_report(f, p)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("VALUATION_EVIDENCE_REPORT=SAVED")
    print("ALIGNED_PRICE_RECORDS=" + str(report["aligned_price_records"]))
    print("HISTORICAL_PE_VALIDATED=FALSE; BUFFETT_READY=FALSE; BROKER_EXECUTION=DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
