from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sidedeck.application.sd066_data_capability import (
    CAPABILITY_MATRIX,
    STATUSES,
    TRACK_DATA_NEEDS,
    BudgetPolicy,
    CapabilityError,
    DataNeed,
    ProviderBudget,
    capability,
    select_sources,
)

T0 = datetime(2026, 10, 22, 14, tzinfo=UTC)


def test_matrix_is_honest_about_delay_consolidation_and_status() -> None:
    assert {c.source_id for c in CAPABILITY_MATRIX} >= {"SEC_EDGAR", "ALPACA_SIP_DAILY", "ALPACA_IEX"}
    assert all(c.status in STATUSES and c.evidence for c in CAPABILITY_MATRIX)
    assert capability("ALPACA_IEX").consolidated is False
    assert not any(c.delay == "REALTIME" for c in CAPABILITY_MATRIX)
    with pytest.raises(CapabilityError):
        capability("MADE_UP")


def test_day_track_is_blocked_without_an_approved_intraday_source() -> None:
    selection = select_sources(TRACK_DATA_NEEDS["DAY"])
    assert selection.status == "BLOCKED_EXTERNAL" and selection.usable == ()
    reasons = dict(selection.refused)
    assert reasons["ALPACA_IEX"] != "OK"  # 1M exists but not 5M, nor consolidated


def test_unapproved_sources_are_refused_even_when_capable() -> None:
    selection = select_sources(DataNeed("daily", "1D", "COMMON_STOCK", "END_OF_DAY"))
    reasons = dict(selection.refused)
    assert reasons["ALPACA_SIP_DAILY"] == "STATUS_AUTHORIZATION_EXHAUSTED"
    assert reasons["TIINGO_EOD"] == "STATUS_NOT_APPROVED"
    assert selection.usable == ("OWNER_CSV_IMPORT",)
    strict = select_sources(DataNeed("daily", "1D", "COMMON_STOCK", "END_OF_DAY",
                                     requires_consolidated=True))
    assert "OWNER_CSV_IMPORT" not in strict.usable
    with pytest.raises(CapabilityError):
        select_sources(DataNeed("x", "1D", "ETF", "INSTANT"))


def test_budget_refuses_unapproved_provider() -> None:
    with pytest.raises(CapabilityError, match="owner authorization"):
        ProviderBudget(Path("unused.sqlite3"), BudgetPolicy("ALPACA_SIP_DAILY", 1, 60, 1))


def test_budget_rate_total_restart_and_clock(tmp_path: Path) -> None:
    db = tmp_path / "budget.sqlite3"
    policy = BudgetPolicy("SEC_EDGAR", max_per_window=2, window_seconds=1, max_total=3)
    budget = ProviderBudget(db, policy)
    assert budget.reserve(T0).allowed
    assert budget.reserve(T0).allowed
    assert budget.reserve(T0).reason == "RATE_LIMITED"
    restarted = ProviderBudget(db, policy)  # counts survive restart
    assert restarted.reserve(T0).reason == "RATE_LIMITED"
    assert restarted.reserve(T0 - timedelta(seconds=5)).reason == "CLOCK_REGRESSION"
    assert restarted.reserve(T0 + timedelta(seconds=2)).allowed
    assert restarted.reserve(T0 + timedelta(seconds=10)).reason == "TOTAL_BUDGET_EXHAUSTED"
    with pytest.raises(CapabilityError):
        restarted.reserve(T0.replace(tzinfo=None))


def test_retry_only_for_transient_and_breaker_isolates(tmp_path: Path) -> None:
    policy = BudgetPolicy("SEC_EDGAR", 10, 1, 100, max_retries=1, breaker_failures=2,
                          breaker_cooldown_seconds=60)
    budget = ProviderBudget(tmp_path / "b.sqlite3", policy)
    r1 = budget.reserve(T0)
    assert r1.reservation_id is not None
    assert budget.record_outcome(r1.reservation_id, T0, 503) == "RETRY_ALLOWED"
    assert budget.reserve(T0, attempt=2).reason == "RETRY_LIMIT"
    r2 = budget.reserve(T0, attempt=1)
    assert r2.reservation_id is not None
    assert budget.record_outcome(r2.reservation_id, T0, 403) == "NO_RETRY"
    assert budget.reserve(T0 + timedelta(seconds=1)).reason == "CIRCUIT_OPEN"
    r3 = budget.reserve(T0 + timedelta(seconds=61))
    assert r3.allowed and r3.reservation_id is not None
    assert budget.record_outcome(r3.reservation_id, T0, 200) == "OK"
    with pytest.raises(CapabilityError):
        budget.record_outcome(r3.reservation_id, T0, 200)  # no double recording
    assert budget.record_outcome(
        budget.reserve(T0 + timedelta(seconds=62)).reservation_id or -1, T0, None
    ) == "NO_RETRY"
    assert budget.usage()["OK"] == 1


@pytest.mark.parametrize("kwargs", [
    {"max_per_window": -1}, {"window_seconds": 0}, {"max_retries": 4}, {"breaker_failures": 0},
])
def test_invalid_policies(kwargs: dict[str, int]) -> None:
    base = {"provider": "SEC_EDGAR", "max_per_window": 1, "window_seconds": 1, "max_total": 1}
    with pytest.raises(CapabilityError):
        BudgetPolicy(**{**base, **kwargs})  # type: ignore[arg-type]


def test_review_budget_cannot_exceed_documented_rate_and_mixed_offsets_order(tmp_path: Path) -> None:
    with pytest.raises(CapabilityError, match="documented rate limit"):
        ProviderBudget(tmp_path / "x.sqlite3", BudgetPolicy("SEC_EDGAR", 1000, 1, 10**5))
    from zoneinfo import ZoneInfo

    budget = ProviderBudget(tmp_path / "y.sqlite3", BudgetPolicy("SEC_EDGAR", 1, 60, 10))
    assert budget.reserve(T0).allowed
    # Same instant expressed in New York time must count against the same window.
    assert budget.reserve(T0.astimezone(ZoneInfo("America/New_York"))).reason == "RATE_LIMITED"
    earlier_ny = (T0 - timedelta(seconds=1)).astimezone(ZoneInfo("America/New_York"))
    assert budget.reserve(earlier_ny).reason == "CLOCK_REGRESSION"
