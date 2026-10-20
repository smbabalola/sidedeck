"""Offline dual-agent research acceptance: fail closed on missing/mismatched evidence.

Accepts research-only outputs already produced by the real P5 launcher. Never
runs a model, infers a trade size, contacts brokers or asserts profitability.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPECTED = {"tradingagents": "TauricResearch/TradingAgents",
            "ai-trading": "virattt/ai-hedge-fund"}


def assess_research_pair(outputs: list[dict[str, Any]], ticker: str) -> dict[str, Any]:
    if not isinstance(outputs, list) or len(outputs) != 2 or not ticker:
        raise ValueError("expected two real independent research outputs")
    seen: set[str] = set()
    evidence: list[dict[str, str]] = []
    cutoffs: set[str] = set()
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
        if record.get("instrument_id") != "US:" + ticker:
            raise ValueError("cross-instrument research cannot be compared")
        if record.get("decision") not in ("BUY", "SELL", "HOLD"):
            raise ValueError("unsupported upstream decision")
        rationale = record.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError("missing research rationale")
        fingerprint = record.get("configuration_fingerprint") or record.get("model_config_fingerprint")
        if not fingerprint or not record.get("model_id") or not record.get("model_provider"):
            raise ValueError("missing model lineage")
        if not isinstance(record.get("upstream_version"), str) or not record["upstream_version"].strip():
            raise ValueError("missing upstream version")
        if not isinstance(record.get("strategy_id"), str) or not record["strategy_id"].strip():
            raise ValueError("missing strategy identity")
        references = record.get("evidence_references")
        if not isinstance(references, list) or not references or any(
            not isinstance(item, str) or not item.strip() for item in references
        ):
            raise ValueError("missing research provenance references")
        if record.get("abstained") is not False or record.get("unavailable") is not False:
            raise ValueError("abstention or unavailable data cannot become a decision")
        cutoff = _timestamp(record.get("market_cutoff"), "market cutoff")
        decision_time = _timestamp(record.get("decision_timestamp"), "decision timestamp")
        if cutoff > decision_time:
            raise ValueError("decision precedes market cutoff")
        cutoffs.add(cutoff.isoformat())
        evidence.append({"portfolio": portfolio, "status": "RESEARCH_ONLY",
                         "decision": record["decision"], "upstream": record["upstream"],
                         "model_config_fingerprint": str(fingerprint),
                         "market_cutoff": cutoff.isoformat(),
                         "instrument_id": record["instrument_id"]})
    if seen != set(EXPECTED):
        raise ValueError("missing upstream")
    fingerprints = {e["model_config_fingerprint"] for e in evidence}
    if len(fingerprints) != 1:
        raise ValueError("different configuration revisions")
    if len(cutoffs) != 1:
        raise ValueError("different market cutoffs")
    return {"ticker": ticker, "evidence": sorted(evidence, key=lambda e: e["portfolio"]),
            "research_pair_status": "RECORDED_NOT_RISK_APPROVED",
            "order_submission_allowed": False, "broker_execution": "DISABLED"}


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"missing {field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


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
