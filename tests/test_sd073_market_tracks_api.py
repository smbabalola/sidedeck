from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sidedeck.application.sd073_market_tracks_api import market_tracks_summary

NOW = datetime(2026, 10, 22, 20, 30, tzinfo=UTC)   # after the close


def test_tracks_are_research_only_and_honest_without_evidence() -> None:
    s = market_tracks_summary(now=NOW)
    assert s["execution_enabled"] is False
    assert s["universe"]["status"] == "UNAVAILABLE" and s["price_coverage"]["status"] == "UNAVAILABLE"
    tracks = {t["track"]: t for t in s["tracks"]}
    assert set(tracks) == {"DAY", "SWING", "POSITION"}
    assert all(t["mode"] == "RESEARCH_ONLY" and t["execution"] == "DISABLED" for t in tracks.values())
    assert tracks["DAY"]["data_status"] == "BLOCKED_EXTERNAL" and tracks["DAY"]["filters"][
        "spread_required"]
    day_job = tracks["DAY"]["jobs"][0]
    assert day_job["next_run_utc"] == "2026-10-23T13:35:00+00:00"   # next session, not tonight
    assert s["decision_engine"]["execution_permission"] == "NOT_GRANTED_BY_DECISION_ENGINE"
    text = json.dumps(s).lower()
    assert "secret" not in text and "apca" not in text


def test_loads_only_allowlisted_evidence_fields(tmp_path: Path) -> None:
    universe = tmp_path / "u.json"
    universe.write_text(json.dumps({"merged_instruments": 5900, "history_basis": "SNAPSHOT x",
                                    "retrieved_at": "2026-10-22T19:00:00+00:00",
                                    "files": [{"sha256": "raw-should-not-appear"}]}))
    pilot = tmp_path / "p.json"
    pilot.write_text(json.dumps({"coverage_counts": {"COVERED": 19, "PARTIALLY_COVERED": 1,
                                                     "UNAVAILABLE": 0},
                                 "benchmark_status": "COVERED", "key": "APCA-leak"}))
    s = market_tracks_summary(str(universe), str(pilot), now=NOW)
    assert s["universe"] == {"status": "SNAPSHOT_LOADED", "instruments": 5900,
                             "history_basis": "SNAPSHOT x",
                             "retrieved_at": "2026-10-22T19:00:00+00:00",
                             "tradability": "NOT_ASSESSED"}
    assert s["price_coverage"]["counts"]["COVERED"] == 19
    assert "APCA-leak" not in json.dumps(s) and "raw-should-not-appear" not in json.dumps(s)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"coverage_counts": {"COVERED": "19"}}))
    assert market_tracks_summary(None, str(bad), now=NOW)["price_coverage"]["status"] == "UNAVAILABLE"
    assert market_tracks_summary(str(tmp_path / "missing.json"), now=NOW)["universe"]["status"] \
        == "UNAVAILABLE"


def test_review_boolean_counts_are_rejected(tmp_path: Path) -> None:
    pilot = tmp_path / "p.json"
    pilot.write_text(json.dumps({"coverage_counts": {"COVERED": True, "PARTIALLY_COVERED": 0,
                                                     "UNAVAILABLE": 0}}))
    summary = market_tracks_summary(None, str(pilot), now=NOW)
    assert summary["price_coverage"]["status"] == "UNAVAILABLE"
