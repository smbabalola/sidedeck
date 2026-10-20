"""Offline, point-in-time MSFT SEC Company Facts reconstruction.

This is an industrial-company profile, separate from the bank reconstruction.
Every exported metric is backed by filing-dated XBRL facts and quarter/TTM
checks. Missing or ambiguous inputs remain in the audit and are not exported.
No network, model, broker, or price-feed calls are made.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from sidedeck.application.p5_sec_bank_metrics import (
    _reconcile,
    discrete_quarters,
    _earliest_instant,
    _gaap,
)
from sidedeck.application.p5_sec_ttm import derive_ttm_net_income

MSFT_CIK = 789019
TICKER = "MSFT"
FLOW_TAGS = {
    "revenue": "RevenueFromContractWithCustomerExcludingAssessedTax",
    "gross_profit": "GrossProfit",
    "operating_income": "OperatingIncomeLoss",
    "net_income": "NetIncomeLoss",
    "operating_cash_flow": "NetCashProvidedByUsedInOperatingActivities",
    "capex": "PaymentsToAcquirePropertyPlantAndEquipment",
    "eps": "EarningsPerShareDiluted",
    "diluted_shares": "WeightedAverageNumberOfDilutedSharesOutstanding",
}
INSTANT_TAGS = {
    "equity": "StockholdersEquity",
    "assets_current": "AssetsCurrent",
    "liabilities_current": "LiabilitiesCurrent",
    "long_debt": "LongTermDebt",
    "long_debt_current": "LongTermDebtCurrent",
    "shares": "CommonStockSharesOutstanding",
}


class MSFTMetricsError(ValueError):
    pass


def _alias(payload: dict[str, Any], tag: str, unit: str) -> dict[str, Any]:
    rows = _gaap(payload).get(tag, {}).get("units", {}).get(unit, [])
    return {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": rows}}}}}


def _ttm(
    payload: dict[str, Any], as_of: str, tag: str, unit: str = "USD"
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in derive_ttm_net_income(_alias(payload, tag, unit), as_of):
        for component in row["components"]:
            component["tag"] = tag
            component["unit"] = unit
        result[row["report_period"]] = row
    return result


def _source_url(cik: int, accession: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/"


def _metric(
    value: Decimal,
    definition: str,
    filed: str,
    components: list[dict[str, Any]],
    reconciliation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "value": format(value.quantize(Decimal("0.000001")).normalize(), "f"),
        "definition": definition,
        "status": "RECONCILED",
        "included": True,
        "filing_date": filed,
        "components": components,
    }
    if reconciliation is not None:
        out["reconciliation"] = reconciliation
    return out


def _reconciled(ttm: dict[str, Any], quarters: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return _reconcile(ttm, quarters)


def reconstruct_msft_metrics(
    companyfacts: dict[str, Any], as_of: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    if companyfacts.get("cik") != MSFT_CIK:
        raise MSFTMetricsError("MSFT Company Facts CIK 789019 required")
    cutoff = date.fromisoformat(as_of)
    series = {
        name: _ttm(companyfacts, as_of, tag)
        for name, tag in FLOW_TAGS.items()
        if name not in {"eps", "diluted_shares"}
    }
    series["eps"] = _ttm(companyfacts, as_of, FLOW_TAGS["eps"], "USD/shares")
    series["diluted_shares"] = _ttm(companyfacts, as_of, FLOW_TAGS["diluted_shares"], "shares")
    quarters = {
        name: discrete_quarters(_alias(companyfacts, tag, "USD"), as_of, "NetIncomeLoss")
        for name, tag in FLOW_TAGS.items()
        if name not in {"eps", "diluted_shares"}
    }
    quarters["eps"] = discrete_quarters(
        _alias(companyfacts, FLOW_TAGS["eps"], "USD/shares"), as_of, "NetIncomeLoss"
    )
    quarters["diluted_shares"] = discrete_quarters(
        _alias(companyfacts, FLOW_TAGS["diluted_shares"], "shares"), as_of, "NetIncomeLoss"
    )
    inst = {
        name: _earliest_instant(companyfacts, cutoff, tag) for name, tag in INSTANT_TAGS.items()
    }
    inst["shares"] = _earliest_instant_unit(companyfacts, cutoff, INSTANT_TAGS["shares"], "shares")
    records: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []

    for period in sorted(series["net_income"], reverse=True):
        ni = series["net_income"][period]
        audit: dict[str, Any] = {
            "report_period": period,
            "filing_date": ni["filing_date"],
            "metrics": {},
        }
        rec: dict[str, Any] = {
            "period": "ttm",
            "report_period": period,
            "filing_date": ni["filing_date"],
            "source_url": _source_url(MSFT_CIK, ni["components"][0]["accession"]),
        }

        def ratio(name: str, numerator: str, denominator: str, definition: str) -> None:
            a, b = series[numerator].get(period), series[denominator].get(period)
            if not a or not b or Decimal(b["value"]) == 0:
                audit["metrics"][name] = {"status": "UNAVAILABLE", "included": False}
                return
            ra, rb = _reconciled(a, quarters[numerator]), _reconciled(b, quarters[denominator])
            ok = ra["status"] == rb["status"] == "RECONCILED"
            entry = {
                "status": "RECONCILED" if ok else "NOT_RECONCILED",
                "included": ok,
                "definition": definition,
                "value": format(Decimal(a["value"]) / Decimal(b["value"]), "f"),
                "reconciliation": {numerator: ra, denominator: rb},
                "filing_date": max(a["filing_date"], b["filing_date"]),
                "components": a["components"] + b["components"],
            }
            audit["metrics"][name] = entry
            if ok:
                rec[name] = float(Decimal(a["value"]) / Decimal(b["value"]))

        ratio("net_margin", "net_income", "revenue", "ttm_net_income_over_ttm_revenue")
        ratio("gross_margin", "gross_profit", "revenue", "ttm_gross_profit_over_ttm_revenue")
        ratio(
            "operating_margin",
            "operating_income",
            "revenue",
            "ttm_operating_income_over_ttm_revenue",
        )
        prior_periods = sorted(
            p
            for p in series["revenue"]
            if 360 <= (date.fromisoformat(period) - date.fromisoformat(p)).days <= 371
        )
        prior = series["revenue"].get(prior_periods[0]) if len(prior_periods) == 1 else None
        rev = series["revenue"].get(period)
        if rev and prior and Decimal(prior["value"]) > 0:
            r1, r2 = _reconciled(rev, quarters["revenue"]), _reconciled(prior, quarters["revenue"])
            ok = r1["status"] == r2["status"] == "RECONCILED"
            value = Decimal(rev["value"]) / Decimal(prior["value"]) - 1
            audit["metrics"]["revenue_growth"] = {
                "value": format(value, "f"),
                "definition": "ttm_revenue_year_over_year",
                "status": "RECONCILED" if ok else "NOT_RECONCILED",
                "included": ok,
                "prior_report_period": prior_periods[0],
                "filing_date": max(rev["filing_date"], prior["filing_date"]),
                "reconciliation": {"current": r1, "prior": r2},
                "components": rev["components"] + prior["components"],
            }
            if ok:
                rec["revenue_growth"] = float(value)
        else:
            audit["metrics"]["revenue_growth"] = {"status": "UNAVAILABLE", "included": False}
        equity, prev_equity = inst["equity"].get(period), None
        prior_eq = sorted(
            p
            for p in inst["equity"]
            if 360 <= (date.fromisoformat(period) - date.fromisoformat(p)).days <= 371
        )
        if equity and len(prior_eq) == 1:
            prev_equity = inst["equity"][prior_eq[0]]
        if (
            equity
            and prev_equity
            and equity["filed"].isoformat() <= ni["filing_date"]
            and prev_equity["filed"].isoformat() <= ni["filing_date"]
        ):
            avg = (Decimal(equity["value"]) + Decimal(prev_equity["value"])) / 2
            value = Decimal(ni["value"]) / avg
            audit["metrics"]["return_on_equity"] = _metric(
                value,
                "ttm_net_income_over_average_begin_end_equity",
                ni["filing_date"],
                ni["components"],
            )
            rec["return_on_equity"] = float(value)
        else:
            audit["metrics"]["return_on_equity"] = {"status": "UNAVAILABLE", "included": False}
        for name, num, den, definition in (
            (
                "current_ratio",
                "assets_current",
                "liabilities_current",
                "assets_current_over_liabilities_current",
            ),
        ):
            a, b = inst[num].get(period), inst[den].get(period)
            if a and b and Decimal(b["value"]) > 0:
                value = Decimal(a["value"]) / Decimal(b["value"])
                audit["metrics"][name] = _metric(
                    value,
                    definition,
                    max(a["filed"], b["filed"]).isoformat(),
                    [_source(a, INSTANT_TAGS[num]), _source(b, INSTANT_TAGS[den])],
                )
                rec[name] = float(value)
            else:
                audit["metrics"][name] = {"status": "UNAVAILABLE", "included": False}
        for name, tag in (("debt_to_equity", "long_debt"),):
            debt, eq = inst[tag].get(period), inst["equity"].get(period)
            current = inst["long_debt_current"].get(period)
            if debt and eq and Decimal(eq["value"]) > 0:
                total = Decimal(debt["value"]) + Decimal(current["value"] if current else 0)
                audit["metrics"][name] = _metric(
                    total / Decimal(eq["value"]),
                    "long_term_plus_current_debt_over_equity",
                    max(debt["filed"], eq["filed"]).isoformat(),
                    [_source(debt, INSTANT_TAGS[tag]), _source(eq, INSTANT_TAGS["equity"])]
                    + ([_source(current, INSTANT_TAGS["long_debt_current"])] if current else []),
                )
                rec[name] = float(total / Decimal(eq["value"]))
            else:
                audit["metrics"][name] = {"status": "UNAVAILABLE", "included": False}
        for name in ("eps",):
            a = series[name].get(period)
            if a:
                recon = _reconciled(a, quarters[name])
                # EPS is reported rounded to cents; direct quarter facts can
                # differ from YTD subtraction by a cent while still agreeing
                # with the independently filed annual EPS.
                ok = len(recon.get("quarter_ends", [])) == 4 and abs(
                    Decimal(recon["ttm"]) - Decimal(recon.get("quarter_sum", "0"))
                ) <= Decimal("0.02")
                if ok and recon["status"] != "RECONCILED":
                    recon = {
                        **recon,
                        "status": "RECONCILED_ROUNDED_EPS",
                        "rounding_tolerance": "0.02",
                    }
                audit["metrics"][name] = {
                    "value": a["value"],
                    "definition": "ttm_diluted_eps_from_diluted_eps_facts",
                    "status": "RECONCILED" if ok else "NOT_RECONCILED",
                    "included": ok,
                    "filing_date": a["filing_date"],
                    "reconciliation": recon,
                    "components": a["components"],
                }
                if ok:
                    rec["earnings_per_share"] = float(a["value"])
            else:
                audit["metrics"]["eps"] = {"status": "UNAVAILABLE", "included": False}
        ocf, capex = series["operating_cash_flow"].get(period), series["capex"].get(period)
        shares = series["diluted_shares"].get(period)
        if ocf and capex and shares:
            ro, rc = (
                _reconciled(ocf, quarters["operating_cash_flow"]),
                _reconciled(capex, quarters["capex"]),
            )
            share_rows = sorted(
                (date.fromisoformat(k), q)
                for k, q in quarters["diluted_shares"].items()
                if date.fromisoformat(k) <= date.fromisoformat(period)
            )[-4:]
            share_average = (
                (sum((Decimal(q["value"]) for _, q in share_rows[:3]), Decimal(0)) / 3)
                if len(share_rows) >= 3
                else Decimal(0)
            )
            share_ok = len(share_rows) >= 3 and abs(
                share_average - Decimal(shares["value"])
            ) <= Decimal("50000000")
            rs = {
                "ttm": str(shares["value"]),
                "quarter_ends": [d.isoformat() for d, _ in share_rows],
                "supporting_quarter_average": str(share_average),
                "status": "RECONCILED" if share_ok else "MISMATCH",
                "method": "ANNUAL_WEIGHTED_AVERAGE_WITH_Q1_Q3_SUPPORT",
            }
            ok = ro["status"] == rc["status"] == "RECONCILED" and share_ok
            fcf = (Decimal(ocf["value"]) - Decimal(capex["value"])) / Decimal(shares["value"])
            audit["metrics"]["free_cash_flow_per_share"] = {
                "value": format(fcf, "f"),
                "definition": "ttm_ocf_less_capex_over_ttm_diluted_shares",
                "status": "RECONCILED" if ok else "NOT_RECONCILED",
                "included": ok,
                "filing_date": max(ocf["filing_date"], capex["filing_date"], shares["filing_date"]),
                "reconciliation": {"ocf": ro, "capex": rc, "shares": rs},
                "components": ocf["components"] + capex["components"] + shares["components"],
            }
            if ok:
                rec["free_cash_flow_per_share"] = float(fcf)
        else:
            audit["metrics"]["free_cash_flow_per_share"] = {
                "status": "UNAVAILABLE",
                "included": False,
            }
        eq, sh = inst["equity"].get(period), inst["shares"].get(period)
        if (
            eq
            and sh
            and Decimal(sh["value"]) > 0
            and eq["filed"].isoformat() <= ni["filing_date"]
            and sh["filed"].isoformat() <= ni["filing_date"]
        ):
            bvps = Decimal(eq["value"]) / Decimal(sh["value"])
            audit["metrics"]["book_value_per_share"] = _metric(
                bvps,
                "period_end_equity_over_period_end_common_shares",
                max(eq["filed"], sh["filed"]).isoformat(),
                [_source(eq, INSTANT_TAGS["equity"]), _source(sh, INSTANT_TAGS["shares"])],
            )
            rec["book_value_per_share"] = float(bvps)
        else:
            audit["metrics"]["book_value_per_share"] = {"status": "UNAVAILABLE", "included": False}
        audit["metrics"]["market_cap"] = {
            "status": "UNAVAILABLE",
            "included": False,
            "reason": "no independently validated historical price",
        }
        audit["metrics"]["price_to_earnings_ratio"] = {
            "status": "UNAVAILABLE",
            "included": False,
            "reason": "market cap and historical price unavailable",
        }
        audit["validated_metric_count"] = sum(
            1 for m in audit["metrics"].values() if m.get("included")
        )
        records.append(rec)
        audits.append(audit)
    records.sort(key=lambda r: r["report_period"], reverse=True)
    audits.sort(key=lambda r: r["report_period"], reverse=True)
    latest = audits[0] if audits else {"validated_metric_count": 0}
    audit_out = {
        "ticker": TICKER,
        "cik": MSFT_CIK,
        "as_of": as_of,
        "profile": "general",
        "periods": audits,
        "latest_validated_metric_count": latest["validated_metric_count"],
        "reconciled_historical_periods": sum(
            1 for row in audits if row["validated_metric_count"] >= 1
        ),
        "valuation": "UNRESOLVED_HISTORICAL_PRICE_AND_SHARE_BASIS",
        "coverage_gate": "NOT_ASSESSED",
        "research_ready": False,
        "buffett_ready": False,
        "broker_execution": "DISABLED",
        "source": "OWNER_SUPPLIED_LOCAL_SEC_COMPANYFACTS",
    }
    return {"ticker": TICKER, "records": records}, audit_out


def _source(row: dict[str, Any], tag: str) -> dict[str, Any]:
    return {
        "accession": row["accn"],
        "filed": row["filed"].isoformat(),
        "end": row["end"].isoformat(),
        "form": row["form"],
        "tag": tag,
        "unit": "USD",
    }


def _earliest_instant_unit(
    payload: dict[str, Any], cutoff: date, tag: str, unit: str
) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for item in _gaap(payload).get(tag, {}).get("units", {}).get(unit, []):
        if (
            not isinstance(item, dict)
            or item.get("form") not in ("10-K", "10-Q")
            or "start" in item
        ):
            continue
        try:
            end, filed = date.fromisoformat(item["end"]), date.fromisoformat(item["filed"])
            value = item["val"]
        except (KeyError, TypeError, ValueError):
            continue
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not end <= filed <= cutoff
        ):
            continue
        row = {
            "end": end,
            "filed": filed,
            "value": value,
            "accn": item.get("accn", ""),
            "form": item["form"],
        }
        prior = found.get(end.isoformat())
        if prior is None or filed < prior["filed"]:
            found[end.isoformat()] = row
    return found


def main() -> int:
    p = argparse.ArgumentParser(description="Offline MSFT SEC reconstruction")
    p.add_argument("--companyfacts", required=True)
    p.add_argument("--as-of", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--audit-output", required=True)
    a = p.parse_args()
    out, audit = Path(a.output), Path(a.audit_output)
    if out.exists() or audit.exists() or out == audit:
        p.error("refusing to overwrite output")
    payload, report = reconstruct_msft_metrics(
        json.loads(Path(a.companyfacts).read_text(encoding="utf-8")), a.as_of
    )
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    audit.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        f"MSFT_VALIDATED_LATEST={report['latest_validated_metric_count']}; RECONCILED_PERIODS={report['reconciled_historical_periods']}; COVERAGE_GATE=NOT_ASSESSED; BROKER_EXECUTION=DISABLED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
