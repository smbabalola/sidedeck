"""SD-097 read-only UK Markets summary for ``/api/market/uk`` (loopback dashboard).

Three sections, each with its own provenance that is never upgraded:

* ``calendar`` and ``tracks`` — XLON sessions, hours, DST-correct UTC times, the
  calendar's corroboration status, and per-track data status / next UK jobs;
* ``genuine`` — the SD-098 import of owner-supplied licensed files (``REAL_DATA``
  only when an import succeeded with that declared basis; otherwise ``UNAVAILABLE``)
  and the candidate names' abstentions;
* ``fixture`` / ``simulation`` — read from a saved SD-096 report, accepted only if it
  says ``SYNTHETIC_FIXTURE`` / ``SIMULATION``; anything else is refused, never relabelled.

No network, credentials, broker access or write path. Values from files are
allowlisted and length-bounded before they reach the browser.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sidedeck.application.sd066_data_capability import UK_TRACK_DATA_NEEDS, select_sources
from sidedeck.application.sd068_track_scheduler import UK_DEFAULT_JOBS, slots_for
from sidedeck.application.sd089_exchange_calendar import (
    UK_HALF_DAYS,
    UK_UNCORROBORATED_HALF_DAYS,
    XLON,
    CalendarError,
)
from sidedeck.application.sd090_uk_market import UK_CANDIDATE_WATCHLIST
from sidedeck.application.sd096_uk_acceptance import genuine_data_inventory

MAX_TEXT = 200
MAX_ROWS = 300


def _t(value: Any) -> str:
    return str(value)[:MAX_TEXT]


def _num(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    try:
        float(text)
    except ValueError:
        return None
    return text[:40]


def _calendar(now: datetime) -> dict[str, Any]:
    today = XLON.local_date(now)
    out: dict[str, Any] = {
        "id": XLON.calendar_id, "timezone": XLON.timezone, "continuous_hours_local": "08:00-16:30",
        "half_day_close_local": "12:30", "source_status": XLON.source_status,
        "corroboration": "PENDING_SD094A_AND_LSE_NOTICE",
        "half_days_uncorroborated": sorted(d.isoformat() for d in UK_HALF_DAYS
                                           if d >= today - timedelta(days=400)),
        "rule_only_half_days": sorted(d.isoformat() for d in UK_UNCORROBORATED_HALF_DAYS),
    }
    try:
        session = XLON.session(today)
        out["status_now"] = "OPEN" if XLON.is_open(now) else "CLOSED"
        out["today"] = {
            "date": today.isoformat(), "is_session": session is not None,
            "open_utc": session.open_utc.isoformat() if session else None,
            "close_utc": session.close_utc.isoformat() if session else None,
            "early_close": bool(session and session.early_close),
            "closure_reason": XLON.closures.get(today),
        }
        nxt = today
        upcoming: list[dict[str, Any]] = []
        while len(upcoming) < 5:
            nxt = XLON.next_session(nxt)
            s = XLON.session(nxt)
            assert s is not None
            upcoming.append({"date": nxt.isoformat(), "open_utc": s.open_utc.isoformat(),
                             "close_utc": s.close_utc.isoformat(), "early_close": s.early_close})
        out["next_sessions"] = upcoming
        out["last_completed_session"] = XLON.last_completed_session(now).isoformat()
    except CalendarError:
        out.update(status_now="CALENDAR_NOT_COVERED", today=None, next_sessions=[],
                   last_completed_session=None)
    return out


def _tracks(now: datetime) -> list[dict[str, Any]]:
    tracks = []
    for track, need in UK_TRACK_DATA_NEEDS.items():
        selection = select_sources(need)
        jobs = []
        for job in UK_DEFAULT_JOBS:
            if job.track != track:
                continue
            nxt = None
            try:
                day = XLON.local_date(now)
                for offset in range(0, 10):
                    slots = [s for s in slots_for(job, day + timedelta(days=offset)) if s > now]
                    if slots:
                        nxt = slots[0].isoformat()
                        break
            except Exception:  # noqa: BLE001 - an uncovered calendar year shows no next run
                nxt = None
            jobs.append({"job_id": job.job_id, "enabled": job.enabled, "next_run_utc": nxt})
        tracks.append({"track": track, "data_status": selection.status,
                       "usable_sources": list(selection.usable), "mode": "RESEARCH_ONLY",
                       "execution": "DISABLED", "jobs": jobs})
    return tracks


def _genuine(data_dir: str | None, now: datetime) -> dict[str, Any]:
    base: dict[str, Any] = {"provenance": "UNAVAILABLE", "status": "NO_GENUINE_UK_DATA",
                            "identities": [], "candidates": [], "rejected": 0, "warnings": 0,
                            "memberships": []}
    if not data_dir:
        base["candidates"] = [{"name": c.name, "proposed_tidm": c.proposed_tidm,
                               "result": "ABSTAIN", "reasons": ["NO_SOURCED_RECORD",
                                                                "NO_APPROVED_MARKET_DATA"]}
                              for c in UK_CANDIDATE_WATCHLIST]
        base["blocker"] = "no UK data directory configured"
        return base
    inv = genuine_data_inventory(Path(data_dir), now)
    imp = inv["import"]
    real = inv.get("real_scan")
    base.update(
        status=_t(inv["status"]), blocker=None if inv["blocker"] is None else _t(inv["blocker"]),
        cutoff=_t(inv["cutoff"]), import_status=_t(imp["status"]),
        data_basis_attestation=imp.get("data_basis_attestation"),
        rejected=len(imp["rejected"]), warnings=len(imp["warnings"]),
        candidates=[{"name": _t(c["name"]), "proposed_tidm": _t(c["proposed_tidm"]),
                     "result": _t(c["result"]), "reasons": [_t(r) for r in c["reasons"]]}
                    for c in inv["candidates"]],
    )
    if real is not None and real.get("data_basis") == "REAL_DATA":
        base["provenance"] = "REAL_DATA"
        base["identities"] = [_identity(i) for i in real.get("identities", [])][:MAX_ROWS]
        base["scan"] = _scan(real)
        base["memberships"] = [
            {"canonical_id": _t(m["canonical_id"]), "index_id": _t(m["index_id"]),
             "start": _t(m["start"]), "end": None if m["end"] is None else _t(m["end"]),
             "basis": _t(m["basis"])}
            for m in inv.get("index_memberships") or []][:MAX_ROWS]
    return base


def _identity(i: dict[str, Any]) -> dict[str, Any]:
    return {k: (None if i.get(k) is None else _t(i.get(k))) for k in (
        "canonical_id", "tidm", "isin", "name", "quote_unit", "source_id", "source_unit",
        "divisor", "last_bar", "retrieved_at", "data_basis")} | {
        "last_close_gbp": _num(i.get("last_close_gbp"))}


def _scan(s: dict[str, Any]) -> dict[str, Any]:
    rankings = {}
    for track in ("DAY", "SWING", "POSITION"):
        rows = s.get("rankings", {}).get(track, [])[:MAX_ROWS]
        rankings[track] = [{"rank": int(r["rank"]), "canonical_id": _t(r["canonical_id"]),
                            "score": _num(r.get("score"))} for r in rows]
    filtered: dict[str, dict[str, int]] = {}
    for track, rows in (s.get("filtered") or {}).items():
        counts: dict[str, int] = {}
        for _, reason in rows:
            counts[_t(reason)] = counts.get(_t(reason), 0) + 1
        filtered[_t(track)] = counts
    return {
        "cutoff": _t(s.get("cutoff")), "universe": int(s.get("universe", 0)),
        "scanned": int(s.get("scanned", 0)),
        "excluded": [[_t(a), _t(b)] for a, b in (s.get("excluded") or [])][:MAX_ROWS],
        "scan_exclusions": {_t(k): int(v) for k, v in (s.get("scan_exclusions") or {}).items()},
        "rankings": rankings, "filtered": filtered,
        "decision_counts": {_t(k): int(v) for k, v in (s.get("decision_counts") or {}).items()},
        "signals": len(s.get("signals") or []), "acceptance": _t(s.get("acceptance")),
    }


def _report(path: str | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    if not path:
        return None, None, "no saved SD-096 report configured"
    target = Path(path)
    if not target.is_file() or target.is_symlink():
        return None, None, "SD-096 report not generated yet"
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        fx, sim = data["fixture_scan"], data["simulated_trade"]
        if fx.get("data_basis") != "SYNTHETIC_FIXTURE" or sim.get("label") != "SIMULATION":
            return None, None, "report provenance invalid; refused"
        fixture = {"provenance": "SYNTHETIC_FIXTURE", **_scan(fx),
                   "identities": [_identity(i) for i in fx.get("identities", [])][:MAX_ROWS],
                   "listing_rejections": [[_t(a), _t(b)] for a, b in
                                          fx.get("listing_rejections", [])][:MAX_ROWS]}
        rec = sim["final_reconciliation"]
        simulation = {
            "provenance": "SIMULATION", "fill_basis": "SIMULATED_LOCAL",
            "intent_source": _t(sim.get("intent_source")),
            "instrument": {k: _t(v) for k, v in sim["instrument"].items()},
            "gbx_to_gbp": {k: _t(v) for k, v in sim["gbx_to_gbp"].items()},
            "entry": {k: (None if v is None else _t(v)) for k, v in sim["entry"].items()},
            "exit": {k: (None if v is None else _t(v)) for k, v in sim["exit"].items()},
            "reconciliation": {"status": _t(rec["status"]), "cash_gbp": _num(rec["cash_gbp"]),
                               "realized_pnl_gbp": _num(rec["realized_pnl_gbp"]),
                               "fees_gbp": _num(rec["fees_gbp"]),
                               "open_positions": int(rec["open_positions"])},
            "scenarios": {_t(k): _t(v) for k, v in (data.get("scenarios") or {}).items()},
        }
        return fixture, simulation, None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None, None, "report unreadable or malformed"


def uk_markets_summary(data_dir: str | None, report_path: str | None,
                       now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    fixture, simulation, report_reason = _report(report_path)
    return {
        "schema_version": 1, "market": "UK", "exchange": "LSE", "price_unit": "GBP",
        "execution_enabled": False, "generated_at": now.astimezone(UTC).isoformat(),
        "calendar": _calendar(now), "tracks": _tracks(now), "genuine": _genuine(data_dir, now),
        "fixture": fixture, "simulation": simulation, "report_reason": report_reason,
        "authorizations": {"A": "NOT_AUTHORIZED", "B": "NOT_AUTHORIZED", "C": "NOT_AUTHORIZED"},
        "evidence": {
            "provenance": "NO_DATA",
            "admitted_uk_strategies": 0,
            "agents": "NOT_RUN (SD-008 blocked: no owner-approved provider call)",
            "note": "UK signals stay WATCHLIST/ABSTAIN until a UK strategy passes locked OOS "
                    "admission on genuine data",
        },
        "broker_execution": "DISABLED_FOR_UK",
    }
