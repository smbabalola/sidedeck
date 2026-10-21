"""P5 research-only two-agent CLI. No network broker access and no orders.

An upstream bridge must emit exact JSON {"ticker":"SOFI","decision":"HOLD",
"rationale":"..."}. Decisions are proposals, NOT investment orders.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sidedeck.application.ai_agents import AgentUnavailable, ExternalJsonAgent
from sidedeck.application.p5_model_config import load_model_settings
from sidedeck.application.p5_research_credentials import import_research_env


TRADINGAGENTS_REVISION = "tradingagents==0.7.0"
AI_HEDGE_FUND_REVISION = "aihf==2.5.0+git.ec025370c66cf71d3ea2f2d8f463b5934c1c48af"


def main() -> int:
    parser = argparse.ArgumentParser(description="P5 research-only external agent comparison")
    parser.add_argument("--ticker", default="SOFI")
    parser.add_argument("--models-config", required=True, help="versioned non-secret JSON file")
    parser.add_argument("--env-file", default="", help="explicit local research API keys file")
    parser.add_argument("--tradingagents-python", required=True)
    parser.add_argument("--hedge-fund-bridge", default="",
                        help="approved absolute path to JSON-output research bridge")
    parser.add_argument("--hedge-fund-python", required=True)
    parser.add_argument("--fundamentals-json", default="", help="independent SEC-filed TTM records")
    parser.add_argument("--report", default="", help="optional local-only JSON status report")
    args = parser.parse_args()
    hedge_bridge = args.hedge_fund_bridge or str(
        Path(__file__).resolve().parents[1] / "bridges" / "hedge_fund_bridge.py"
    )
    if not Path(hedge_bridge).is_file():
        print("P5_DECISION=NO-GO (hedge fund bridge missing)")
        return 2
    settings = load_model_settings(args.models_config)
    if args.env_file:
        import_research_env(args.env_file)
    now = datetime.now(timezone.utc)
    agents = (
        ExternalJsonAgent(
            upstream="TauricResearch/TradingAgents", portfolio_id="tradingagents",
            revision=TRADINGAGENTS_REVISION,
            command=(args.tradingagents_python, "-m",
                     "sidedeck.bridges.tradingagents_bridge"),
            model_provider=settings.portfolios["tradingagents"].default.provider,
            model_id=settings.portfolios["tradingagents"].default.model,
        ),
        ExternalJsonAgent(
            upstream="virattt/ai-hedge-fund", portfolio_id="ai-trading",
            revision=AI_HEDGE_FUND_REVISION,
            command=(args.hedge_fund_python, hedge_bridge) + (
                ("--fundamentals-json", args.fundamentals_json)
                if args.fundamentals_json else ()
            ),
            model_provider=settings.portfolios["ai-trading"].default.provider,
            model_id=settings.portfolios["ai-trading"].default.model,
        ),
    )
    output: list[dict[str, Any]] = []
    failures = 0
    for agent in agents:
        try:
            result = agent.run(args.ticker, now)
            output.append({"portfolio": result.portfolio_id, "ticker": result.ticker, "upstream": result.upstream,
                           "status": "RESEARCH_ONLY", "decision": result.decision,
                           "rationale": result.rationale,
                           "strategy_id": "dual-agent-research",
                           "instrument_id": result.instrument_id or "US:" + result.ticker,
                           "market_cutoff": result.market_cutoff.isoformat() if result.market_cutoff else "",
                           "decision_timestamp": result.decision_timestamp.isoformat()
                           if result.decision_timestamp else "",
                           "upstream_version": result.upstream_version,
                           "model_config_fingerprint": settings.fingerprint,
                           "model_provider": agent.model_provider or "",
                           "model_id": agent.model_id or "",
                           "evidence_references": list(result.evidence_references),
                           "abstained": result.abstained, "unavailable": result.unavailable})
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
