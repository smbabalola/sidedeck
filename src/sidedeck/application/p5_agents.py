"""P5 research-only two-agent CLI. No network broker access and no orders.

An upstream bridge must emit exact JSON {"ticker":"SOFI","decision":"HOLD",
"rationale":"..."}. Decisions are proposals, NOT investment orders.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from sidedeck.application.ai_agents import AgentUnavailable, ExternalJsonAgent
from sidedeck.application.p5_model_config import load_model_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="P5 research-only external agent comparison")
    parser.add_argument("--ticker", default="SOFI")
    parser.add_argument("--models-config", required=True, help="versioned non-secret JSON file")
    parser.add_argument("--tradingagents-python", required=True)
    parser.add_argument("--hedge-fund-bridge", required=True,
                        help="approved absolute path to JSON-output research bridge")
    parser.add_argument("--hedge-fund-python", required=True)
    parser.add_argument("--report", default="", help="optional local-only JSON status report")
    args = parser.parse_args()
    if not Path(args.hedge_fund_bridge).is_file():
        print("P5_DECISION=NO-GO (hedge fund bridge missing)")
        return 2
    settings = load_model_settings(args.models_config)
    now = datetime.now(timezone.utc)
    agents = (
        ExternalJsonAgent(
            upstream="TauricResearch/TradingAgents", portfolio_id="tradingagents",
            revision="upstream-unpinned-local",
            command=(args.tradingagents_python, "-m",
                     "sidedeck.bridges.tradingagents_bridge"),
            model_provider=settings.portfolios["tradingagents"].default.provider,
            model_id=settings.portfolios["tradingagents"].default.model,
        ),
        ExternalJsonAgent(
            upstream="virattt/ai-hedge-fund", portfolio_id="ai-trading",
            revision="upstream-unpinned-local",
            command=(args.hedge_fund_python, args.hedge_fund_bridge),
            model_provider=settings.portfolios["ai-trading"].default.provider,
            model_id=settings.portfolios["ai-trading"].default.model,
        ),
    )
    output: list[dict[str, str]] = []
    failures = 0
    for agent in agents:
        try:
            result = agent.run(args.ticker, now)
            output.append({"portfolio": result.portfolio_id, "upstream": result.upstream,
                           "status": "RESEARCH_ONLY", "decision": result.decision,
                           "rationale": result.rationale,
                           "model_config_fingerprint": settings.fingerprint,
                           "model_provider": agent.model_provider or "",
                           "model_id": agent.model_id or ""})
        except (AgentUnavailable, ValueError) as exc:
            failures += 1
            output.append({"portfolio": agent.portfolio_id, "upstream": agent.upstream,
                           "status": "BLOCKED", "reason": type(exc).__name__})
    if args.report:
        target = Path(args.report).resolve()
        if target.exists():
            print("P5_DECISION=NO-GO (refusing to overwrite report)")
            return 2
        target.write_text(json.dumps(output, indent=2), encoding="utf-8")
    for item in output:
        print(json.dumps(item))
    print("BROKER_EXECUTION=DISABLED")
    print("P5_DECISION=" + ("NO-GO" if failures else "RESEARCH_OUTPUTS_PRESENT_NOT_RISK_APPROVED"))
    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
