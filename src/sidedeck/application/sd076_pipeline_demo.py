"""SD-076 offline Milestone 1 pipeline demo on SYNTHETIC data.

``python -m sidedeck.application.sd076_pipeline_demo`` builds a small synthetic
universe, runs the broad scan and per-track shortlists, derives native
day-trader method signals and pushes them through the decision engine. It
prints a JSON summary. Every number is from generated fixtures: it demonstrates
the plumbing only and is never market coverage or performance evidence.
No network access, credentials, broker or order path is involved.
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sidedeck.application.sd014_strategy_engine import StrategyBar
from sidedeck.application.sd065_market_universe import (
    InstrumentRecord,
    MarketUniverseRegistry,
    SourceCoverage,
    TickerInterval,
    evaluate_eligibility,
)
from sidedeck.application.sd067_market_scanner import DEFAULT_SCORING, build_shortlist, run_broad_scan
from sidedeck.application.sd069_day_trader_methods import daily_signals
from sidedeck.application.sd071_decision_engine import (
    MarketContext,
    PortfolioState,
    TrackPolicy,
    decide,
)
from sidedeck.application.us_equity_calendar import expected_regular_sessions

DATA_BASIS = "SYNTHETIC_FIXTURE"
CUTOFF = date(2026, 10, 21)
PROVENANCE = "sd076 synthetic generator; not market data"


def _synthetic_bars(seed: int, days: tuple[date, ...]) -> tuple[StrategyBar, ...]:
    """Deterministic pseudo-random walk (linear congruential), Decimal only."""
    state = seed * 7919 + 17
    price = Decimal(20 + seed % 180)
    volume = Decimal(200_000 + (seed * 37_000) % 5_000_000)
    bars = []
    for day in days:
        state = (state * 1103515245 + 12345) % (2**31)
        step = (Decimal(state % 2001) - Decimal(1000)) / Decimal(50_000)  # ±2 %
        drift = Decimal(seed % 7 - 3) / Decimal(10_000)
        close = (price * (1 + step + drift)).quantize(Decimal("0.01"))
        high = max(price, close) * Decimal("1.006")
        low = min(price, close) * Decimal("0.994")
        bars.append(StrategyBar(day, price, high.quantize(Decimal("0.01")),
                                low.quantize(Decimal("0.01")), close, volume))
        price = close
    return tuple(bars)


def run_demo(count: int = 60) -> dict[str, Any]:
    days = expected_regular_sessions(date(2025, 6, 2), CUTOFF)
    ids = [f"US:SYN{i:03d}" for i in range(count)]

    def load_bars(cid: str) -> tuple[StrategyBar, ...]:
        # Streamed: bars exist only while one instrument is scanned (memory stays ~flat).
        return _synthetic_bars(int(cid[6:]), days)
    snapshot = date(2025, 6, 2)
    records = tuple(
        InstrumentRecord(
            canonical_id=cid, name=f"Synthetic {cid[3:]}", country="US",
            asset_type="COMMON_STOCK", currency="USD",
            tickers=(TickerInterval(cid[3:], "NASDAQ", snapshot),),
            history_basis="POINT_IN_TIME", provenance=PROVENANCE, listing_date=snapshot,
            coverage=(SourceCoverage(DATA_BASIS, "1D", days[0], days[-1], len(days), PROVENANCE),),
        )
        for cid in ids
    )
    now = datetime(2026, 10, 22, 12, tzinfo=UTC)
    registry = MarketUniverseRegistry(1, now, "sd076 synthetic", records)
    members = registry.universe_as_of(CUTOFF).members
    eligible = [r.canonical_id for r in members
                if evaluate_eligibility(r, CUTOFF, data_source=DATA_BASIS).strategy_eligible]
    benchmark = _synthetic_bars(9999, days)
    report = run_broad_scan(eligible, load_bars, CUTOFF, data_basis=DATA_BASIS,
                            benchmark=benchmark, batch_size=25)
    shortlists = {
        track: build_shortlist(report, cfg) for track, cfg in DEFAULT_SCORING.items()
    }
    cutoff_time = datetime(2026, 10, 21, 20, tzinfo=UTC)
    policy = TrackPolicy(
        policy_id="sd076-demo-swing", track="SWING", virtual_capital=Decimal("1000"),
        max_position_pct=Decimal("0.2"), max_positions=5, max_gross_exposure_pct=Decimal("0.8"),
        max_instrument_total_pct=Decimal("0.25"), max_sector_pct=Decimal("0.4"),
        max_correlation=Decimal("0.85"), risk_per_trade_pct=Decimal("0.01"),
        stop_atr_multiple=Decimal("2"), min_notional=Decimal("10"),
        max_signal_age=timedelta(days=1), max_signal_data_age=timedelta(days=4),
        max_price_age=timedelta(days=1), expires_at=now + timedelta(days=1),
        allowed_strategies=frozenset(),
    )
    decisions: dict[str, int] = {}
    signal_count = 0
    features = {f.canonical_id: f for f in report.features}
    for cand in shortlists["SWING"].research:
        signals = daily_signals(cand.canonical_id, load_bars(cand.canonical_id), CUTOFF,
                                cutoff_time=cutoff_time, generated_at=now)
        signal_count += len(signals)
        feat = features[cand.canonical_id]
        market = MarketContext(cand.canonical_id, feat.last_close, cutoff_time, feat.atr14,
                               "UNKNOWN", session_open=False, execution_eligible=False)
        decision = decide(signals, (), policy, PortfolioState((), {"SWING": Decimal(1000)}),
                          market, now)
        decisions[decision.status] = decisions.get(decision.status, 0) + 1
    return {
        "data_basis": DATA_BASIS,
        "warning": "Synthetic plumbing demo only: not market coverage, signals or performance.",
        "universe_members": len(members),
        "strategy_eligible": len(eligible),
        "scan": {
            "scanned": len(report.features), "excluded": report.exclusion_counts(),
            "batches": report.batches, "bars_read": report.bars_read,
            "duration_seconds": round(report.duration_seconds, 3),
        },
        "shortlists": {
            track: {"quant": len(s.candidates), "research": len(s.research),
                    "filtered": len(s.filtered)}
            for track, s in shortlists.items()
        },
        "swing_method_signals": signal_count,
        "swing_decisions": dict(sorted(decisions.items())),
        "execution_permission": "NOT_GRANTED_BY_DECISION_ENGINE",
    }


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="SD-076 synthetic pipeline demo / throughput")
    parser.add_argument("--count", type=int, default=60, help="synthetic instruments (1-10000)")
    args = parser.parse_args(argv)
    if not 1 <= args.count <= 10_000:
        parser.error("count must be 1-10000")
    print(json.dumps(run_demo(args.count), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
