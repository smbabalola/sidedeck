"""SD-082 persisted scanner snapshots for the read-only Markets workspace.

``write_scan_snapshot`` stores the latest broad scan and per-track shortlists with
explicit provenance (``REAL_DATA`` with a source id, or ``SYNTHETIC_FIXTURE``).
``scan_snapshot_summary`` reads it back through a strict allowlist for the API:
numbers are emitted as strings, unknown fields are dropped and anything malformed
is ``UNAVAILABLE``. Nothing here fetches data or touches a broker.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping

from sidedeck.application.sd067_market_scanner import ScanReport, Shortlist

SCHEMA = "sidedeck.scan_snapshot.v1"
PROVENANCES = frozenset({"REAL_DATA", "SYNTHETIC_FIXTURE"})
MAX_BYTES = 4_000_000
_FEATURES = ("last_close", "ret_5", "ret_20", "ret_60", "ret_126", "rs_60", "atr_pct", "vol20",
             "dollar_adv20", "unusual_volume", "gap_pct")


class SnapshotError(ValueError):
    pass


def _s(value: Decimal | None) -> str | None:
    return None if value is None else format(value.quantize(Decimal("0.000001")), "f")


def _count(items: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        out[item] = out.get(item, 0) + 1
    return out


def write_scan_snapshot(
    path: Path, report: ScanReport, shortlists: Mapping[str, Shortlist], *, provenance: str,
    source_id: str, exchanges: Mapping[str, str], generated_at: datetime,
) -> None:
    if provenance not in PROVENANCES:
        raise SnapshotError("provenance must be REAL_DATA or SYNTHETIC_FIXTURE")
    synthetic_basis = "SYNTHETIC" in report.data_basis.upper() or "FIXTURE" in \
        report.data_basis.upper()
    if provenance == "SYNTHETIC_FIXTURE" and not synthetic_basis:
        raise SnapshotError("synthetic snapshots must come from a synthetic data basis")
    if provenance == "REAL_DATA" and synthetic_basis:
        raise SnapshotError("a synthetic or fixture scan can never be labelled REAL_DATA")
    features = {f.canonical_id for f in report.features}
    payload = {
        "schema": SCHEMA, "provenance": provenance, "source_id": source_id,
        "data_basis": report.data_basis, "generated_at": generated_at.astimezone(UTC).isoformat(),
        "cutoff": report.cutoff.isoformat(), "universe_size": report.universe_size,
        "scanned": len(report.features), "excluded": report.exclusion_counts(),
        "duration_seconds": round(report.duration_seconds, 3), "bars_read": report.bars_read,
        "instruments": [
            {"canonical_id": f.canonical_id, "ticker": f.canonical_id.split(":", 1)[1],
             "exchange": exchanges.get(f.canonical_id, "UNKNOWN"), "sessions": f.sessions,
             "regime": f.regime, "breakout_20": f.breakout_20,
             "sweep_reversal_20": f.sweep_reversal_20,
             "above_sma200": f.above_sma200, "event_flags": list(f.event_flags),
             **{name: _s(getattr(f, name)) for name in _FEATURES}}
            for f in report.features
        ],
        "tracks": {
            track: {
                "candidates": [
                    {"canonical_id": c.canonical_id, "rank": c.rank, "score": _s(c.score),
                     "components": {k: _s(v) for k, v in c.components},
                     "missing": list(c.missing_features),
                     "research": c in s.research}
                    for c in s.candidates if c.canonical_id in features
                ],
                "filtered": dict(sorted(_count(r for _, r in s.filtered).items())),
            }
            for track, s in shortlists.items()
        },
    }
    text = json.dumps(payload, sort_keys=True)
    if len(text) > MAX_BYTES:
        raise SnapshotError("snapshot too large")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".scan-")
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(text)
    os.replace(tmp, path)


def _num(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise SnapshotError("invalid numeric string")
    if not Decimal(value).is_finite():
        raise SnapshotError("non-finite number")
    return value


def scan_snapshot_summary(path: str | None) -> dict[str, Any]:
    base: dict[str, Any] = {"schema_version": 1, "status": "UNAVAILABLE",
                            "execution_enabled": False,
                            "reason": "no scanner snapshot has been produced"}
    if not path:
        return base
    target = Path(path)
    try:
        if not target.is_file() or target.is_symlink() or target.stat().st_size > MAX_BYTES:
            return base
        data = json.loads(target.read_text(encoding="utf-8"))
        if data.get("schema") != SCHEMA or data.get("provenance") not in PROVENANCES:
            return {**base, "reason": "snapshot schema or provenance not recognised"}
        instruments = []
        for row in data["instruments"]:
            above = row["above_sma200"]
            instruments.append({
                "canonical_id": str(row["canonical_id"])[:24], "ticker": str(row["ticker"])[:12],
                "exchange": str(row["exchange"])[:16], "sessions": int(row["sessions"]),
                "regime": str(row["regime"])[:16], "breakout_20": row["breakout_20"] is True,
                "sweep_reversal_20": row["sweep_reversal_20"] is True,
                "above_sma200": above if isinstance(above, bool) else None,
                "event_flags": [str(x)[:32] for x in row.get("event_flags", [])][:8],
                **{name: _num(row.get(name)) for name in _FEATURES},
            })
        tracks = {}
        for track in ("DAY", "SWING", "POSITION"):
            raw = data["tracks"].get(track, {"candidates": [], "filtered": {}})
            tracks[track] = {
                "candidates": [
                    {"canonical_id": str(c["canonical_id"])[:24], "rank": int(c["rank"]),
                     "score": _num(c["score"]),
                     "components": {str(k)[:24]: _num(v) for k, v in c["components"].items()},
                     "missing": [str(m)[:24] for m in c["missing"]],
                     "research": c["research"] is True}
                    for c in raw["candidates"]
                ][:1000],
                "filtered": {str(k)[:32]: int(v) for k, v in raw["filtered"].items()},
            }
        return {
            "schema_version": 1, "status": "LOADED", "execution_enabled": False,
            "provenance": data["provenance"], "source_id": str(data["source_id"])[:64],
            "data_basis": str(data["data_basis"])[:80],
            "generated_at": str(data["generated_at"])[:40], "cutoff": str(data["cutoff"])[:10],
            "universe_size": int(data["universe_size"]), "scanned": int(data["scanned"]),
            "excluded": {str(k)[:32]: int(v) for k, v in data["excluded"].items()},
            "duration_seconds": float(data["duration_seconds"]),
            "instruments": instruments, "tracks": tracks,
            "note": "Scores rank candidates; they are not forecasts or orders.",
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ArithmeticError):
        return {**base, "reason": "snapshot unreadable or malformed"}


def main(argv: list[str] | None = None) -> int:
    from sidedeck.application.sd067_market_scanner import (
        DEFAULT_SCORING,
        build_shortlist,
        run_broad_scan,
    )
    from sidedeck.application.sd076_pipeline_demo import CUTOFF, DATA_BASIS, _synthetic_bars
    from sidedeck.application.us_equity_calendar import expected_regular_sessions

    parser = argparse.ArgumentParser(description="Write a SYNTHETIC_FIXTURE scan snapshot")
    parser.add_argument("--synthetic", type=int, required=True, help="instrument count 1-2000")
    parser.add_argument("--out", default="data/scan-latest.json")
    args = parser.parse_args(argv)
    if not 1 <= args.synthetic <= 2000:
        parser.error("synthetic count must be 1-2000")
    days = expected_regular_sessions(CUTOFF.replace(year=CUTOFF.year - 1), CUTOFF)
    bars = {f"US:SYN{i:03d}": _synthetic_bars(i, days) for i in range(args.synthetic)}
    report = run_broad_scan(sorted(bars), bars.__getitem__, CUTOFF, data_basis=DATA_BASIS,
                            benchmark=_synthetic_bars(9999, days))
    shortlists = {t: build_shortlist(report, c) for t, c in DEFAULT_SCORING.items()}
    write_scan_snapshot(Path(args.out), report, shortlists, provenance="SYNTHETIC_FIXTURE",
                        source_id="sd076-synthetic-generator",
                        exchanges={cid: "SYNTHETIC" for cid in bars},
                        generated_at=datetime.now(UTC))
    print(f"SNAPSHOT_WRITTEN={args.out}; PROVENANCE=SYNTHETIC_FIXTURE; NETWORK_REQUESTS=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
