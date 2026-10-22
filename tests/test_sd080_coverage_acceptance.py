"""SD-080 coverage acceptance. Bars are synthetic fixtures."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from sidedeck.application.sd014_strategy_engine import StrategyBar
from sidedeck.application.sd080_coverage_acceptance import (
    CoverageError,
    assess_instrument,
    coverage_report,
)
from sidedeck.application.us_equity_calendar import expected_regular_sessions

START, END = date(2026, 9, 1), date(2026, 10, 21)
DAYS = expected_regular_sessions(START, END)


def _bars(days: tuple[date, ...] = DAYS) -> list[StrategyBar]:
    out = []
    for i, d in enumerate(days):
        c = Decimal(100) + Decimal(i % 3)
        out.append(StrategyBar(d, c, c + 1, c - 1, c, Decimal(1000)))
    return out


def test_complete_series_is_covered() -> None:
    item = assess_instrument("US:A", _bars(), START, END)
    assert item.status == "COVERED" and item.missing_sessions == 0
    assert item.expected_sessions == len(DAYS) == item.observed_sessions


def test_missing_sessions_partial_and_listed() -> None:
    bars = _bars()
    del bars[10]
    item = assess_instrument("US:A", bars, START, END)
    assert item.status == "PARTIALLY_COVERED" and item.missing_sessions == 1
    assert item.first_missing == (DAYS[10].isoformat(),)


@pytest.mark.parametrize("mutate, issue, status", [
    (lambda b: b + [b[-1]], "DUPLICATE_DATES", "UNAVAILABLE"),
    (lambda b: b + [replace(b[-1], day=date(2026, 9, 7))], "NON_SESSION_DATES", "UNAVAILABLE"),
    (lambda b: b[:-1] + [replace(b[-1], close=Decimal(0))], "INVALID_PRICES", "UNAVAILABLE"),
    (lambda b: b[:-1] + [replace(b[-1], high=Decimal(1))], "INCONSISTENT_OHLC", "UNAVAILABLE"),
    (lambda b: b[:-1] + [replace(b[-1], volume=Decimal(0))], "ZERO_VOLUME_SESSIONS",
     "PARTIALLY_COVERED"),
    (lambda b: b[:-1] + [replace(b[-1], open=Decimal(50), high=Decimal(51), low=Decimal(49),
                                 close=Decimal(50))], "SUSPECTED_UNADJUSTED_SPLIT",
     "PARTIALLY_COVERED"),
    (lambda b: [replace(x, open=Decimal(100), high=Decimal(101), low=Decimal(99),
                        close=Decimal(100)) for x in b], "STALE_REPEATED_CLOSES",
     "PARTIALLY_COVERED"),
    (lambda b: b + [replace(b[-1], day=date(2026, 10, 22))], "OUTSIDE_WINDOW", "UNAVAILABLE"),
])
def test_quality_issues(mutate: object, issue: str, status: str) -> None:
    item = assess_instrument("US:A", mutate(_bars()), START, END)  # type: ignore[operator]
    assert issue in item.issues and item.status == status


def test_report_counts_and_benchmark_gate() -> None:
    report = coverage_report({"US:SPY": _bars(), "US:A": _bars()[:-3], "US:B": None},
                             START, END, data_basis="FIXTURE", benchmark_id="US:SPY")
    assert report.counts == {"COVERED": 1, "PARTIALLY_COVERED": 1, "UNAVAILABLE": 1}
    assert report.relative_metrics_allowed
    weak = coverage_report({"US:SPY": _bars()[:-1]}, START, END, data_basis="FIXTURE",
                           benchmark_id="US:SPY")
    assert not weak.relative_metrics_allowed
    with pytest.raises(CoverageError):
        coverage_report({}, START, END, data_basis=" ")
    with pytest.raises(CoverageError, match="calendar"):
        assess_instrument("US:A", _bars(), date(2021, 1, 4), END)
