from datetime import UTC, datetime
from pathlib import Path
import sqlite3

import pytest

from sidedeck.application.sd121_day_trader_schedule import tick


def test_fixture_schedule_is_durable_single_slot_and_audited(tmp_path: Path) -> None:
    now = datetime(2026, 10, 27, 20, 46, tzinfo=UTC)
    paths = {name: tmp_path / f"{name}.sqlite3" for name in ("schedule", "runs", "audit")}
    with pytest.raises(PermissionError, match="fixture_acceptance"):
        tick(now=now, schedule_db=paths["schedule"], runs_db=paths["runs"],
             audit_db=paths["audit"])

    result = tick(now=now, schedule_db=paths["schedule"], runs_db=paths["runs"],
                  audit_db=paths["audit"], fixture_acceptance=True)
    assert result["status"] == "COMPLETED"
    assert result["broker_execution"] == "DISABLED"
    assert result["basis"] == "UPSTREAM_FIXTURE_UNAPPROVED_SOURCE"
    assert result["run_id"]

    # A fresh process/store sees the completed slot and cannot rerun it.
    recovered = tick(now=now, schedule_db=paths["schedule"], runs_db=paths["runs"],
                     audit_db=paths["audit"], fixture_acceptance=True)
    assert recovered["status"] == "NOT_DUE"
    with sqlite3.connect(paths["audit"]) as db:
        row = db.execute("SELECT status, run_id, basis FROM sd121_schedule_audit").fetchone()
        assert row == ("COMPLETED", result["run_id"], "UPSTREAM_FIXTURE_UNAPPROVED_SOURCE")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("DELETE FROM sd121_schedule_audit")
