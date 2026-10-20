"""Offline dual-agent research-run planning and authorization gate."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime\nfrom decimal import Decimal, InvalidOperation


class ResearchRunBlocked(RuntimeError):
    pass


@dataclass(frozen=True)
class ResearchRunPlan:
    run_id: str
    instrument_id: str
    cutoff: datetime
    max_provider_calls: int
    max_cost_usd: str
    broker_execution: str = "DISABLED"


def plan_run(run_id: str, instrument_id: str, cutoff: datetime, *, max_provider_calls: int = 1,
             max_cost_usd: str = "0") -> ResearchRunPlan:
    if not run_id.strip() or not instrument_id.startswith("US:"):
        raise ResearchRunBlocked("run identity is invalid")
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ResearchRunBlocked("cutoff must be timezone-aware")
    if max_provider_calls < 0:
        raise ResearchRunBlocked("provider-call budget cannot be negative")
    return ResearchRunPlan(run_id, instrument_id, cutoff, max_provider_calls, max_cost_usd)


def dry_run(plan: ResearchRunPlan) -> dict[str, object]:
    return {"run_id": plan.run_id, "instrument_id": plan.instrument_id,
            "market_cutoff": plan.cutoff.isoformat(), "provider_calls": 0,
            "status": "DRY_RUN_READY", "execution_authorized": False,
            "broker_execution": "DISABLED"}


def require_owner_authorization(plan: ResearchRunPlan, authorized: bool) -> None:
    if not authorized:
        raise ResearchRunBlocked("owner authorization required before provider calls")
