"""Bank-aware SEC metric reconstruction for the BuffettAgent local input.

Lender financial statements differ from industrial ones. Rather than forcing
every upstream field, each one is applied, labelled, held for owner approval,
or recorded as not applicable. Only metrics whose TTM inputs reconcile against
independently tagged 3-month facts enter the research input; everything else
stays in the audit. No network access, LLM or broker.
"""
from __future__ import annotations

import argparse
import copy
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sidedeck.application.p5_sec_ttm import derive_ttm_net_income


class BankMetricsError(ValueError):
    pass


TOLERANCE = Decimal("0.001")  # relative; filed XBRL values normally match exactly
REVENUE = "RevenuesNetOfInterestExpense"
NET_INCOME = "NetIncomeLoss"
OCF = "NetCashProvidedByUsedInOperatingActivities"
CAPEX = "PaymentsToAcquireProductiveAssets"
ORIGINATIONS = "PaymentsForOriginationAndPurchasesOfLoansHeldForSale"
APPROVABLE_DEFINITIONS = frozenset({"debt_to_equity:borrowings_excluding_deposits"})
EXCLUDED_INPUT_FIELDS = frozenset({"book_value_per_share", "gross_margin", "operating_margin",
                                   "current_ratio", "free_cash_flow_per_share"})
RECONSTRUCTED_FIELDS = frozenset({"net_margin", "revenue_growth", "debt_to_equity"})

_STATIC_POLICY: dict[str, dict[str, str]] = {
    "return_on_equity": {"status": "INCLUDED_EXISTING",
                         "definition": "ttm_net_income_over_average_equity (earlier mapping)"},
    "earnings_per_share": {"status": "INCLUDED_EXISTING",
                           "definition": "directly filed full-year diluted EPS"},
    "net_margin": {
        "status": "APPLICABLE", "definition": "ttm_net_income_over_ttm_total_net_revenue",
        "note": "Total net revenue is RevenuesNetOfInterestExpense (net interest income "
                "plus noninterest income). NetIncomeLoss is before preferred dividends."},
    "revenue_growth": {
        "status": "APPLICABLE", "definition": "ttm_total_net_revenue_year_over_year",
        "note": "SideDeck definition; Financial Datasets semantics are not verified."},
    "debt_to_equity": {
        "status": "DEFINITION_APPROVAL_REQUIRED", "definition": "borrowings_excluding_deposits",
        "note": "DebtLongtermAndShorttermCombinedAmount / StockholdersEquity. Customer "
                "deposits are funding, reported only as context; not comparable with "
                "industrial leverage."},
    "book_value_per_share": {
        "status": "EXCLUDED_PENDING_APPROVAL",
        "reason": "Earlier BVPS calculations are not reconciled or owner-approved."},
    "gross_margin": {
        "status": "NOT_APPLICABLE",
        "reason": "Bank income statements have no cost-of-goods-sold or gross-profit line."},
    "operating_margin": {
        "status": "NOT_APPLICABLE",
        "reason": "No operating-income subtotal in the bank presentation."},
    "current_ratio": {
        "status": "NOT_APPLICABLE",
        "reason": "Bank balance sheets are unclassified (no current assets/liabilities)."},
    "market_cap": {"status": "VALUATION_EVIDENCE_PENDING",
                   "reason": "Requires validated filing-date price and share count."},
    "price_to_earnings_ratio": {"status": "VALUATION_EVIDENCE_PENDING",
                                "reason": "Requires validated market cap and earnings basis."},
}


def _fmt(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001")).normalize(), "f")


def _gaap(payload: dict[str, Any]) -> dict[str, Any]:
    gaap = payload.get("facts", {}).get("us-gaap") if isinstance(payload, dict) else None
    if not isinstance(gaap, dict):
        raise BankMetricsError("missing US-GAAP facts")
    return gaap


def _rows(payload: dict[str, Any], tag: str) -> list[dict[str, Any]]:
    units = _gaap(payload).get(tag, {}).get("units", {})
    rows = units.get("USD", []) if isinstance(units, dict) else []
    return [r for r in rows if isinstance(r, dict)]


def _earliest_flows(payload: dict[str, Any], cutoff: date, tag: str) -> dict[tuple[date, date], dict[str, Any]]:
    found: dict[tuple[date, date], dict[str, Any]] = {}
    for item in _rows(payload, tag):
        if item.get("form") not in ("10-K", "10-Q"):
            continue
        try:
            start, end, filed = (date.fromisoformat(item[k]) for k in ("start", "end", "filed"))
            value = item["val"]
            accession = item["accn"]
        except (KeyError, TypeError, ValueError):
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        if filed > cutoff or filed < end or not 75 <= (end - start).days <= 380:
            continue
        row = {"start": start, "end": end, "filed": filed, "value": value,
               "accn": accession, "form": item["form"]}
        prior = found.get((start, end))
        if prior is None or filed < prior["filed"]:
            found[(start, end)] = row
    return found


def _source(row: dict[str, Any], tag: str) -> dict[str, Any]:
    out = {"accession": row["accn"], "filed": row["filed"].isoformat(),
           "end": row["end"].isoformat(), "form": row["form"], "tag": tag, "unit": "USD"}
    if "start" in row:
        out["start"] = row["start"].isoformat()
    return out


def discrete_quarters(payload: dict[str, Any], as_of: str, tag: str) -> dict[str, dict[str, Any]]:
    """Quarterly values: direct 3-month facts where tagged, else YTD differences."""
    cutoff = date.fromisoformat(as_of)
    flows = _earliest_flows(payload, cutoff, tag)
    annual = [r for r in flows.values() if r["form"] == "10-K" and 330 <= (r["end"] - r["start"]).days <= 380]
    starts = {r["start"] for r in annual} | {r["end"] + timedelta(days=1) for r in annual}
    quarters: dict[str, dict[str, Any]] = {}
    for fiscal_start in starts:
        ytd = sorted((r for r in flows.values() if r["start"] == fiscal_start), key=lambda r: r["end"])
        previous: dict[str, Any] | None = None
        for row in ytd:
            if previous is None:
                if 75 <= (row["end"] - row["start"]).days <= 100:
                    quarters[row["end"].isoformat()] = {
                        "value": row["value"], "method": "FIRST_QUARTER_YTD",
                        "filed": row["filed"], "sources": [_source(row, tag)]}
            elif 80 <= (row["end"] - previous["end"]).days <= 100:
                is_annual = row["form"] == "10-K" and (row["end"] - row["start"]).days >= 330
                quarters[row["end"].isoformat()] = {
                    "value": row["value"] - previous["value"],
                    "method": "ANNUAL_LESS_NINE_MONTHS" if is_annual else "YTD_DIFFERENCE",
                    "filed": max(row["filed"], previous["filed"]),
                    "sources": [_source(row, tag), _source(previous, tag)]}
            previous = row
    for row in flows.values():
        if row["start"] in starts or not 75 <= (row["end"] - row["start"]).days <= 100:
            continue
        key = row["end"].isoformat()
        derived = quarters.get(key)
        direct = {"value": row["value"], "method": "DIRECT_THREE_MONTH", "filed": row["filed"],
                  "sources": [_source(row, tag)]}
        if derived is not None and row["value"] != derived["value"]:
            direct["method"] = "DIRECT_CONFLICTS_WITH_YTD"
            direct["ytd_difference"] = derived["value"]
        quarters[key] = direct
    return quarters


def ttm_series(payload: dict[str, Any], as_of: str, tag: str) -> dict[str, dict[str, Any]]:
    # Reuse the established FY + current YTD - prior YTD converter by tag substitution.
    substituted = {"facts": {"us-gaap": {"NetIncomeLoss": _gaap(payload).get(tag, {})}}}
    result: dict[str, dict[str, Any]] = {}
    for row in derive_ttm_net_income(substituted, as_of):
        for component in row["components"]:
            component["tag"] = tag
        result[row["report_period"]] = row
    return result


def _reconcile(ttm: dict[str, Any], quarters: dict[str, dict[str, Any]]) -> dict[str, Any]:
    end = date.fromisoformat(ttm["report_period"])
    available = date.fromisoformat(ttm["filing_date"])
    usable = sorted(
        (date.fromisoformat(k), q) for k, q in quarters.items()
        if date.fromisoformat(k) <= end and q["filed"] <= available
        and (end - date.fromisoformat(k)).days < 300
    )[-4:]
    total = Decimal(ttm["value"])
    result: dict[str, Any] = {"ttm": _fmt(total), "quarter_ends": [d.isoformat() for d, _ in usable]}
    gaps = [(b[0] - a[0]).days for a, b in zip(usable, usable[1:])]
    if len(usable) != 4 or usable[-1][0] != end or not all(80 <= g <= 100 for g in gaps):
        return {**result, "status": "INSUFFICIENT_QUARTERS", "independent_quarters": 0}
    quarter_sum = sum((Decimal(q["value"]) for _, q in usable), Decimal(0))
    independent = sum(q["method"] == "DIRECT_THREE_MONTH" for _, q in usable)
    conflict = any(q["method"] == "DIRECT_CONFLICTS_WITH_YTD" for _, q in usable)
    within = abs(total - quarter_sum) <= TOLERANCE * max(abs(total), Decimal(1))
    if conflict or not within:
        status = "MISMATCH"
    elif independent == 0:
        status = "ARITHMETIC_ONLY"
    else:
        status = "RECONCILED"
    return {**result, "quarter_sum": _fmt(quarter_sum), "status": status,
            "independent_quarters": independent,
            "quarter_methods": [q["method"] for _, q in usable]}


def _earliest_instant(payload: dict[str, Any], cutoff: date, tag: str) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for item in _rows(payload, tag):
        if item.get("form") not in ("10-K", "10-Q") or "start" in item:
            continue
        try:
            end, filed = date.fromisoformat(item["end"]), date.fromisoformat(item["filed"])
            value = item["val"]
            accession = item["accn"]
        except (KeyError, TypeError, ValueError):
            continue
        if isinstance(value, bool) or not isinstance(value, int) or not end <= filed <= cutoff:
            continue
        row = {"end": end, "filed": filed, "value": value, "accn": accession, "form": item["form"]}
        prior = found.get(end.isoformat())
        if prior is None or filed < prior["filed"]:
            found[end.isoformat()] = row
    return found


def _year_ago(series: dict[str, dict[str, Any]], period: str) -> dict[str, Any] | None:
    end = date.fromisoformat(period)
    matches = [row for key, row in series.items() if 360 <= (end - date.fromisoformat(key)).days <= 371]
    return matches[0] if len(matches) == 1 else None


def reconstruct_bank_metrics(
    companyfacts: dict[str, Any], base_input: dict[str, Any], as_of: str, *, cik: int,
    approved_definitions: set[str] | frozenset[str] = frozenset(),
) -> tuple[dict[str, Any], dict[str, Any]]:
    unknown = set(approved_definitions) - APPROVABLE_DEFINITIONS
    if unknown:
        raise BankMetricsError("unknown definition approval: " + ", ".join(sorted(unknown)))
    cutoff = date.fromisoformat(as_of)
    ticker = base_input.get("ticker") if isinstance(base_input, dict) else None
    records = base_input.get("records") if isinstance(base_input, dict) else None
    if not isinstance(ticker, str) or not isinstance(records, list):
        raise BankMetricsError("base input requires ticker and records")
    for record in records:
        if EXCLUDED_INPUT_FIELDS & set(record):
            raise BankMetricsError("base input carries an excluded field")
        if RECONSTRUCTED_FIELDS & set(record):
            raise BankMetricsError("base input already carries a reconstructed field")
    de_approved = "debt_to_equity:borrowings_excluding_deposits" in approved_definitions

    revenue, income = ttm_series(companyfacts, as_of, REVENUE), ttm_series(companyfacts, as_of, NET_INCOME)
    ocf, capex = ttm_series(companyfacts, as_of, OCF), ttm_series(companyfacts, as_of, CAPEX)
    rev_q = discrete_quarters(companyfacts, as_of, REVENUE)
    ni_q = discrete_quarters(companyfacts, as_of, NET_INCOME)
    ocf_q, capex_q = discrete_quarters(companyfacts, as_of, OCF), discrete_quarters(companyfacts, as_of, CAPEX)
    debt = _earliest_instant(companyfacts, cutoff, "DebtLongtermAndShorttermCombinedAmount")
    equity = _earliest_instant(companyfacts, cutoff, "StockholdersEquity")
    deposits = _earliest_instant(companyfacts, cutoff, "Deposits")
    originations_operating = bool(_gaap(companyfacts).get(ORIGINATIONS))

    output_records: list[dict[str, Any]] = []
    periods: list[dict[str, Any]] = []
    for base in copy.deepcopy(records):
        period, base_filed = base.get("report_period"), base.get("filing_date")
        if not isinstance(period, str) or not isinstance(base_filed, str):
            raise BankMetricsError("base record missing dates")
        if date.fromisoformat(base_filed) > cutoff:
            continue
        metrics: dict[str, Any] = {}
        additions: dict[str, tuple[float, str]] = {}

        rev, ni = revenue.get(period), income.get(period)
        if rev and ni and rev["value"] > 0:
            recon = {"revenue_ttm": _reconcile(rev, rev_q), "net_income_ttm": _reconcile(ni, ni_q)}
            ok = all(r["status"] == "RECONCILED" for r in recon.values())
            value = Decimal(ni["value"]) / Decimal(rev["value"])
            filed = max(rev["filing_date"], ni["filing_date"])
            metrics["net_margin"] = {
                "value": _fmt(value), "definition": _STATIC_POLICY["net_margin"]["definition"],
                "status": "RECONCILED" if ok else "NOT_RECONCILED", "included": ok,
                "filing_date": filed, "reconciliation": recon,
                "components": rev["components"] + ni["components"]}
            if ok:
                additions["net_margin"] = (float(value), filed)
        else:
            metrics["net_margin"] = {"status": "UNAVAILABLE", "included": False}

        prior = _year_ago(revenue, period)
        if rev and prior and prior["value"] > 0:
            recon = {"revenue_ttm": _reconcile(rev, rev_q), "prior_revenue_ttm": _reconcile(prior, rev_q)}
            ok = all(r["status"] == "RECONCILED" for r in recon.values())
            value = Decimal(rev["value"]) / Decimal(prior["value"]) - 1
            filed = max(rev["filing_date"], prior["filing_date"])
            metrics["revenue_growth"] = {
                "value": _fmt(value), "definition": _STATIC_POLICY["revenue_growth"]["definition"],
                "status": "RECONCILED" if ok else "NOT_RECONCILED", "included": ok,
                "filing_date": filed, "prior_report_period": prior["report_period"],
                "reconciliation": recon, "components": rev["components"] + prior["components"]}
            if ok:
                additions["revenue_growth"] = (float(value), filed)
        else:
            metrics["revenue_growth"] = {"status": "UNAVAILABLE", "included": False}

        d, e = debt.get(period), equity.get(period)
        if d and e and e["value"] > 0:
            value = Decimal(d["value"]) / Decimal(e["value"])
            filed = max(d["filed"], e["filed"]).isoformat()
            dep = deposits.get(period)
            context: dict[str, Any] = {"deposits": dep["value"] if dep else None}
            if dep:
                context["deposits_plus_borrowings_to_equity"] = _fmt(
                    (Decimal(dep["value"]) + Decimal(d["value"])) / Decimal(e["value"]))
            metrics["debt_to_equity"] = {
                "value": _fmt(value), "definition": "borrowings_excluding_deposits",
                "status": "OWNER_APPROVED_DEFINITION" if de_approved else "DEFINITION_APPROVAL_REQUIRED",
                "included": de_approved, "filing_date": filed, "context": context,
                "components": [_source(d, "DebtLongtermAndShorttermCombinedAmount"),
                               _source(e, "StockholdersEquity")]
                              + ([_source(dep, "Deposits")] if dep else [])}
            if de_approved:
                additions["debt_to_equity"] = (float(value), filed)
        else:
            metrics["debt_to_equity"] = {"status": "UNAVAILABLE", "included": False}

        o, c = ocf.get(period), capex.get(period)
        if o and c:
            metrics["free_cash_flow"] = {
                "value": _fmt(Decimal(o["value"]) - Decimal(c["value"])),
                "definition": "ttm_operating_cash_flow_less_productive_asset_payments",
                "status": "NOT_MEANINGFUL_FOR_LENDER" if originations_operating else "REVIEW_REQUIRED",
                "included": False, "per_share": "NOT_COMPUTED",
                "filing_date": max(o["filing_date"], c["filing_date"]),
                "reconciliation": {"operating_cash_flow_ttm": _reconcile(o, ocf_q),
                                   "capex_ttm": _reconcile(c, capex_q)},
                "components": o["components"] + c["components"]}
        else:
            metrics["free_cash_flow"] = {"status": "UNAVAILABLE", "included": False}

        record = dict(base)
        for name, (value_float, filed) in additions.items():
            record[name] = value_float
            record["filing_date"] = max(record["filing_date"], filed)
        output_records.append(record)
        periods.append({"report_period": period, "available_from": record["filing_date"],
                        "metrics": metrics, "included_fields": sorted(additions)})

    policy = copy.deepcopy(_STATIC_POLICY)
    if de_approved:
        policy["debt_to_equity"]["status"] = "OWNER_APPROVED_DEFINITION"
    policy["free_cash_flow_per_share"] = (
        {"status": "NOT_MEANINGFUL",
         "reason": f"{ORIGINATIONS} is tagged: loan originations held for sale run through "
                   "operating cash flow, so OCF less capex does not measure owner earnings."}
        if originations_operating else
        {"status": "REVIEW_REQUIRED",
         "reason": "Lender cash flows mix lending activity with operations; needs review."})
    return ({"ticker": ticker, "records": output_records}, {
        "ticker": ticker, "cik": cik, "as_of": as_of,
        "profile": "us_bank_holding_company", "reconciliation_tolerance": str(TOLERANCE),
        "approved_definitions": sorted(approved_definitions),
        "field_policy": policy, "periods": periods,
        "assessment": "NO_GO", "buffett_ready": False, "approved": False,
        "broker_execution": "DISABLED",
    })


def main() -> int:
    parser = argparse.ArgumentParser(description="Bank-aware SEC metrics for BuffettAgent input")
    parser.add_argument("--companyfacts", required=True)
    parser.add_argument("--base-input", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--cik", type=int, required=True)
    parser.add_argument("--approve-definition", action="append", default=[])
    parser.add_argument("--output", required=True)
    parser.add_argument("--audit-output", required=True)
    args = parser.parse_args()
    output, audit_path = Path(args.output), Path(args.audit_output)
    if output == audit_path or output.exists() or audit_path.exists():
        parser.error("output collision or existing file; refusing to overwrite")
    facts = json.loads(Path(args.companyfacts).read_text(encoding="utf-8"))
    base = json.loads(Path(args.base_input).read_text(encoding="utf-8"))
    payload, audit = reconstruct_bank_metrics(facts, base, args.as_of, cik=args.cik,
                                              approved_definitions=set(args.approve_definition))
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    audit_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    counts = {name: sum(name in r for r in payload["records"]) for name in sorted(RECONSTRUCTED_FIELDS)}
    print("BANK_METRICS=SAVED " + json.dumps(counts, sort_keys=True))
    print("BUFFETT_READY=FALSE; BROKER_EXECUTION=DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
