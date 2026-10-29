"""SD-144 single-command genuine-data strategy qualification, no broker permission.

Runs the existing SD-103 admission engine against explicitly supplied local
historical bundles and produces a small inspectable decision record. Never
creates fabricated data, grants, signatures, or executable orders.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Sequence

from sidedeck.application.sd103_trading_pipeline import (
    REAL_DATA, PipelineConfig, PipelineError, build_context, load_bundle, run_report,
)


def assess_local_bundles(paths: Sequence[Path], *, through: date) -> dict[str, Any]:
    if not paths:
        raise PipelineError("at least one local genuine-data bundle must be supplied")
    loaded = [load_bundle(path) for path in paths]
    ctx, excluded = build_context(
        loaded, basis=REAL_DATA, admission_through=through,
        cfg=PipelineConfig(),
    )
    # An existing pipeline report provides independently inspectable details
    # without reimplementing or relaxing the SD-022/SD-071 admission logic.
    report = run_report(ctx, excluded, now=datetime.now(UTC), mode="run",
                        admission_through=through)
    admitted = report["admitted_strategies"]
    return {
        "schema": "sidedeck.sd144.local-strategy-qualification/1",
        "source_pipeline_schema": report["schema"],
        "admission_through": through.isoformat(),
        "market_data": report["market_data"],
        "excluded_instruments": report["excluded_instruments"],
        "admitted_strategies": admitted,
        "strategy_evidence": report["strategies"],
        "data_freshness": report["data_freshness"],
        "verdict": "RESEARCH_ADMISSION_PRESENT" if admitted else "NO_ADMITTED_STRATEGY",
        "next_action": "SEPARATE_RELEASE_AND_BROKER_EVIDENCE_REVIEW" if admitted
                       else "REVISE_RESEARCH_WITHOUT_RELAXING_ADMISSION",
        "broker_execution_allowed": False,
        "execution_release": "ETORO_DEMO_NOT_RELEASED",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit local genuine-data SWING bundles")
    parser.add_argument("--bundles", nargs="+", type=Path, required=True)
    parser.add_argument("--admission-through", type=date.fromisoformat,
                        default=date(2026, 4, 30))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = assess_local_bundles(args.bundles, through=args.admission_through)
    except (OSError, ValueError, PipelineError) as exc:
        print(json.dumps({"status": "BLOCKED_INPUT", "reason": str(exc)[:300]}))
        return 5
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True, default=str),
                        encoding="utf-8")
    print(json.dumps({"report": str(args.out), "verdict": report["verdict"],
                      "admitted_strategies": report["admitted_strategies"],
                      "excluded_instruments": report["excluded_instruments"],
                      "broker_execution_allowed": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
