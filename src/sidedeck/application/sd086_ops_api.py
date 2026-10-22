"""SD-086 read-only summaries for the Portfolio and Operations workspaces.

* ``authorization_ledger_summary`` reports how many requests each signed SD-077 data
  authorization has used (counts and outcomes only; URLs are public endpoints).
* ``track_ledgers_summary`` reports the SD-079 simulated per-track ledgers (cash,
  open positions, realized P&L, fees, entries) labelled ``SIMULATION``.

Both open SQLite files strictly read-only (``mode=ro``) and never create them;
anything missing or malformed is reported ``UNAVAILABLE``.
"""
from __future__ import annotations

import json
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

_TRACK_FILES = {"DAY": "day-ledger.sqlite3", "SWING": "swing-ledger.sqlite3",
                "POSITION": "position-ledger.sqlite3"}


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve(strict=True).as_uri() + "?mode=ro", uri=True)


def authorization_ledger_summary(path: str | None) -> dict[str, Any]:
    base: dict[str, Any] = {"schema_version": 1, "status": "UNAVAILABLE", "authorizations": [],
                            "execution_enabled": False}
    if not path:
        return {**base, "reason": "no data-authorization ledger configured"}
    target = Path(path)
    if not target.is_file() or target.is_symlink():
        return {**base, "reason": "no signed data authorization has been used yet"}
    try:
        conn = _ro(target)
        try:
            rows = conn.execute(
                "SELECT auth_digest, outcome, COUNT(*), MIN(at), MAX(at) FROM requests "
                "GROUP BY auth_digest, outcome ORDER BY MIN(at)").fetchall()
        finally:
            conn.close()
    except (OSError, sqlite3.Error):
        return {**base, "reason": "ledger unreadable"}
    by_digest: dict[str, dict[str, Any]] = {}
    for digest, outcome, count, first, last in rows:
        if not (isinstance(digest, str) and len(digest) == 64 and type(count) is int):
            return {**base, "reason": "ledger malformed"}
        entry = by_digest.setdefault(digest, {"digest_prefix": digest[:12], "requests": 0,
                                              "outcomes": {}, "first_at": first, "last_at": last})
        entry["requests"] += count
        entry["outcomes"][str(outcome)[:64]] = count
        entry["first_at"] = min(entry["first_at"], first)
        entry["last_at"] = max(entry["last_at"], last)
    return {**base, "status": "LOADED", "authorizations": list(by_digest.values())}


def _dec(value: Any) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise InvalidOperation("non-finite")
    return result


def track_ledgers_summary(directory: str | None) -> dict[str, Any]:
    base: dict[str, Any] = {"schema_version": 1, "provenance": "SIMULATION",
                            "fill_basis": "SIMULATED_LOCAL", "execution_enabled": False,
                            "tracks": []}
    if not directory:
        return {**base, "status": "UNAVAILABLE", "reason": "no simulation ledger directory configured"}
    tracks: list[dict[str, Any]] = []
    for track, name in _TRACK_FILES.items():
        target = Path(directory) / name
        if not target.is_file() or target.is_symlink():
            tracks.append({"track": track, "status": "NOT_STARTED"})
            continue
        try:
            conn = _ro(target)
            try:
                meta = conn.execute("SELECT track, capital FROM meta").fetchone()
                events = conn.execute("SELECT kind, payload FROM events ORDER BY seq").fetchall()
            finally:
                conn.close()
            if meta is None or meta[0] != track:
                raise ValueError("ledger belongs to another track")
            capital = _dec(meta[1])
            cash, fees, realized = capital, Decimal(0), Decimal(0)
            open_positions: dict[str, tuple[Decimal, Decimal]] = {}  # ref -> (quantity, cost)
            entries = closes = 0
            for kind, payload in events:
                p = json.loads(payload)
                if kind == "OPEN":
                    quantity, fee = _dec(p["quantity"]), _dec(p["fee"])
                    cost = quantity * _dec(p["price"]) + fee
                    cash -= cost
                    fees += fee
                    open_positions[str(p["ref"])] = (quantity, cost)
                    entries += 1
                elif kind == "CLOSE":
                    quantity, cost = open_positions.pop(str(p["ref"]))
                    fee = _dec(p["fee"])
                    proceeds = quantity * _dec(p["price"]) - fee
                    cash += proceeds
                    fees += fee
                    realized += proceeds - cost
                    closes += 1
                elif kind != "MARK":
                    raise ValueError("unknown event")
            tracks.append({
                "track": track, "status": "ACTIVE", "virtual_capital": str(capital),
                "cash": str(cash), "open_positions": len(open_positions),
                "open_cost_basis": str(sum((c for _, c in open_positions.values()), Decimal(0))),
                "realized_pnl": str(realized), "fees": str(fees),
                "entries": entries, "closes": closes,
            })
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, InvalidOperation):
            tracks.append({"track": track, "status": "UNAVAILABLE"})
    return {**base, "status": "LOADED", "tracks": tracks}
