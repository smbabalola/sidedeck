"""Isolated TradingAgents bridge: run in an upstream-only Python environment.

Usage: python -m sidedeck.bridges.tradingagents_bridge --ticker SOFI --as-of 2026-10-19
Output ONLY a JSON decision on stdout. Never send order to broker.
"""
from __future__ import annotations

import argparse
import contextlib
import io
from importlib import import_module
import json
import re
import sys


def extract_action(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("TradingAgents returned a non-text decision")
    # Some versions return 'FINAL TRANSACTION PROPOSAL: BUY', others bare BUY.
    # Require exactly one unambiguous action, never infer from generic prose.
    text = value.strip().upper()
    if text in ("BUY", "SELL", "HOLD"):
        return text
    match = re.fullmatch(r"(?:FINAL (?:TRADE|TRANSACTION) (?:PROPOSAL|DECISION):\s*)(BUY|SELL|HOLD)[.!]?", text)
    if match:
        return match.group(1)
    raise ValueError("TradingAgents decision is not unambiguous")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args()
    try:
        # Dynamically load the separately installed upstream research package.
        config_module = import_module("tradingagents.default_config")
        graph_module = import_module("tradingagents.graph.trading_graph")
        config = config_module.DEFAULT_CONFIG.copy()
        # The installed TradingAgents upstream owns data/LLM selection.
        # Upstream may print progress; keep stdout exclusively machine-readable JSON.
        with contextlib.redirect_stdout(io.StringIO()):
            graph = graph_module.TradingAgentsGraph(debug=False, config=config)
            _state, final = graph.propagate(args.ticker, args.as_of)
        action = extract_action(final)
        print(json.dumps({"ticker": args.ticker, "decision": action,
                          "rationale": f"TradingAgents returned {action}; see isolated upstream logs."}))
        return 0
    except (ImportError, ValueError, RuntimeError, OSError) as exc:
        print(f"TradingAgents research unavailable: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
