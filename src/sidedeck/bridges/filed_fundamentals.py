"""Strict point-in-time fundamentals snapshot adapter for upstream AI Hedge Fund.

Accept only explicitly sourced filing-dated TTM JSON snapshots. No fabricated
ratios, no latest-only metrics re-labelled as historical fundamentals.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from importlib import import_module
from typing import Any


class FundamentalsDataError(ValueError):
    pass


_ALLOWED_METRICS = frozenset({
    "market_cap", "price_to_earnings_ratio", "return_on_equity", "gross_margin",
    "operating_margin", "net_margin", "debt_to_equity", "current_ratio",
    "revenue_growth", "earnings_per_share", "book_value_per_share",
    "free_cash_flow_per_share",
})


def verified_fundamentals(path: str | Path, ticker: str, as_of: str) -> list[dict[str, Any]]:
    """Return only dated public TTM records, newest filing first.

    The caller must acquire genuine independent fundamental history with
    source URLs, reporting periods and actual public filing dates.
    """
    try:
        cutoff = date.fromisoformat(as_of)
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise FundamentalsDataError("invalid fundamentals file or as-of date") from exc
    if not isinstance(payload, dict) or set(payload) != {"ticker", "records"}:
        raise FundamentalsDataError("fundamentals root requires ticker and records")
    if payload["ticker"] != ticker or not isinstance(payload["records"], list):
        raise FundamentalsDataError("ticker mismatch or invalid records")
    accepted: list[dict[str, Any]] = []
    seen_periods: set[str] = set()
    for raw in payload["records"]:
        if not isinstance(raw, dict):
            raise FundamentalsDataError("invalid fundamentals record")
        required = {"report_period", "filing_date", "source_url", "period"}
        if not required.issubset(raw) or set(raw) - (required | _ALLOWED_METRICS):
            raise FundamentalsDataError("missing provenance or unsupported fields")
        if raw["period"] != "ttm" or not isinstance(raw["report_period"], str):
            raise FundamentalsDataError("expected TTM report periods")
        if not isinstance(raw["source_url"], str) or not raw["source_url"].startswith(
            ("https://www.sec.gov/", "https://data.sec.gov/")
        ):
            raise FundamentalsDataError("record must reference an SEC filing")
        try:
            filed = date.fromisoformat(raw["filing_date"])
            report = date.fromisoformat(raw["report_period"])
        except (ValueError, TypeError) as exc:
            raise FundamentalsDataError("invalid filing/report date") from exc
        if filed < report:
            raise FundamentalsDataError("filing date precedes reporting period")
        if filed > cutoff:
            continue
        if raw["report_period"] in seen_periods:
            raise FundamentalsDataError("duplicate reporting period")
        seen_periods.add(raw["report_period"])
        for key in _ALLOWED_METRICS & raw.keys():
            val = raw[key]
            if val is not None and (
                isinstance(val, bool) or not isinstance(val, (float, int))
            ):
                raise FundamentalsDataError("non-numeric financial metric")
        accepted.append({
            "ticker": ticker, "period": "ttm",
            **{key: val for key, val in raw.items() if key != "source_url"},
        })
    if len(accepted) < 4:
        raise FundamentalsDataError("fewer than four eligible filed TTM periods")
    accepted.sort(key=lambda item: (item["filing_date"], item["report_period"]), reverse=True)
    return accepted


class LocalFiledDataClient:
    """Only implements methods used by upstream BuffettAgent.build_snapshot."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def get_financial_metrics(
        self, ticker: str, end_date: str, period: str = "ttm", limit: int = 20
    ) -> list[Any]:
        if period != "ttm" or limit < 4:
            raise FundamentalsDataError("only TTM fundamentals supported")
        FinancialMetrics = import_module('hedge_fund.data.models').FinancialMetrics
        return [
            FinancialMetrics(**record)
            for record in verified_fundamentals(self.path, ticker, end_date)[:limit]
        ]

    def get_company_facts(self, ticker: str) -> None:
        # No as-of sector/industry source was provided. Do not invent one.
        return None
