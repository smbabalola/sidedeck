"""Offline dual-agent research acceptance: fail closed on missing/mismatched evidence.

Accepts research-only outputs already produced by the real P5 launcher. Never
runs a model, infers a trade size, contacts brokers or asserts profitability.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

EXPECTED = {"tradingagents": "TauricResearch/TradingAgents",
            "ai-trading": "virattt/ai-hedge-fund"}


def assess_research_pair(outputs: list[dict[str, Any]], ticker: str) -> dict[str, Any]:
    if not isinstance(outputs, list) or len(outputs) != 2 or not ticker:
        raise ValueError("expected two real independent research outputs")
    seen: set[str] = set()
    evidence: list[dict[str, str]] = []
    for record in outputs:
        if not isinstance(record, dict):
            raise ValueError("invalid research output")
        portfolio = record.get("portfolio")
        if portfolio not in EXPECTED or portfolio in seen:
            raise ValueError("unknown or repeated research portfolio")
        seen.add(portfolio)
        if record.get("upstream") != EXPECTED[portfolio]:
            raise ValueError("incorrect upstream identity")
        if record.get("status") != "RESEARCH_ONLY":
            raise ValueError("upstream did not produce research")
        if record.get("ticker") != ticker:
            raise ValueError("cross-instrument research cannot be compared")
        if record.get("decision") not in ("BUY", "SELL", "HOLD"):
            raise ValueError("unsupported upstream decision")
        rationale = record.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError("missing research rationale")
        if not record.get("model_config_fingerprint") or not record.get("model_id"):
            raise ValueError("missing model lineage")
        evidence.append({"portfolio": portfolio, "status": "RESEARCH_ONLY",
                         "decision": record["decision"], "upstream": record["upstream"],
                         "model_config_fingerprint": record["model_config_fingerprint"]})
    if seen != set(EXPECTED):
        raise ValueError("missing upstream")
    fingerprints = {e["model_config_fingerprint"] for e in evidence}
    if len(fingerprints) != 1:
        raise ValueError("different configuration revisions")
    return {"ticker": ticker, "evidence": sorted(evidence, key=lambda e: e["portfolio"]),
            "research_pair_status": "RECORDED_NOT_RISK_APPROVED",
            "order_submission_allowed": False, "broker_execution": "DISABLED"}


def main() -> int:
    p = argparse.ArgumentParser(description="Offline, read-only paired-agent evidence check")
    p.add_argument("--input", required=True)
    p.add_argument("--ticker", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    output = Path(a.output)
    if output.exists():
        p.error("refusing to overwrite research evidence")
    entries = json.loads(Path(a.input).read_text(encoding="utf-8"))
    report = assess_research_pair(entries, a.ticker)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("RESEARCH_PAIR=" + report["research_pair_status"])
    print("BROKER_EXECUTION=DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
