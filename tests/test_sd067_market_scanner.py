"""SD-067 tests. All bars are synthetic fixtures, never market observations."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from sidedeck.application.sd014_strategy_engine import StrategyBar
from sidedeck.application.sd067_market_scanner import (
    DEFAULT_SCORING,
    FeatureCache,
    ScanError,
    TrackScoring,
    build_shortlist,
    compute_features,
    run_broad_scan,
)
from sidedeck.application.us_equity_calendar import expected_regular_sessions

CUTOFF = date(2026, 10, 21)
DAYS = expected_regular_sessions(date(2025, 6, 2), CUTOFF)


def _series(start: str, drift: str, volume: int, days: tuple[date, ...] = DAYS,
            wiggle: str = "0.01") -> tuple[StrategyBar, ...]:
    price = Decimal(start)
    bars = []
    for i, day in enumerate(days):
        step = Decimal(drift) + (Decimal(wiggle) if i % 2 else -Decimal(wiggle))
        open_ = price
        close = (price * (1 + step)).quantize(Decimal("0.0001"))
        high = max(open_, close) * Decimal("1.01")
        low = min(open_, close) * Decimal("0.99")
        bars.append(StrategyBar(day, open_, high, low, close, Decimal(volume)))
        price = close
    return tuple(bars)


UP = _series("50", "0.003", 2_000_000)
DOWN = _series("50", "-0.002", 2_000_000)
FLAT = _series("50", "0", 2_000_000, wiggle="0.002")
THIN = _series("50", "0.004", 1_000)
PENNY = _series("2", "0", 50_000_000)
BENCH = _series("400", "0.0005", 50_000_000)
FIXTURES = {"US:UP": UP, "US:DOWN": DOWN, "US:FLAT": FLAT, "US:THIN": THIN, "US:PENNY": PENNY}


def _loader(cid: str) -> tuple[StrategyBar, ...]:
    if cid == "US:BROKEN":
        raise OSError("disk")
    return FIXTURES[cid]


def test_features_are_deterministic_and_point_in_time() -> None:
    f = compute_features("US:UP", UP, CUTOFF, benchmark=BENCH)
    assert f.sessions == len(DAYS) and f.last_close == UP[-1].close
    assert f.ret_20 > 0 and f.ret_126 is not None and f.ret_126 > 0
    assert f.sma200 is not None and f.above_sma200
    assert f.rs_60 is not None and f.rs_60 > 0 and f.regime == "RISK_ON"
    assert f.adv20 == Decimal(2_000_000) and f.atr_pct > 0 and f.vol20 > 0
    assert compute_features("US:UP", UP, CUTOFF, benchmark=BENCH) == f
    assert compute_features("US:DOWN", DOWN, CUTOFF).above_sma200 is False


def test_look_ahead_stale_and_malformed_data_fail_closed() -> None:
    future = UP + (StrategyBar(date(2026, 10, 22), UP[-1].close, UP[-1].close,
                               UP[-1].close, UP[-1].close, Decimal(1)),)
    with pytest.raises(ScanError, match="FUTURE_BAR"):
        compute_features("US:UP", future, CUTOFF)
    with pytest.raises(ScanError, match="STALE"):
        compute_features("US:UP", UP[:-1], CUTOFF)
    with pytest.raises(ScanError, match="DUPLICATE"):
        compute_features("US:UP", UP + UP[-1:], CUTOFF)
    bad = UP[:-1] + (replace(UP[-1], high=UP[-1].low / 2),)
    with pytest.raises(ScanError, match="INCONSISTENT"):
        compute_features("US:UP", bad, CUTOFF)
    with pytest.raises(ScanError, match="INSUFFICIENT"):
        compute_features("US:UP", UP[-10:], CUTOFF)
    nan = UP[:-1] + (replace(UP[-1], close=Decimal("NaN")),)
    with pytest.raises(ScanError):
        compute_features("US:UP", nan, CUTOFF)


def test_broad_scan_batches_isolates_failures_and_caches() -> None:
    universe = ["US:UP", "US:DOWN", "US:FLAT", "US:THIN", "US:PENNY", "US:BROKEN"]
    clock = iter([0.0, 1.5])
    cache = FeatureCache()
    report = run_broad_scan(universe, _loader, CUTOFF, data_basis="FIXTURE", batch_size=4,
                            cache=cache, benchmark=BENCH, clock=lambda: next(clock))
    assert report.batches == 2 and report.universe_size == 6 and len(report.features) == 5
    assert report.excluded == (("US:BROKEN", "LOAD_FAILED"),)
    assert report.duration_seconds == 1.5 and report.cache_hits == 0
    assert report.coverage_ratio == Decimal(5) / Decimal(6) and report.data_basis == "FIXTURE"
    again = run_broad_scan(universe, _loader, CUTOFF, data_basis="FIXTURE", cache=cache,
                           benchmark=BENCH)
    assert again.cache_hits == 5 and again.features == report.features
    no_bench = run_broad_scan(universe, _loader, CUTOFF, data_basis="FIXTURE", cache=cache)
    assert no_bench.cache_hits == 0  # different context, recomputed


@pytest.mark.parametrize("kwargs, message", [
    ({"cutoff": date(2026, 10, 24)}, "regular session"),     # Saturday
    ({"cutoff": date(2026, 11, 26)}, "regular session"),     # Thanksgiving
    ({"cutoff": date(2027, 1, 4)}, "regular session"),       # outside verified calendar
    ({"data_basis": " "}, "data_basis"),
    ({"batch_size": 0}, "batch_size"),
])
def test_scan_argument_validation(kwargs: dict[str, object], message: str) -> None:
    args: dict[str, object] = {"cutoff": CUTOFF, "data_basis": "FIXTURE"}
    args.update(kwargs)
    with pytest.raises(ScanError, match=message):
        run_broad_scan(["US:UP"], _loader, **args)  # type: ignore[arg-type]
    with pytest.raises(ScanError, match="duplicate"):
        run_broad_scan(["US:UP", "US:UP"], _loader, CUTOFF, data_basis="FIXTURE")


def test_track_shortlists_filter_rank_and_explain() -> None:
    report = run_broad_scan(list(FIXTURES), _loader, CUTOFF, data_basis="FIXTURE",
                            benchmark=BENCH)
    swing = build_shortlist(report, replace(DEFAULT_SCORING["SWING"], min_dollar_adv=Decimal(1),
                                            quant_size=3, research_size=1))
    filtered = dict(swing.filtered)
    assert filtered["US:PENNY"] == "PRICE_BELOW_MIN"
    order = [c.canonical_id for c in swing.candidates]
    assert order[:2] == ["US:THIN", "US:UP"]  # strongest synthetic drift ranks first
    assert [c.rank for c in swing.candidates] == list(range(1, len(swing.candidates) + 1))
    assert len(swing.research) == 1 and "not an expected return" in swing.note
    position = build_shortlist(report, replace(DEFAULT_SCORING["POSITION"],
                                               min_dollar_adv=Decimal(1)))
    assert dict(position.filtered)["US:DOWN"] == "BELOW_OR_NO_SMA200"
    liquid = build_shortlist(report, DEFAULT_SCORING["SWING"])
    assert dict(liquid.filtered)["US:THIN"] == "ILLIQUID"
    day = build_shortlist(report, replace(DEFAULT_SCORING["DAY"], min_dollar_adv=Decimal(1)))
    # No spread data supplied: DAY refuses rather than assuming tight spreads.
    assert day.candidates == () and set(dict(day.filtered).values()) <= {
        "SPREAD_UNAVAILABLE", "PRICE_BELOW_MIN", "INSUFFICIENT_RANGE"}


def test_missing_features_contribute_nothing_and_ties_are_deterministic() -> None:
    report = run_broad_scan(["US:UP", "US:FLAT"], _loader, CUTOFF, data_basis="FIXTURE")
    cfg = replace(DEFAULT_SCORING["SWING"], min_dollar_adv=Decimal(1))
    shortlist = build_shortlist(report, cfg)
    for cand in shortlist.candidates:
        assert "rs_60" in cand.missing_features  # no benchmark, no relative strength
        assert dict(cand.components)["rs_60"] is None
    assert build_shortlist(report, cfg) == shortlist


def test_event_exclusion_and_scoring_config_validation() -> None:
    report = run_broad_scan(["US:UP"], _loader, CUTOFF, data_basis="FIXTURE",
                            events={"US:UP": ["EARNINGS_WITHIN_5D"]})
    shortlist = build_shortlist(report, replace(DEFAULT_SCORING["SWING"],
                                                min_dollar_adv=Decimal(1)))
    assert dict(shortlist.filtered)["US:UP"] == "EVENT_EXCLUDED"
    with pytest.raises(ScanError):
        TrackScoring("CRYPTO", Decimal(1), Decimal(1), 1, (("ret_5", Decimal(1)),))
    with pytest.raises(ScanError):
        TrackScoring("DAY", Decimal(1), Decimal(1), 1, (("magic", Decimal(1)),))
    with pytest.raises(ScanError):
        TrackScoring("DAY", Decimal(1), Decimal(1), 1, (("ret_5", Decimal(1)),),
                     quant_size=5, research_size=10)


def test_review_missing_sessions_weekend_bars_and_malformed_objects() -> None:
    gap = UP[:-5] + UP[-4:]
    with pytest.raises(ScanError, match="MISSING_OR_NON_SESSION"):
        compute_features("US:UP", gap, CUTOFF)
    weekend = UP[:-1] + (replace(UP[-1], day=date(2026, 10, 18)),) + UP[-1:]
    with pytest.raises(ScanError, match="MISSING_OR_NON_SESSION"):
        compute_features("US:UP", weekend, CUTOFF)
    report = run_broad_scan(["US:BAD", "US:UP"], lambda cid: UP if cid == "US:UP" else
                            (object(),), CUTOFF, data_basis="FIXTURE")  # type: ignore[arg-type,return-value]
    assert report.excluded == (("US:BAD", "MALFORMED_BAR"),) and len(report.features) == 1


def test_review_relative_strength_is_date_aligned() -> None:
    assert compute_features("US:UP", UP, CUTOFF, benchmark=BENCH).rs_60 is not None
    gapped = tuple(b for b in BENCH if b.day != UP[-61].day)
    f = compute_features("US:UP", UP, CUTOFF, benchmark=gapped)
    assert f.rs_60 is None and f.regime == "UNAVAILABLE"
