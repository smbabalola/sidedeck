"""No-network coverage and cost report for a BuffettAgent run on local SEC data.

Answers three questions before any provider call is requested:
1. Which of the upstream snapshot fields does the local SEC file populate?
2. Which SEC concepts exist for the missing fields (presence only, unvalidated)?
3. How large is the exact upstream prompt, and what is the cost upper bound?

Never calls an LLM, Financial Datasets, SEC, or a broker. Assessment stays NO_GO.
"""
from __future__ import annotations

import argparse
import json
from decimal import Decimal
from importlib import import_module
from pathlib import Path
from typing import Any

from sidedeck.bridges.filed_fundamentals import LocalFiledDataClient, verified_fundamentals

# Mirrors hedge_fund.features.snapshot.PeriodFundamentals at aihf 2.5.0,
# git ec025370c66cf71d3ea2f2d8f463b5934c1c48af. upstream_field_drift() checks it.
SNAPSHOT_FIELDS = (
    "market_cap", "price_to_earnings_ratio", "return_on_equity", "gross_margin",
    "operating_margin", "net_margin", "debt_to_equity", "current_ratio",
    "revenue_growth", "earnings_per_share", "book_value_per_share",
    "free_cash_flow_per_share",
)

# Buffett system-prompt checklist items that are judged from numbers.
CHECKLIST = {
    "moat": ("return_on_equity", "gross_margin", "operating_margin", "net_margin"),
    "management": ("book_value_per_share", "free_cash_flow_per_share",
                   "earnings_per_share"),
    "financial_strength": ("debt_to_equity", "current_ratio"),
    "valuation": ("market_cap", "price_to_earnings_ratio"),
}

# SEC concepts that could feed each field. Presence is counted; nothing here
# asserts the derivation is correct for a given filer (banks especially).
CANDIDATE_CONCEPTS: dict[str, tuple[str, ...]] = {
    "market_cap": ("dei:EntityCommonStockSharesOutstanding",
                   "us-gaap:CommonStockSharesOutstanding"),
    "price_to_earnings_ratio": ("us-gaap:EarningsPerShareDiluted",),
    "return_on_equity": ("us-gaap:NetIncomeLoss", "us-gaap:StockholdersEquity"),
    "gross_margin": ("us-gaap:RevenuesNetOfInterestExpense", "us-gaap:Revenues",
                     "us-gaap:CostOfRevenue"),
    "operating_margin": ("us-gaap:OperatingIncomeLoss",
                         "us-gaap:RevenuesNetOfInterestExpense"),
    "net_margin": ("us-gaap:NetIncomeLoss", "us-gaap:RevenuesNetOfInterestExpense",
                   "us-gaap:Revenues"),
    "debt_to_equity": ("us-gaap:DebtLongtermAndShorttermCombinedAmount",
                       "us-gaap:LongTermDebt", "us-gaap:StockholdersEquity"),
    "current_ratio": ("us-gaap:AssetsCurrent", "us-gaap:LiabilitiesCurrent"),
    "revenue_growth": ("us-gaap:RevenuesNetOfInterestExpense", "us-gaap:Revenues"),
    "earnings_per_share": ("us-gaap:EarningsPerShareDiluted",),
    "book_value_per_share": ("us-gaap:StockholdersEquity",
                             "us-gaap:CommonStockSharesOutstanding"),
    "free_cash_flow_per_share": ("us-gaap:NetCashProvidedByUsedInOperatingActivities",
                                 "us-gaap:PaymentsToAcquireProductiveAssets",
                                 "us-gaap:CommonStockSharesOutstanding"),
}
_PRICE_FIELDS = frozenset({"market_cap", "price_to_earnings_ratio"})

# Fields that are not relevant evidence for a sector. They are excluded from the
# gate, and populating one anyway fails the gate rather than raising coverage.
PROFILES: dict[str, dict[str, str]] = {
    "general": {},
    "bank": {
        "gross_margin": "NOT_APPLICABLE",
        "operating_margin": "NOT_APPLICABLE",
        "current_ratio": "NOT_APPLICABLE",
        "free_cash_flow_per_share": "NOT_MEANINGFUL",
        "book_value_per_share": "EXCLUDED_PENDING_APPROVAL",
    },
}

# make_llm() defaults at the pinned upstream revision: Anthropic passes
# max_tokens=4096; OpenAI and Google pass no cap (provider default applies).
OUTPUT_TOKEN_CAP: dict[str, int | None] = {"anthropic": 4096, "openai": None,
                                           "google": None}


def _aggregates(rows: list[dict[str, Any]]) -> dict[str, str]:
    def count(field: str) -> int:
        return sum(row.get(field) is not None for row in rows)

    def newest(field: str) -> bool:
        return bool(rows) and rows[0].get(field) is not None

    bvps = [row["book_value_per_share"] for row in rows
            if row.get("book_value_per_share") is not None]
    eps_ok = (len(rows) >= 5 and rows[0].get("earnings_per_share") is not None
              and (rows[4].get("earnings_per_share") or 0) > 0)
    status = {
        "roe_avg": count("return_on_equity") >= 1,
        "net_margin_avg": count("net_margin") >= 1,
        "gross_margin_trend": count("gross_margin") >= 2,
        "bvps_cagr": len(bvps) >= 2 and bvps[0] > 0 and bvps[-1] > 0,
        "debt_to_equity_latest": newest("debt_to_equity"),
        "market_cap_latest": newest("market_cap"),
        "eps_growth_yoy": eps_ok,
    }
    return {name: "COMPUTABLE" if ok else "UNAVAILABLE" for name, ok in status.items()}


def coverage_report(path: str | Path, ticker: str, as_of: str,
                    periods: int = 20, profile: str = "general") -> dict[str, Any]:
    """Judge the periods build_snapshot would see on relevant evidence only."""
    if profile not in PROFILES:
        raise ValueError("unknown sector profile")
    excluded = PROFILES[profile]
    rows = verified_fundamentals(path, ticker, as_of)[:periods]
    fields = {
        name: {"populated": sum(row.get(name) is not None for row in rows),
               "eligible_periods": len(rows),
               "newest_period": rows[0].get(name) is not None,
               "applicability": excluded.get(name, "RELEVANT")}
        for name in SNAPSHOT_FIELDS
    }
    checklist: dict[str, Any] = {}
    for item, names in CHECKLIST.items():
        relevant = [n for n in names if n not in excluded]
        present = [n for n in relevant if fields[n]["newest_period"]]
        if not relevant:
            status = "NOT_ASSESSABLE"
        else:
            status = ("FULL" if len(present) == len(relevant)
                      else "PARTIAL" if present else "NO_EVIDENCE")
        checklist[item] = {"status": status, "fields_present": present,
                           "fields_missing": [n for n in relevant if n not in present],
                           "fields_not_relevant": [n for n in names if n in excluded]}
    forced = sorted(n for n in excluded if fields[n]["populated"])
    relevant_names = [n for n in SNAPSHOT_FIELDS if n not in excluded]
    relevant_newest = sum(1 for n in relevant_names if fields[n]["newest_period"])
    gate = (not forced and all(entry["status"] in ("FULL", "PARTIAL")
                               for entry in checklist.values()))
    return {
        "ticker": ticker, "as_of": as_of, "profile": profile,
        "relevant_fields_in_newest": f"{relevant_newest}/{len(relevant_names)}",
        "not_relevant_fields_populated": forced,
        "eligible_periods": len(rows),
        "newest_report_period": rows[0]["report_period"],
        "newest_filing_date": rows[0]["filing_date"],
        "fields": fields,
        "fields_populated_in_newest": sum(f["newest_period"] for f in fields.values()),
        "aggregates": _aggregates(rows),
        "checklist": checklist,
        "coverage_gate": "PASS" if gate else "FAIL",
        "financial_datasets_required": False,
        "assessment": "NO_GO", "buffett_ready": False, "approved": False,
        "broker_execution": "DISABLED",
    }


def concept_inventory(companyfacts: dict[str, Any]) -> dict[str, Any]:
    """Count SEC observations per candidate concept. Presence is not validity."""
    facts = companyfacts.get("facts", {}) if isinstance(companyfacts, dict) else {}

    def observations(qualified: str) -> int:
        taxonomy, concept = qualified.split(":", 1)
        units = facts.get(taxonomy, {}).get(concept, {}).get("units", {})
        return sum(len(values) for values in units.values()) if isinstance(units, dict) else 0

    return {
        field: {"candidates": {c: observations(c) for c in concepts},
                "requires_price_evidence": field in _PRICE_FIELDS,
                "validated": False}
        for field, concepts in CANDIDATE_CONCEPTS.items()
    }


def cost_bound(input_tokens: int, output_cap: int | None,
               input_usd_per_mtok: Decimal | None,
               output_usd_per_mtok: Decimal | None) -> str:
    """Worst-case USD for one call, or a reason the bound cannot be stated."""
    if input_usd_per_mtok is None or output_usd_per_mtok is None:
        return "PRICE_NOT_SUPPLIED"
    if input_usd_per_mtok < 0 or output_usd_per_mtok < 0 or input_tokens < 0:
        raise ValueError("prices and token counts must be non-negative")
    if output_cap is None:
        return "OUTPUT_CAP_UNKNOWN"
    million = Decimal(1_000_000)
    total = (Decimal(input_tokens) * input_usd_per_mtok
             + Decimal(output_cap) * output_usd_per_mtok) / million
    return str(total.quantize(Decimal("0.000001")))


def upstream_field_drift() -> dict[str, Any] | str:
    try:
        model = import_module("hedge_fund.features.snapshot").PeriodFundamentals
    except ImportError:
        return "UPSTREAM_NOT_IMPORTABLE"
    upstream = tuple(n for n in model.model_fields if n not in ("report_period", "filing_date"))
    if upstream == SNAPSHOT_FIELDS:
        return "NONE"
    return {"missing_here": sorted(set(upstream) - set(SNAPSHOT_FIELDS)),
            "removed_upstream": sorted(set(SNAPSHOT_FIELDS) - set(upstream))}


def prompt_size(path: str | Path, ticker: str, as_of: str) -> dict[str, Any] | str:
    """Render the exact upstream prompt without an LLM. Needs the upstream venv."""
    try:
        cls = import_module("hedge_fund.signals.buffett").BuffettAgent
    except ImportError:
        return "UPSTREAM_NOT_IMPORTABLE"

    class NoLLM:
        model = "none"

        def complete(self, system: str, user: str) -> str:
            raise RuntimeError("LLM access forbidden during coverage report")

    agent = cls(llm=NoLLM())
    snapshot = agent.build_snapshot(ticker, as_of, LocalFiledDataClient(path))
    system = agent.get_system_prompt()
    user = agent.build_user_prompt(snapshot)
    chars = len(system) + len(user)
    return {"system_chars": len(system), "user_chars": len(user),
            # ~4 characters per token; an estimate, not a tokenizer count.
            "input_tokens_estimate": -(-chars // 4),
            "token_method": "ESTIMATE_CHARS_DIV_4",
            "snapshot_hash": snapshot.content_hash,
            "llm_calls_per_snapshot": 1}


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    report = coverage_report(args.fundamentals_json, args.ticker, args.as_of,
                             profile=args.sector_profile)
    if args.companyfacts:
        facts = json.loads(Path(args.companyfacts).read_text(encoding="utf-8"))
        report["missing_field_sources"] = {
            field: entry for field, entry in concept_inventory(facts).items()
            if not report["fields"][field]["newest_period"]
        }
    report["upstream_field_drift"] = upstream_field_drift()
    size = prompt_size(args.fundamentals_json, args.ticker, args.as_of)
    report["prompt"] = size
    cap = OUTPUT_TOKEN_CAP.get(args.provider)
    price_in = Decimal(args.input_usd_per_mtok) if args.input_usd_per_mtok else None
    price_out = Decimal(args.output_usd_per_mtok) if args.output_usd_per_mtok else None
    report["cost"] = {
        "provider": args.provider, "output_token_cap": cap,
        "max_usd_one_call": (cost_bound(size["input_tokens_estimate"], cap, price_in, price_out)
                             if isinstance(size, dict) else "PROMPT_SIZE_UNAVAILABLE"),
        "price_source": "OPERATOR_SUPPLIED" if price_in is not None else "NONE",
    }
    report["blockers"] = [
        *(f"{entry['status'].lower().replace('_', ' ')} for checklist item: {name}"
          for name, entry in report["checklist"].items()
          if entry["status"] not in ("FULL", "PARTIAL")),
        *(f"not-relevant field populated: {name}"
          for name in report["not_relevant_fields_populated"]),
        "owner authorization for a provider call has not been given",
    ]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="BuffettAgent SEC coverage and cost report")
    parser.add_argument("--fundamentals-json", required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--companyfacts", default="")
    parser.add_argument("--sector-profile", default="general", choices=sorted(PROFILES))
    parser.add_argument("--provider", default="anthropic", choices=sorted(OUTPUT_TOKEN_CAP))
    parser.add_argument("--input-usd-per-mtok", default="")
    parser.add_argument("--output-usd-per-mtok", default="")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    report = build_report(args)
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        out = Path(args.output)
        if out.exists():
            raise SystemExit("refusing to overwrite existing report")
        out.write_text(text + "\n", encoding="utf-8")
    print(text)
    print("BROKER_EXECUTION=DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
