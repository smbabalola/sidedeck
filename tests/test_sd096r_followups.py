"""SD-096R follow-ups: M1 effective per-exchange mode, L3 rule-only half days, L4 ISIN country."""
from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from sidedeck.application.sd068_track_scheduler import MULTI_EXCHANGE_JOBS, SchedulerStore
from sidedeck.application.sd089_exchange_calendar import UK_HALF_DAYS, UK_UNCORROBORATED_HALF_DAYS
from sidedeck.application.sd090_uk_market import LISTING_COLUMNS, parse_uk_listings


def test_m1_simulation_needs_both_track_and_exchange_track(tmp_path: Path) -> None:
    store = SchedulerStore(tmp_path / "s.sqlite3", MULTI_EXCHANGE_JOBS)
    job = next(j for j in MULTI_EXCHANGE_JOBS if j.job_id == "xlon.swing_review")
    assert store.effective_mode(job) == "RESEARCH_ONLY"
    store.set_track("SWING", enabled=True, mode="SIMULATION_ONLY")
    assert store.effective_mode(job) == "RESEARCH_ONLY"            # exchange still research
    store.set_exchange_track("XLON", "SWING", enabled=True, mode="SIMULATION_ONLY")
    assert store.effective_mode(job) == "SIMULATION_ONLY"
    store.set_track("SWING", enabled=True, mode="RESEARCH_ONLY")
    assert store.effective_mode(job) == "RESEARCH_ONLY"
    due = store.due(datetime(2026, 10, 23, 15, 0, tzinfo=UTC))
    assert all(r.mode == "RESEARCH_ONLY" for r in due)


def test_l3_rule_only_half_days_are_listed_as_uncorroborated() -> None:
    assert UK_UNCORROBORATED_HALF_DAYS <= set(UK_HALF_DAYS)
    assert date(2023, 12, 29) in UK_UNCORROBORATED_HALF_DAYS


def test_l4_listing_country_comes_from_the_isin() -> None:
    header = ",".join(LISTING_COLUMNS) + "\n"
    rows = ("BP.,GB0007980591,BP,ORDINARY_SHARE,GBX,GBP,2001-01-02,,2001-01-02,,src,2026-10-22\n"
            "RIO,JE00B4T3BW64,Jersey line,ORDINARY_SHARE,GBX,GBP,2001-01-02,,2001-01-02,,src,"
            "2026-10-22\n")
    report = parse_uk_listings(header + rows, licence_note="test-only")
    countries = {r.isin: r.country for r in report.records}
    assert countries.get("GB0007980591") == "GB"
    assert countries.get("JE00B4T3BW64", "JE") == "JE"
