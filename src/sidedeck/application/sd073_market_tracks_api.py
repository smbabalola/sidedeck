"""SD-073 read-only dashboard summary for market-wide DAY / SWING / POSITION tracks.

Combines code-derived configuration (track scoring, data-source selection,
scheduler cadence) with optional local evidence summaries from SD-075A (universe)
and SD-075B (price pilot). Local files are read through a strict allowlist of
numeric/string fields; anything malformed is reported ``UNAVAILABLE``. The
payload never carries credentials, raw data, account values or order controls,
and ``execution_enabled`` is always ``False``.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sidedeck.application.sd066_data_capability import TRACK_DATA_NEEDS, select_sources
from sidedeck.application.sd067_market_scanner import DEFAULT_SCORING
from sidedeck.application.sd068_track_scheduler import (
    DEFAULT_JOBS,
    NEW_YORK,
    SchedulerError,
    slots_for,
)
from sidedeck.application.sd070_research_signal import TRACK_HORIZONS
from decimal import Decimal

from sidedeck.application.sd071_decision_engine import EXECUTION_PERMISSION
from sidedeck.application.sd072_track_risk_limits import TrackLimits

# Research configuration for simulation and display. Not an execution authorization and
# not a capital allocation: virtual capital stays NOT_ALLOCATED until the owner decides.
TRACK_RISK_BUDGETS: dict[str, dict[str, str | int]] = {
    "DAY": {"risk_per_trade_pct": "0.005", "max_positions": 3, "max_drawdown_pct": "0.05",
            "max_daily_loss_pct": "0.02", "max_orders_per_day": 6,
            "exit_policy": "SAME_SESSION_LIQUIDATION"},
    "SWING": {"risk_per_trade_pct": "0.01", "max_positions": 5, "max_drawdown_pct": "0.10",
              "max_daily_loss_pct": "0.03", "max_orders_per_day": 4,
              "exit_policy": "STOP_OR_TIME_EXIT_15_SESSIONS"},
    "POSITION": {"risk_per_trade_pct": "0.01", "max_positions": 8, "max_drawdown_pct": "0.15",
                 "max_daily_loss_pct": "0.04", "max_orders_per_day": 2,
                 "exit_policy": "STOP_OR_THESIS_INVALIDATION"},
}
for _track, _b in TRACK_RISK_BUDGETS.items():  # validated by the same limits used in SD-072
    TrackLimits(_track, Decimal(str(_b["max_drawdown_pct"])),
                Decimal(str(_b["max_daily_loss_pct"])), int(_b["max_orders_per_day"]))

_COVERAGE_KEYS = ("COVERED", "PARTIALLY_COVERED", "UNAVAILABLE")


def _next_slot(job_id: str, now: datetime) -> str:
    job = next(j for j in DEFAULT_JOBS if j.job_id == job_id)
    if not job.enabled or job.requires_authorization:
        return "DISABLED_PENDING_AUTHORIZATION"
    day = now.astimezone(NEW_YORK).date()
    for offset in range(0, 10):
        try:
            slots = slots_for(job, day + timedelta(days=offset))
        except SchedulerError:
            return "CALENDAR_NOT_COVERED"
        upcoming = [s for s in slots if s > now]
        if upcoming:
            return upcoming[0].isoformat()
    return "NONE_WITHIN_10_DAYS"


def _read_json(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def universe_status(path: str | None) -> dict[str, Any]:
    data = _read_json(path)
    count = data.get("merged_instruments") if data else None
    basis = data.get("history_basis") if data else None
    retrieved = data.get("retrieved_at") if data else None
    if not (type(count) is int and count >= 0 and isinstance(basis, str)
            and isinstance(retrieved, str)):
        return {"status": "UNAVAILABLE", "reason": "no verified SD-075A snapshot loaded"}
    return {"status": "SNAPSHOT_LOADED", "instruments": count, "history_basis": basis[:120],
            "retrieved_at": retrieved[:40], "tradability": "NOT_ASSESSED"}


def price_coverage_status(path: str | None) -> dict[str, Any]:
    data = _read_json(path)
    counts = data.get("coverage_counts") if data else None
    if not (isinstance(counts, dict) and all(type(counts.get(k)) is int for k in _COVERAGE_KEYS)):
        return {"status": "UNAVAILABLE", "reason": "no SD-075B price pilot summary loaded"}
    bench = data.get("benchmark_status") if data else None
    return {"status": "PILOT_LOADED", "counts": {k: counts[k] for k in _COVERAGE_KEYS},
            "benchmark_status": bench if isinstance(bench, str) else "UNAVAILABLE",
            "acceptance": "RESEARCH_DATA_ONLY"}


def market_tracks_summary(universe_path: str | None = None, pilot_path: str | None = None,
                          *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    tracks = []
    for track in ("DAY", "SWING", "POSITION"):
        cfg = DEFAULT_SCORING[track]
        selection = select_sources(TRACK_DATA_NEEDS[track])
        jobs = [j for j in DEFAULT_JOBS if j.track == track]
        tracks.append({
            "track": track,
            "mode": "RESEARCH_ONLY",
            "horizon_trading_days": list(TRACK_HORIZONS[track]),
            "data_status": selection.status,
            "usable_sources": list(selection.usable),
            "filters": {"min_price": str(cfg.min_price), "min_dollar_adv": str(cfg.min_dollar_adv),
                        "min_sessions": cfg.min_sessions,
                        "spread_required": cfg.max_spread_bps is not None},
            "shortlist_sizes": {"quant": cfg.quant_size, "research": cfg.research_size},
            "jobs": [{"job_id": j.job_id, "next_run_utc": _next_slot(j.job_id, now)} for j in jobs],
            "risk_budget": {**TRACK_RISK_BUDGETS[track], "virtual_capital": "NOT_ALLOCATED",
                            "basis": "RESEARCH_CONFIGURATION_NOT_AUTHORIZATION"},
            "execution": "DISABLED",
        })
    return {
        "schema_version": 1,
        "execution_enabled": False,
        "generated_at": now.isoformat(),
        "universe": universe_status(universe_path),
        "price_coverage": price_coverage_status(pilot_path),
        "tracks": tracks,
        "decision_engine": {"execution_permission": EXECUTION_PERMISSION,
                            "agent_only_cap": "WATCHLIST"},
    }
