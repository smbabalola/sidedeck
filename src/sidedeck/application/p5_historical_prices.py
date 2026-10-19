"""Strict offline, research-only historical close input for SEC annual EPS comparison."""
from __future__ import annotations

import argparse
import json
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any


class PriceEvidenceError(ValueError):
    pass


def compare_annual_eps_prices(
    fundamentals: dict[str, Any], prices: dict[str, Any]
) -> dict[str, Any]:
    if fundamentals.get("ticker") != prices.get("ticker"):
        raise PriceEvidenceError("ticker mismatch")
    if prices.get("currency") != "USD" or prices.get("price_basis") != "split_adjusted_close":
        raise PriceEvidenceError("USD split-adjusted closing prices required")
    if prices.get("corporate_actions_verified") is not True:
        raise PriceEvidenceError("corporate actions not verified")
    if not isinstance(prices.get("source"), str) or not prices["source"].startswith("https://"):
        raise PriceEvidenceError("missing HTTPS price provenance")
    try:
        cutoff = date.fromisoformat(fundamentals["as_of"])
    except (KeyError, ValueError, TypeError) as exc:
        raise PriceEvidenceError("invalid as-of") from exc
    records = prices.get("records")
    if not isinstance(records, list):
        raise PriceEvidenceError("invalid price records")
    by_date: dict[date, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise PriceEvidenceError("invalid price record")
        try:
            day = date.fromisoformat(record["date"])
            close = record["close"]
            if isinstance(close, bool) or not isinstance(close, (int, float)):
                raise PriceEvidenceError("invalid close")
            if not math.isfinite(close) or close <= 0:
                raise PriceEvidenceError("nonpositive close")
            if not record.get("source_id"):
                raise PriceEvidenceError("missing price source id")
        except (KeyError, ValueError, TypeError) as exc:
            raise PriceEvidenceError("invalid price row") from exc
        if day > cutoff or day in by_date:
            raise PriceEvidenceError("future or duplicate price date")
        by_date[day] = record
    outputs: list[dict[str, Any]] = []
    for eps in fundamentals.get("metrics", {}).get("annual_diluted_eps_ttm", []):
        try:
            filed = date.fromisoformat(eps["filing_date"])
            period = date.fromisoformat(eps["report_period"])
            value = eps["eps_ttm"]
        except (KeyError, TypeError, ValueError):
            continue
        if not period <= filed <= cutoff or not isinstance(value, (int, float)):
            continue
        if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            continue
        if eps.get("source", {}).get("filed") != eps["filing_date"]:
            continue
        # Compare only a same-day or immediately subsequent market close.
        valid_days = (filed + timedelta(days=i) for i in range(4))
        selected = next((d for d in valid_days if d in by_date), None)
        if selected is None:
            continue
        match = by_date[selected]
        outputs.append({
            "eps_period": period.isoformat(), "eps_publication_date": filed.isoformat(),
            "price_date": selected.isoformat(), "annual_eps": value,
            "split_adjusted_close": match["close"],
            "illustrative_pe": match["close"] / value,
            "eps_source": eps["source"], "price_source": match["source_id"],
            "approval": "RESEARCH_PREVIEW_ONLY",
        })
    return {
        "ticker": fundamentals["ticker"], "valuation_preview": outputs,
        "assessment": "NO_GO", "buffett_ready": False, "broker_execution": "DISABLED",
        "note": "Price adjustment and EPS share basis require independent reconciliation",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline historical EPS/price evidence comparison")
    parser.add_argument("--fundamentals", required=True)
    parser.add_argument("--prices", required=True)
    args = parser.parse_args()
    fundamentals = json.loads(Path(args.fundamentals).read_text(encoding="utf-8"))
    prices = json.loads(Path(args.prices).read_text(encoding="utf-8"))
    print(json.dumps(compare_annual_eps_prices(fundamentals, prices), indent=2))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
