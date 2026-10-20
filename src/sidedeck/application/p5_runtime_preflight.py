"""Local, no-network P5 upstream runtime readiness check.

Does not display credentials or run an AI provider. Run in each isolated Python
environment used for the corresponding upstream package.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path

from sidedeck.application.p5_model_config import load_model_settings


_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "ollama": None,
}


def assess_local_runtime(
    agent: str, provider: str, fundamentals_json: str | None = None,
) -> dict[str, str]:
    if agent not in ("tradingagents", "ai-trading"):
        raise ValueError("unknown agent")
    if provider not in _KEYS:
        raise ValueError("unknown provider")
    if fundamentals_json and agent != "ai-trading":
        raise ValueError("local fundamentals apply only to the AI Hedge Fund bridge")
    package = "tradingagents" if agent == "tradingagents" else "hedge_fund"
    installed = importlib.util.find_spec(package) is not None
    key_name = _KEYS[provider]
    credential_present = key_name is None or bool(os.environ.get(key_name))
    result = {
        "portfolio": agent, "upstream_package": package,
        "runtime_package": "FOUND" if installed else "MISSING",
        "model_credential": "PRESENT" if credential_present else "MISSING",
    }
    data_ready = True
    if agent == "ai-trading" and fundamentals_json:
        # Upstream BuffettAgent reads only the injected data client for a daily
        # cutoff, so local SEC fundamentals replace Financial Datasets entirely.
        found = Path(fundamentals_json).is_file()
        data_ready = found
        result.update(fundamentals_source="LOCAL_SEC_FILE",
                      fundamentals_credential="NOT_REQUIRED",
                      fundamentals_file="FOUND" if found else "MISSING")
    elif agent == "ai-trading":
        data_ready = bool(os.environ.get("FINANCIAL_DATASETS_API_KEY"))
        result.update(fundamentals_source="FINANCIAL_DATASETS",
                      fundamentals_credential="PRESENT" if data_ready else "MISSING")
    else:
        result["fundamentals_credential"] = "NOT_CHECKED"
    # Deliberately conservative; never contacts providers.
    ready = installed and credential_present and data_ready
    result["offline_preflight"] = "READY_TO_ATTEMPT" if ready else "BLOCKED"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="P5 local readiness without API requests")
    parser.add_argument("--models-config", default="config/p5_models.example.json")
    parser.add_argument("--agent", required=True, choices=("tradingagents", "ai-trading"))
    parser.add_argument("--fundamentals-json", default="",
                        help="local SEC fundamentals file (AI Hedge Fund only)")
    args = parser.parse_args()
    settings = load_model_settings(args.models_config)
    choice = settings.portfolios[args.agent].default
    result = assess_local_runtime(args.agent, choice.provider,
                                  fundamentals_json=args.fundamentals_json or None)
    result["model"] = choice.model
    result["provider"] = choice.provider
    result["configuration_revision"] = settings.revision
    print(json.dumps(result, sort_keys=True))
    print("BROKER_EXECUTION=DISABLED")
    return 0 if result["offline_preflight"] == "READY_TO_ATTEMPT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
