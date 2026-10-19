"""Inspect an installed AI Hedge Fund package without initializing models or trading.

Run under the independently installed upstream Python environment. No API calls.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import inspect
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
    # Inspect required constructor fields and the Buffett snapshot API without invoking it.
    model_info = found.get("hedge_fund.data.models", {})
    if model_info.get("available") and model_info.get("symbols", {}).get("FinancialMetrics"):
        model_cls = getattr(importlib.import_module("hedge_fund.data.models"), "FinancialMetrics")
        fields = getattr(model_cls, "model_fields", {})
        model_info["required_fields"] = sorted(name for name, field in fields.items() if field.is_required())
    agent_info = found.get("hedge_fund.signals.buffett", {})
    if agent_info.get("available") and agent_info.get("symbols", {}).get("BuffettAgent"):
        agent_cls = getattr(importlib.import_module("hedge_fund.signals.buffett"), "BuffettAgent")
        agent_info["snapshot_method_available"] = hasattr(agent_cls, "build_snapshot")
        if agent_info["snapshot_method_available"]:
            agent_info["snapshot_signature"] = str(inspect.signature(agent_cls.build_snapshot))
        agent_info["predict_signature"] = str(inspect.signature(agent_cls.predict))
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
