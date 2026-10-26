"""Read-only Day Trader module summary for the local workstation.

This endpoint deliberately reports capability and permission state only. It does not run the
upstream skills, read credentials, fetch data, create proposals, or mutate a ledger.
"""
from __future__ import annotations

from typing import Any

from sidedeck.modules.day_trader.manifest import MODULE_BOOK, SKILLS, SOURCE_VERSION, UPSTREAM, resolve
from sidedeck.application.sd114_day_trader_runs import day_trader_run_summary


def day_trader_summary(runs_path: str = "data/day-trader-runs.sqlite3") -> dict[str, Any]:
    """Return a sanitized, fail-closed module status document."""
    verification = resolve()
    return {
        "schema_version": 1, "module": "DAY_TRADER", "book": MODULE_BOOK,
        "mode": "RESEARCH_ONLY", "enabled": True, "execution_enabled": False,
        "broker_execution": "DISABLED", "data_status": "NO_APPROVED_INTRADAY_DATA",
        "performance_status": "NOT_ASSESSED",
        "source": {"name": UPSTREAM["name"], "version": UPSTREAM["version"],
                   "commit": UPSTREAM["commit"], "license": UPSTREAM["license"],
                   "module_version": SOURCE_VERSION, "verification": verification.status,
                   "origin": verification.source},
        "capabilities": [
            {"id": spec.name, "role": spec.role, "network_hosts_blocked": list(spec.hosts),
             "claude_only_not_used": spec.claude_only}
            for spec in SKILLS.values()
        ],
        **day_trader_run_summary(runs_path),
        "owner_actions": [
            "Provide approved, provenance-tagged intraday data before research acceptance.",
            "Review strategy-admission evidence before any allocation decision.",
        ],
        "limitations": [
            "Time Machine output is a scenario estimate, not a forecast or OOS evidence.",
            "Upstream broker tickets are never forwarded; SideDeck gateway and owner release remain required.",
        ],
    }
