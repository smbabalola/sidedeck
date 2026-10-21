"""Offline dual-agent research-run planning and authorization gate."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256


class ResearchRunBlocked(RuntimeError):
    pass


_ISSUED_AUTHORIZATIONS: set[str] = set()


@dataclass(frozen=True)
class ResearchRunPlan:
    run_id: str
    instrument_id: str
    cutoff: datetime
    max_provider_calls: int
    max_cost_usd: str
    broker_execution: str = "DISABLED"


@dataclass
class ProviderAuthorization:
    """Single-use offline authorization lease; it does not call a provider."""

    plan_digest: str
    expires_at: datetime
    max_calls: int
    max_cost_usd: Decimal
    authorization_id: str
    consumed_calls: int = 0
    consumed_cost_usd: Decimal = Decimal("0")

    def consume(self, *, estimated_cost_usd: str = "0") -> None:
        if self.consumed_calls >= self.max_calls or datetime.now(timezone.utc) >= self.expires_at:
            raise ResearchRunBlocked("provider authorization is exhausted or expired")
        try:
            amount = Decimal(estimated_cost_usd)
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ResearchRunBlocked("invalid provider call cost") from exc
        if not amount.is_finite() or amount < 0 or self.consumed_cost_usd + amount > self.max_cost_usd:
            raise ResearchRunBlocked("provider call exceeds authorized USD budget")
        self.consumed_calls += 1
        self.consumed_cost_usd += amount


def plan_run(run_id: str, instrument_id: str, cutoff: datetime, *, max_provider_calls: int = 1,
             max_cost_usd: str = "0") -> ResearchRunPlan:
    if not run_id.strip() or not instrument_id.startswith("US:"):
        raise ResearchRunBlocked("run identity is invalid")
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ResearchRunBlocked("cutoff must be timezone-aware")
    if (isinstance(max_provider_calls, bool) or not isinstance(max_provider_calls, int)
            or max_provider_calls < 0):
        raise ResearchRunBlocked("provider-call budget must be a nonnegative integer")
    try:
        cost = Decimal(max_cost_usd)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ResearchRunBlocked("invalid USD budget") from exc
    if not cost.is_finite() or cost < 0:
        raise ResearchRunBlocked("USD budget must be finite and nonnegative")
    return ResearchRunPlan(run_id, instrument_id, cutoff, max_provider_calls, max_cost_usd)


def dry_run(plan: ResearchRunPlan) -> dict[str, object]:
    return {"run_id": plan.run_id, "instrument_id": plan.instrument_id,
            "market_cutoff": plan.cutoff.isoformat(), "provider_calls": 0,
            "status": "DRY_RUN_READY", "execution_authorized": False,
            "broker_execution": "DISABLED"}


def require_owner_authorization(plan: ResearchRunPlan, authorized: bool) -> ProviderAuthorization:
    if not authorized:
        raise ResearchRunBlocked("owner authorization required before provider calls")
    if plan.max_provider_calls == 0 or Decimal(plan.max_cost_usd) <= 0:
        raise ResearchRunBlocked("positive explicit provider-call and USD budgets required")
    authorization_id = f"owner:{plan.run_id}"
    if authorization_id in _ISSUED_AUTHORIZATIONS:
        raise ResearchRunBlocked("owner authorization has already been issued for this run")
    digest = sha256(f"{plan.run_id}|{plan.instrument_id}|{plan.cutoff.isoformat()}".encode()).hexdigest()
    _ISSUED_AUTHORIZATIONS.add(authorization_id)
    return ProviderAuthorization(
        plan_digest=digest, expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        max_calls=plan.max_provider_calls, max_cost_usd=Decimal(plan.max_cost_usd),
        authorization_id=authorization_id,
    )
