"""Conservative SEC quarterly evidence -> local FinancialMetrics file and audit.

Maps only source-backed ROE. Passing schema checks does not establish agent
scoring readiness. No missing financial metrics are guessed or zero-filled.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from datetime import date
from pathlib import Path
from typing import Any


class BuffettMappingUnavailable(ValueError):
    pass


def _annual_eps_by_period(preview: dict[str, Any], ticker: str, cutoff: date) -> dict[str, dict[str, Any]]:
    """Only directly reported full-year diluted EPS, never sum quarterly EPS."""
    if preview.get("ticker") != ticker:
        raise BuffettMappingUnavailable("EPS preview ticker mismatch")
    metrics = preview.get("metrics")
    if not isinstance(metrics, dict) or not isinstance(metrics.get("annual_diluted_eps_ttm"), list):
        raise BuffettMappingUnavailable("missing directly filed annual EPS series")
    found: dict[str, dict[str, Any]] = {}
    for row in metrics["annual_diluted_eps_ttm"]:
        try:
            report = date.fromisoformat(row["report_period"])
            filed = date.fromisoformat(row["filing_date"])
            start = date.fromisoformat(row["start"])
            value = row["eps_ttm"]
            source = row["source"]
            source_filed = date.fromisoformat(source["filed"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BuffettMappingUnavailable("invalid annual EPS provenance") from exc
        if (not 330 <= (report - start).days <= 380
                or filed < report or source_filed != filed or filed > cutoff
                or isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or row.get("method") != "directly_filed_full_year_eps_no_quarterly_aggregation"
                or source.get("tag") != "EarningsPerShareDiluted"
                or source.get("unit") != "USD/shares"
                or source.get("start") != row["start"]
                or source.get("end") != row["report_period"]
                or not isinstance(source.get("accession"), str)
                or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", source["accession"])
                or row["report_period"] in found):
            raise BuffettMappingUnavailable("invalid or duplicated annual EPS evidence")
        found[row["report_period"]] = row
    return found


def map_sec_quarterly_to_buffett(
    coverage: dict[str, Any], cik: int, annual_eps_preview: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    ticker = coverage.get("ticker")
    if not isinstance(ticker, str) or not ticker or not isinstance(cik, int) or isinstance(cik, bool) or cik <= 0:
        raise BuffettMappingUnavailable("invalid ticker or CIK")
    cutoff = date.fromisoformat(coverage["as_of"])
    eps_by_period = (_annual_eps_by_period(annual_eps_preview, ticker, cutoff)
                     if annual_eps_preview is not None else {})
    periods = coverage.get("periods")
    if not isinstance(periods, list) or coverage.get("complete_period_count") != len(periods):
        raise BuffettMappingUnavailable("inconsistent coverage")
    output: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    seen: set[str] = set()
    for period in periods:
        try:
            report = date.fromisoformat(period["report_period"])
            available = date.fromisoformat(period["available_from"])
            roe = period["metrics"]["return_on_equity_preview"]
            filed = date.fromisoformat(roe["filing_date"])
            value = roe["value"]
            sources = roe["sources"]
        except (KeyError, TypeError, ValueError) as exc:
            raise BuffettMappingUnavailable("incomplete ROE evidence") from exc
        if (not report <= filed <= available <= cutoff or report.isoformat() in seen
                or isinstance(value, bool) or not isinstance(value, (float, int))
                or not math.isfinite(value) or not isinstance(sources, list) or len(sources) < 3):
            raise BuffettMappingUnavailable("invalid or duplicate ROE period")
        valid_sources = []
        for source in sources:
            if not isinstance(source, dict):
                raise BuffettMappingUnavailable("invalid SEC source")
            accession = source.get("accession")
            if not isinstance(accession, str) or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
                raise BuffettMappingUnavailable("invalid SEC accession")
            source_filed = date.fromisoformat(source["filed"])
            if source_filed > available:
                raise BuffettMappingUnavailable("SEC source unavailable at observation date")
            valid_sources.append(source)
        # Archive index addresses are source locators; independently verifying
        # the filing contents remains a separate gate.
        representative = valid_sources[0]["accession"]
        accession_path = representative.replace("-", "")
        source_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_path}/"
        record = {"report_period": report.isoformat(), "filing_date": available.isoformat(),
                  "period": "ttm", "source_url": source_url, "return_on_equity": value}
        mapped_fields = ["return_on_equity"]
        eps_source = None
        annual = eps_by_period.get(report.isoformat())
        if annual is not None:
            annual_filed = date.fromisoformat(annual["filing_date"])
            record["earnings_per_share"] = annual["eps_ttm"]
            record["filing_date"] = max(available, annual_filed).isoformat()
            mapped_fields.append("earnings_per_share")
            eps_source = annual["source"]
        output.append(record)
        evidence.append({"report_period": report.isoformat(), "available_from": available.isoformat(),
                         "mapped_fields": mapped_fields,
                         "annual_eps_source": eps_source,
                         "source_components": valid_sources,
                         "unmapped": ["debt_to_equity", "gross_margin", "operating_margin",
                                      "net_margin", "revenue_growth",
                                      "free_cash_flow_per_share", "market_cap",
                                      "price_to_earnings_ratio"]})
        seen.add(report.isoformat())
    if len(output) < 4:
        raise BuffettMappingUnavailable("insufficient filed ROE observations")
    return ({"ticker": ticker, "records": output}, {
        "ticker": ticker, "cik": cik, "as_of": cutoff.isoformat(),
        "mapped_periods": len(output), "evidence": evidence,
        "assessment": "NO_GO", "buffett_ready": False, "broker_execution": "DISABLED",
        "note": "Partial ROE and directly filed annual EPS are not Buffett-complete fundamentals",
    })


def main() -> int:
    parser = argparse.ArgumentParser(description="Research-only SEC to Buffett ROE mapping")
    parser.add_argument("--quarterly-coverage", required=True)
    parser.add_argument("--cik", type=int, required=True)
    parser.add_argument("--multimetric-preview", help="Optional SEC preview with directly filed annual diluted EPS")
    parser.add_argument("--output", required=True)
    parser.add_argument("--audit-output", required=True)
    args = parser.parse_args()
    output, audit = Path(args.output), Path(args.audit_output)
    if output == audit or output.exists() or audit.exists():
        parser.error("output collision or existing file; refusing to overwrite")
    coverage = json.loads(Path(args.quarterly_coverage).read_text(encoding="utf-8"))
    eps_preview = (json.loads(Path(args.multimetric_preview).read_text(encoding="utf-8"))
                   if args.multimetric_preview else None)
    mapped, evidence = map_sec_quarterly_to_buffett(coverage, args.cik, eps_preview)
    output.write_text(json.dumps(mapped, indent=2), encoding="utf-8")
    audit.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print("BUFFETT_SCHEMA_MAPPING=SAVED")
    print("ROE_PERIODS=" + str(evidence["mapped_periods"]))
    print("ANNUAL_EPS_PERIODS=" + str(sum("earnings_per_share" in r for r in mapped["records"])))
    print("BUFFETT_READY=FALSE; BROKER_EXECUTION=DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
