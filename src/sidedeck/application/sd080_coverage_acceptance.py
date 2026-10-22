"""SD-080 real-data coverage acceptance and data-quality checks (offline).

Classifies each instrument's daily bars against the verified exchange calendar:

* ``COVERED`` — every expected regular session in the window is present and no
  blocking quality issue was found;
* ``PARTIALLY_COVERED`` — some sessions are present but sessions are missing or
  a quality issue needs review (never silently filled);
* ``UNAVAILABLE`` — no usable bars (request failed, empty, or invalid).

Quality checks: duplicates, non-session dates, non-finite/non-positive prices,
OHLC inconsistency, zero-volume sessions, suspected unadjusted splits (one-day
moves beyond a threshold) and stale repeated closes. The report always states
its data basis so fixture checks are never presented as market coverage.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Mapping, Sequence

from sidedeck.application.sd014_strategy_engine import StrategyBar
from sidedeck.application.us_equity_calendar import (
    COMPLETE_CALENDAR_YEARS,
    expected_regular_sessions,
    is_regular_session,
)

BLOCKING = frozenset({"DUPLICATE_DATES", "NON_SESSION_DATES", "INVALID_PRICES",
                      "INCONSISTENT_OHLC", "OUTSIDE_WINDOW"})
REVIEW = frozenset({"ZERO_VOLUME_SESSIONS", "SUSPECTED_UNADJUSTED_SPLIT", "STALE_REPEATED_CLOSES"})


class CoverageError(ValueError):
    pass


@dataclass(frozen=True)
class InstrumentCoverage:
    canonical_id: str
    status: str
    expected_sessions: int
    observed_sessions: int
    missing_sessions: int
    first_missing: tuple[str, ...]
    issues: tuple[str, ...]
    first_date: str | None
    last_date: str | None


@dataclass(frozen=True)
class CoverageReport:
    data_basis: str
    window_start: date
    window_end: date
    instruments: tuple[InstrumentCoverage, ...]
    benchmark_id: str | None
    benchmark_status: str
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def relative_metrics_allowed(self) -> bool:
        return self.benchmark_status == "COVERED"


def assess_instrument(
    canonical_id: str, bars: Sequence[StrategyBar] | None, start: date, end: date, *,
    jump_threshold: Decimal = Decimal("0.45"), stale_run: int = 5,
) -> InstrumentCoverage:
    for d in (start, end):
        if d.year not in COMPLETE_CALENDAR_YEARS:
            raise CoverageError(f"calendar does not cover {d.year}")
    expected = expected_regular_sessions(start, end)
    if not bars:
        return InstrumentCoverage(canonical_id, "UNAVAILABLE", len(expected), 0, len(expected),
                                  tuple(d.isoformat() for d in expected[:5]), ("NO_BARS",),
                                  None, None)
    issues: set[str] = set()
    days = [b.day for b in bars]
    if len(set(days)) != len(days):
        issues.add("DUPLICATE_DATES")
    if any(d < start or d > end for d in days):
        issues.add("OUTSIDE_WINDOW")
    if any(not is_regular_session(d) for d in days):
        issues.add("NON_SESSION_DATES")
    ordered = sorted(bars, key=lambda b: b.day)
    valid = True
    for b in ordered:
        prices = (b.open, b.high, b.low, b.close)
        if any(not p.is_finite() or p <= 0 for p in prices) or not b.volume.is_finite() \
                or b.volume < 0:
            issues.add("INVALID_PRICES")
            valid = False
        elif b.high < max(b.open, b.close) or b.low > min(b.open, b.close):
            issues.add("INCONSISTENT_OHLC")
        if b.volume == 0:
            issues.add("ZERO_VOLUME_SESSIONS")
    if valid:
        run = 1
        for prev, cur in zip(ordered, ordered[1:]):
            if abs(cur.close / prev.close - 1) > jump_threshold:
                issues.add("SUSPECTED_UNADJUSTED_SPLIT")
            run = run + 1 if cur.close == prev.close else 1
            if run >= stale_run:
                issues.add("STALE_REPEATED_CLOSES")
    observed = {d for d in days if start <= d <= end}
    missing = [d for d in expected if d not in observed]
    if not observed or issues & BLOCKING:
        status = "UNAVAILABLE"  # nothing usable, or untrustworthy data: fail closed
    elif missing or issues:
        status = "PARTIALLY_COVERED"
    else:
        status = "COVERED"
    return InstrumentCoverage(
        canonical_id, status, len(expected), len(observed & set(expected)), len(missing),
        tuple(d.isoformat() for d in missing[:5]), tuple(sorted(issues)),
        ordered[0].day.isoformat(), ordered[-1].day.isoformat(),
    )


def coverage_report(
    bars_by_id: Mapping[str, Sequence[StrategyBar] | None], start: date, end: date, *,
    data_basis: str, benchmark_id: str | None = None,
) -> CoverageReport:
    if not data_basis.strip():
        raise CoverageError("data_basis is required")
    items = tuple(assess_instrument(cid, bars_by_id[cid], start, end) for cid in sorted(bars_by_id))
    counts = {s: 0 for s in ("COVERED", "PARTIALLY_COVERED", "UNAVAILABLE")}
    for item in items:
        counts[item.status] += 1
    bench = next((i.status for i in items if i.canonical_id == benchmark_id), "UNAVAILABLE")
    if benchmark_id is None:
        bench = "NOT_APPLICABLE"
    return CoverageReport(data_basis, start, end, items, benchmark_id, bench, counts)
