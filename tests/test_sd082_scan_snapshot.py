"""SD-082 scan snapshots. Synthetic bars only."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from sidedeck.application.sd067_market_scanner import (
    DEFAULT_SCORING,
    ScanReport,
    Shortlist,
    build_shortlist,
    run_broad_scan,
)
from sidedeck.application.sd076_pipeline_demo import CUTOFF, DATA_BASIS, _synthetic_bars
from sidedeck.application.sd082_scan_snapshot import (
    SnapshotError,
    scan_snapshot_summary,
    write_scan_snapshot,
)
from sidedeck.application.us_equity_calendar import expected_regular_sessions

NOW = datetime(2026, 10, 22, 20, tzinfo=UTC)


def _scan(basis: str = DATA_BASIS) -> tuple[ScanReport, dict[str, Shortlist]]:
    days = expected_regular_sessions(CUTOFF.replace(year=2025), CUTOFF)
    bars = {f"US:SYN{i:03d}": _synthetic_bars(i, days) for i in range(25)}
    report = run_broad_scan(sorted(bars), bars.__getitem__, CUTOFF, data_basis=basis)
    return report, {t: build_shortlist(report, c) for t, c in DEFAULT_SCORING.items()}


def _write(path: Path, provenance: str = "SYNTHETIC_FIXTURE", basis: str = DATA_BASIS) -> None:
    report, shortlists = _scan(basis)
    write_scan_snapshot(path, report, shortlists, provenance=provenance, source_id="test",
                        exchanges={}, generated_at=NOW)


def test_round_trip_is_allowlisted_and_labelled(tmp_path: Path) -> None:
    path = tmp_path / "scan.json"
    _write(path)
    s = scan_snapshot_summary(str(path))
    assert s["status"] == "LOADED" and s["provenance"] == "SYNTHETIC_FIXTURE"
    assert s["execution_enabled"] is False and s["scanned"] == 25
    assert s["instruments"][0]["exchange"] == "UNKNOWN"
    assert isinstance(s["instruments"][0]["last_close"], str)
    swing = s["tracks"]["SWING"]
    ranks = [c["rank"] for c in swing["candidates"]]
    assert ranks == sorted(ranks) and any(c["research"] for c in swing["candidates"])
    assert "not forecasts" in s["note"]


def test_provenance_cannot_be_upgraded(tmp_path: Path) -> None:
    with pytest.raises(SnapshotError, match="never be labelled REAL_DATA"):
        _write(tmp_path / "x.json", provenance="REAL_DATA")
    with pytest.raises(SnapshotError, match="synthetic data basis"):
        _write(tmp_path / "y.json", basis="ALPACA_SIP_DAILY (split-adjusted)")
    with pytest.raises(SnapshotError):
        _write(tmp_path / "z.json", provenance="LIVE")


@pytest.mark.parametrize("field, value", [
    ("schema", "other"), ("provenance", "REAL_TIME"), ("instrument_close", "NaN"),
    ("instrument_close", 12.5), ("tracks", None),
])
def test_malformed_snapshots_are_unavailable(tmp_path: Path, field: str, value: Any) -> None:
    path = tmp_path / "scan.json"
    _write(path)
    data = json.loads(path.read_text())
    if field == "instrument_close":
        data["instruments"][0]["last_close"] = value
    elif value is None:
        data.pop(field)
    else:
        data[field] = value
    path.write_text(json.dumps(data))
    assert scan_snapshot_summary(str(path))["status"] == "UNAVAILABLE"


def test_missing_snapshot_is_unavailable(tmp_path: Path) -> None:
    assert scan_snapshot_summary(None)["status"] == "UNAVAILABLE"
    assert scan_snapshot_summary(str(tmp_path / "missing.json"))["status"] == "UNAVAILABLE"


def test_hand_edited_real_data_claim_is_refused_on_read(tmp_path: Path) -> None:
    path = tmp_path / "scan.json"
    _write(path)
    data = json.loads(path.read_text())
    data["provenance"] = "REAL_DATA"
    path.write_text(json.dumps(data))
    assert scan_snapshot_summary(str(path))["status"] == "UNAVAILABLE"
    data["provenance"] = "SYNTHETIC_FIXTURE"
    data["duration_seconds"] = -1
    path.write_text(json.dumps(data))
    assert scan_snapshot_summary(str(path))["status"] == "UNAVAILABLE"
