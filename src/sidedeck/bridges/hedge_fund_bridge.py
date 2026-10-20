"""Genuine AI Hedge Fund v2 persona research bridge, without its paper broker.

Install https://github.com/virattt/ai-hedge-fund separately. Uses upstream
BuffettAgent.predict() with either SideDeck's local SEC fundamentals client
(--fundamentals-json, no Financial Datasets access) or upstream FDClient.
Never advance(), paper tick or order tools.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import sys
from importlib import import_module

from sidedeck.bridges.upstream_identity import resolve_hedge_fund_identity


def _upstream_version() -> str:
    # The upstream distribution is "aihf"; editable installs are pinned to a
    # clean git commit. Fails closed rather than inventing a version.
    return str(resolve_hedge_fund_identity()["identity"])


def classify_signal(value: object, *, abstained: bool = False) -> str:
    if abstained:
        raise ValueError("upstream abstained; cannot claim a HOLD recommendation")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("non-numeric upstream conviction")
    numeric = float(value)
    if not math.isfinite(numeric) or not -1 <= numeric <= 1:
        raise ValueError("invalid upstream conviction")
    if numeric > 0:
        return "BUY"
    if numeric < 0:
        return "SELL"
    return "HOLD"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--fundamentals-json", default="")
    args = parser.parse_args()
    try:
        from sidedeck.application.p5_model_config import ModelChoice
        choice = ModelChoice(args.provider, args.model)
        if choice.provider not in ("openai", "anthropic", "google"):
            raise ValueError("provider is not mapped to AI Hedge Fund v2")
        version = _upstream_version()
        llm_factory = import_module("hedge_fund.llm")
        fd_module = import_module("hedge_fund.data.client")
        buffett_module = import_module("hedge_fund.signals.buffett")
        client = llm_factory.make_llm(choice.model)
        with contextlib.redirect_stdout(io.StringIO()):
            if args.fundamentals_json:
                from sidedeck.bridges.filed_fundamentals import LocalFiledDataClient
                data_client = LocalFiledDataClient(args.fundamentals_json)
                signal = buffett_module.BuffettAgent(llm=client).predict(
                    args.ticker, args.as_of, data_client,
                )
            else:
                with fd_module.FDClient() as data_client:
                    signal = buffett_module.BuffettAgent(llm=client).predict(
                        args.ticker, args.as_of, data_client,
                    )
        signal_metadata = getattr(signal, "metadata", {})
        if not isinstance(signal_metadata, dict):
            raise ValueError("invalid signal metadata")
        decision = classify_signal(signal.value, abstained=signal_metadata.get("abstained") is True)
        rationale = getattr(signal, "reasoning", "")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError("empty research thesis")
        print(json.dumps({"ticker": args.ticker, "instrument_id": "US:" + args.ticker,
                          "market_cutoff": args.as_of + "T00:00:00+00:00",
                          "decision": decision, "status": "RESEARCH_ONLY",
                          "abstained": False, "unavailable": False,
                          "upstream_version": version,
                          "evidence_references": ["AI Hedge Fund BuffettAgent runtime"],
                          "rationale": rationale[:2000]}))
        return 0
    except (ImportError, ValueError, RuntimeError, OSError) as exc:
        print(f"AI Hedge Fund research unavailable: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
