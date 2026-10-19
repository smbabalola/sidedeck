"""SEC filing-dated diluted EPS and diluted weighted-average share observations.

These remain reported annual/YTD/quarter spans, NOT comparable TTM EPS.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any


_TAGS = {
    "diluted_eps": ("EarningsPerShareDiluted", "USD/shares"),
    "weighted_average_diluted_shares": (
        "WeightedAverageNumberOfDilutedSharesOutstanding", "shares"
    ),
}


def reported_per_share(payload: dict[str, Any], as_of: str) -> dict[str, list[dict[str, Any]]]:
    cutoff = date.fromisoformat(as_of)
    gaap = payload.get("facts", {}).get("us-gaap", {})
    result: dict[str, list[dict[str, Any]]] = {}
    for name, (tag, unit) in _TAGS.items():
        chosen: dict[tuple[str, str], dict[str, Any]] = {}
        entries = gaap.get(tag, {}).get("units", {}).get(unit, [])
        for raw in entries:
            if not isinstance(raw, dict) or raw.get("form") not in ("10-K", "10-Q"):
                continue
            try:
                start = date.fromisoformat(raw["start"])
                end = date.fromisoformat(raw["end"])
                filed = date.fromisoformat(raw["filed"])
            except (KeyError, TypeError, ValueError):
                continue
            span = (end - start).days
            if not 75 <= span <= 380 or not end <= filed <= cutoff:
                continue
            val = raw.get("val")
            if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val):
                continue
            if name == "weighted_average_diluted_shares" and val <= 0:
                continue
            if not isinstance(raw.get("accn"), str) or not raw["accn"]:
                continue
            key = (start.isoformat(), end.isoformat())
            current = chosen.get(key)
            record = {
                "start": key[0], "report_period": key[1],
                "filing_date": filed.isoformat(), "value": val,
                "source": {"accession": raw["accn"], "form": raw["form"],
                           "filed": filed.isoformat(), "start": key[0],
                           "end": key[1], "tag": tag, "unit": unit},
            }
            if current is None or record["filing_date"] < current["filing_date"]:
                chosen[key] = record
        result[name + "_reported"] = sorted(
            chosen.values(), key=lambda x: (x["report_period"], x["start"]), reverse=True
        )
    return result
