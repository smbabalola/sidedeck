"""Inspect an installed AI Hedge Fund package without initializing models or trading.

Run under the independently installed upstream Python environment. No API calls.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import sys
from typing import Any


def probe() -> dict[str, Any]:
    required = {
        "hedge_fund.signals.buffett": ("BuffettAgent",),
        "hedge_fund.data.models": ("FinancialMetrics",),
        "hedge_fund.data.client": ("FDClient",),
        "hedge_fund.llm": ("make_llm",),
    }
    found: dict[str, Any] = {}
    for module_name, names in required.items():
        try:
            spec = importlib.util.find_spec(module_name)
        except (ImportError, ModuleNotFoundError, AttributeError):
            spec = None
        if spec is None:
            found[module_name] = {"available": False, "symbols": {}}
            continue
        try:
            module = importlib.import_module(module_name)
        except (ImportError, ModuleNotFoundError, AttributeError) as exc:
            found[module_name] = {"available": False, "error": type(exc).__name__, "symbols": {}}
            continue
        symbols: dict[str, bool] = {name: hasattr(module, name) for name in names}
        found[module_name] = {"available": True, "symbols": symbols}
        if module_name == "hedge_fund.data.models" and symbols["FinancialMetrics"]:
            cls = getattr(module, "FinancialMetrics")
            fields = getattr(cls, "model_fields", None)
            if isinstance(fields, dict):
                found[module_name]["field_names"] = sorted(fields)
    compatible = all(
        item["available"] and all(item["symbols"].values()) for item in found.values()
    )
    return {
        "installed_upstream_legacy_bridge_contract": "PRESENT" if compatible else "MISSING",
        "modules": found,
        "agent_research_run": "NOT_ATTEMPTED",
        "buffett_ready": False, "broker_execution": "DISABLED",
    }


def main() -> int:
    argparse.ArgumentParser(description="No-cost AI Hedge Fund installed interface probe").parse_args()
    print(json.dumps(probe(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
