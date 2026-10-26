"""SD-112 cross-instrument (pooled) out-of-sample admission — PROPOSAL ONLY.

Owner direction 2026-10-26: design and offline-test a pooled strategy-level admission method;
do **not** change the production gate (SD-022 + SD-071 per-instrument floor) and do not admit
anything automatically. This module produces evidence for owner review only.

Method (all rules fixed before any result is seen):

1. **One fixed strategy version** (catalogue parameters, no fitting) on every instrument.
2. **Shared chronological splits** on the sessions common to all instruments. Sessions
   before ``HOLDOUT_START`` (2026-10-26): first 60 % TRAIN (reported, never used to fit),
   the rest pooled OOS. These bars were already examined in SD-021/SD-022, which is
   disclosed and counted in the multiple-testing family. The FINAL HOLDOUT is every session
   from ``HOLDOUT_START`` on: genuinely unseen data that accrues with authorized fresh bars.
   It stays **sealed** (a commitment to the fixed cut-off and strategy version) until the
   owner unseals it once with >= 40 sessions available; a data refresh cannot re-arm it.
3. Trades: signal at a close, entry and exit at the next session's close (the SD-014
   ``NEXT_OBSERVED_CLOSE_INTERVAL`` assumption), costs per side = fee + slippage. A trade
   belongs to the segment containing its entry; one that exits in a later segment is
   excluded (``CROSSES_BOUNDARY``) so no holdout bar is used.
4. **Effective sample size** = min(time-overlap clusters, correlation design effect
   ``n / (1 + (k - 1) * mean pairwise correlation)`` of instruments' daily strategy returns).
   Correlated or simultaneous trades are never counted as independent.
5. **Uncertainty**: cluster block bootstrap of pooled profit factor and mean trade return; the
   lower bound uses a Bonferroni-adjusted one-sided level across the strategies tested.
6. **Concentration** (share of net profit from the best instrument and from the top 10 % of
   trades), **regimes** (benchmark above/below its 50-session SMA at entry), **2x cost
   stress**, and an equal-weight buy-and-hold **benchmark** over the OOS window.
7. Every instrument is pooled (no cherry-picking). Instruments that lose on their own are
   also listed as **instrument-level exclusions** that would apply even if the strategy were
   later admitted.

Verdicts: ``PROPOSED_FOR_OWNER_REVIEW`` (all criteria met; holdout still sealed),
``INSUFFICIENT_EVIDENCE`` or ``REJECTED``. Never ``ADMITTED``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from sidedeck.application.sd014_strategy_engine import StrategyBar, generate_signals
from sidedeck.application.sd103_trading_pipeline import (
    REAL_DATA, SIGNAL_STRATEGIES, MarketEvidence, _spec, admit_market_data, load_bundle,
)

SCHEMA = "sidedeck-pooled-admission-proposal/2"
TRAIN_FRACTION = Decimal("0.60")         # of the pre-holdout sessions; the rest is pooled OOS
# The FINAL HOLDOUT is pinned by calendar, not by a fraction: every bar up to 2026-10-23 was
# already examined (SD-021/SD-022 80/20 split, then this method), so the only untouched data
# is sessions from 2026-10-26 onward. It accrues as authorized fresh data arrives.
HOLDOUT_START = date(2026, 10, 26)
MIN_HOLDOUT_SESSIONS = 40                # about two months before a single owner unseal
PRIOR_LOOKS = 2                          # SD-021/SD-022 split + this pooled split
COST_BPS_PER_SIDE = Decimal("10")        # fee 5 + slippage 5
BOOTSTRAP_SAMPLES = 2000
BOOTSTRAP_SEED = 103
ALPHA = 0.05
HOLDOUT_PASS = {"min_profit_factor": 1.0, "min_mean_return": 0.0}   # pre-declared
CRITERIA = {
    "min_effective_sample_size": 30,
    "min_pooled_profit_factor": 1.15,
    "min_bootstrap_lower_profit_factor": 1.0,
    "min_stressed_profit_factor": 1.0,          # at 2x costs
    "max_top_instrument_profit_share": 0.5,
    "min_regime_profit_factor": 0.8,            # any regime with >= 5 trades
    "min_regime_trades": 5,
    "instrument_exclusion_min_trades": 5,
}
VERDICTS = ("PROPOSED_FOR_OWNER_REVIEW", "INSUFFICIENT_EVIDENCE", "REJECTED")
DATA_DIR = Path(__file__).resolve().parents[3] / "data"


class PooledAdmissionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Trade:
    instrument: str
    entry_day: date
    exit_day: date
    entry: Decimal
    exit: Decimal
    segment: str

    def ret(self, cost_bps: Decimal) -> float:
        c = cost_bps / Decimal(10000)
        return float(self.exit * (1 - c) / (self.entry * (1 + c)) - 1)


def segments(common: Sequence[date]) -> dict[str, tuple[date, date]]:
    """TRAIN / OOS split the sessions before ``HOLDOUT_START``; HOLDOUT is every session from
    ``HOLDOUT_START`` (possibly none yet)."""
    pre = [d for d in common if d < HOLDOUT_START]
    if len(pre) < 300:
        raise PooledAdmissionError("not enough common sessions before the holdout")
    train_end = int(len(pre) * TRAIN_FRACTION)
    return {"TRAIN": (pre[0], pre[train_end - 1]), "OOS": (pre[train_end], pre[-1]),
            "HOLDOUT": (HOLDOUT_START, date.max)}


def holdout_commitment(strategy_id: str) -> str:
    """Binds the holdout to a fixed calendar cut-off and strategy version, independent of
    later data refreshes (so a refresh can never mint a fresh 'untouched' holdout)."""
    return hashlib.sha256(json.dumps(
        {"holdout_start": HOLDOUT_START.isoformat(), "strategy": strategy_id,
         "version": _spec(strategy_id).version, "schema": SCHEMA},
        sort_keys=True).encode()).hexdigest()


def _segment_of(day: date, seg: Mapping[str, tuple[date, date]]) -> str:
    for name, (lo, hi) in seg.items():
        if lo <= day <= hi:
            return name
    return "OUTSIDE"


def trades_for(strategy_id: str, bars: Sequence[StrategyBar],
               seg: Mapping[str, tuple[date, date]], instrument: str) -> tuple[list[Trade], int]:
    """Round trips from the causal signal map; returns (kept trades, boundary exclusions)."""
    signals = generate_signals(_spec(strategy_id), bars)
    kept: list[Trade] = []
    crossed = 0
    open_at: tuple[date, Decimal] | None = None
    for i, bar in enumerate(bars[:-1]):
        nxt = bars[i + 1]
        sig = signals.get(bar.day, "HOLD")
        if sig == "BUY" and open_at is None:
            open_at = (nxt.day, nxt.close)
        elif sig == "SELL" and open_at is not None:
            entry_seg, exit_seg = _segment_of(open_at[0], seg), _segment_of(nxt.day, seg)
            if entry_seg == exit_seg and entry_seg != "OUTSIDE":
                kept.append(Trade(instrument, open_at[0], nxt.day, open_at[1], nxt.close,
                                  entry_seg))
            elif entry_seg != "OUTSIDE":
                crossed += 1               # entered in a segment, exited in a later one
            open_at = None
    return kept, crossed


def profit_factor(returns: Sequence[float]) -> float | None:
    if not returns:
        return None
    gains = sum(r for r in returns if r > 0)
    losses = -sum(r for r in returns if r < 0)
    return math.inf if losses == 0 else gains / losses


def clusters(trades: Sequence[Trade]) -> list[list[Trade]]:
    """Trades whose holding intervals overlap (any instrument) form one cluster."""
    ordered = sorted(trades, key=lambda t: (t.entry_day, t.instrument))
    out: list[list[Trade]] = []
    end: date | None = None
    for t in ordered:
        if out and end is not None and t.entry_day <= end:
            out[-1].append(t)
            end = max(end, t.exit_day)
        else:
            out.append([t])
            end = t.exit_day
    return out


def _daily_strategy_returns(bars: Sequence[StrategyBar], trades: Sequence[Trade],
                            window: tuple[date, date]) -> dict[date, float]:
    held: set[date] = set()
    days = [b.day for b in bars]
    for t in trades:
        held.update(d for d in days if t.entry_day < d <= t.exit_day)
    out = {}
    for prev, bar in zip(bars, bars[1:]):
        if window[0] <= bar.day <= window[1]:
            out[bar.day] = float(bar.close / prev.close - 1) if bar.day in held else 0.0
    return out


def mean_pairwise_correlation(series: Mapping[str, Mapping[date, float]]
                              ) -> tuple[float, int]:
    """Mean pairwise correlation (negative clipped to 0) and the number of usable pairs."""
    names = sorted(series)
    values = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            days = sorted(set(series[a]) & set(series[b]))
            if len(days) < 20:
                continue
            xa = [series[a][d] for d in days]
            xb = [series[b][d] for d in days]
            ma, mb = sum(xa) / len(xa), sum(xb) / len(xb)
            va = sum((x - ma) ** 2 for x in xa)
            vb = sum((y - mb) ** 2 for y in xb)
            if va == 0 or vb == 0:
                continue
            values.append(sum((x - ma) * (y - mb) for x, y in zip(xa, xb)) / math.sqrt(va * vb))
    return (max(0.0, sum(values) / len(values)) if values else 0.0), len(values)


def bootstrap_lower(groups: Sequence[Sequence[float]], *,
                    level: float) -> dict[str, float | None]:
    if not groups:
        return {"profit_factor": None, "mean_return": None}
    rng = random.Random(BOOTSTRAP_SEED)
    pfs, means = [], []
    for _ in range(BOOTSTRAP_SAMPLES):
        sample = [r for _ in groups for r in groups[rng.randrange(len(groups))]]
        pf = profit_factor(sample)
        pfs.append(1e9 if pf is None or math.isinf(pf) else pf)
        means.append(sum(sample) / len(sample))
    pfs.sort()
    means.sort()
    k = max(0, min(BOOTSTRAP_SAMPLES - 1, int(level * BOOTSTRAP_SAMPLES)))
    return {"profit_factor": pfs[k], "mean_return": means[k]}


def _regime(benchmark: Sequence[StrategyBar]) -> dict[date, str]:
    out, closes = {}, [b.close for b in benchmark]
    for i, bar in enumerate(benchmark):
        if i >= 50:
            sma = sum(closes[i - 50:i], Decimal(0)) / 50
            out[bar.day] = "UPTREND" if bar.close > sma else "DOWNTREND"
    return out


def _r(value: float | None, digits: int = 4) -> float | str | None:
    if value is None:
        return None
    if math.isinf(value):
        return "INF_NO_LOSSES"
    return round(value, digits)


def evaluate_strategy(strategy_id: str, evidence: Mapping[str, MarketEvidence], *,
                      tested_strategies: int, benchmark_id: str = "US:SPY") -> dict[str, Any]:
    common = sorted(set.intersection(*(set(b.day for b in ev.bars) for ev in evidence.values())))
    seg = segments(common)
    commitment = holdout_commitment(strategy_id)
    per: dict[str, list[Trade]] = {}
    crossed_total = 0
    for cid, ev in evidence.items():
        trades, crossed = trades_for(strategy_id, ev.bars, seg, cid)
        per[cid] = trades
        crossed_total += crossed
    oos = [t for ts in per.values() for t in ts if t.segment == "OOS"]
    rets = [t.ret(COST_BPS_PER_SIDE) for t in oos]
    stressed = [t.ret(COST_BPS_PER_SIDE * 2) for t in oos]
    groups = [[t.ret(COST_BPS_PER_SIDE) for t in c] for c in clusters(oos)]
    series = {cid: _daily_strategy_returns(evidence[cid].bars,
                                           [t for t in ts if t.segment == "OOS"], seg["OOS"])
              for cid, ts in per.items()}
    rho, pairs = mean_pairwise_correlation(series)
    contributing = sum(1 for ts in per.values() if any(t.segment == "OOS" for t in ts))
    n_eff_corr = len(oos) / (1 + max(contributing - 1, 0) * rho) if oos else 0.0
    n_eff = min(len(groups), n_eff_corr)
    family = max(tested_strategies, 1) * PRIOR_LOOKS
    level = ALPHA / family
    lower = bootstrap_lower(groups, level=level)
    instruments = {}
    for cid, ts in sorted(per.items()):
        r = [t.ret(COST_BPS_PER_SIDE) for t in ts if t.segment == "OOS"]
        pf_i = profit_factor(r)
        excluded = (len(r) >= CRITERIA["instrument_exclusion_min_trades"]
                    and pf_i is not None and pf_i < 1)
        instruments[cid] = {"oos_trades": len(r), "profit_factor": _r(pf_i),
                            "net_return_sum": _r(sum(r)),
                            "train_trades": sum(1 for t in ts if t.segment == "TRAIN"),
                            "instrument_exclusion": ("EXCLUDED_LOSES_ON_ITS_OWN" if excluded
                                                     else "NONE")}
    by_instrument = {cid: sum(t.ret(COST_BPS_PER_SIDE) for t in ts if t.segment == "OOS")
                     for cid, ts in per.items()}
    positive = {k: v for k, v in by_instrument.items() if v > 0}
    net = sum(rets)
    top_share = (max(positive.values()) / sum(positive.values())) if positive else None
    top_trades = sorted(rets, reverse=True)[:max(1, len(rets) // 10)]
    top_trade_share = (sum(top_trades) / net) if net > 0 else None
    regimes: dict[str, list[float]] = {"UPTREND": [], "DOWNTREND": []}
    bench = evidence.get(benchmark_id)
    if bench is not None:
        labels = _regime(bench.bars)
        for t in oos:
            if t.entry_day in labels:
                regimes[labels[t.entry_day]].append(t.ret(COST_BPS_PER_SIDE))
    bench_returns, strategy_returns, exposures = [], [], []
    for cid, ev in evidence.items():
        window = [b for b in ev.bars if seg["OOS"][0] <= b.day <= seg["OOS"][1]]
        if len(window) >= 2:
            bench_returns.append(float(window[-1].close / window[0].close - 1))
        daily = series[cid]
        growth = 1.0
        for value in daily.values():
            growth *= 1 + value
        strategy_returns.append(growth - 1)
        exposures.append(sum(1 for v in daily.values() if v != 0) / len(daily) if daily else 0.0)
    pooled_pf = profit_factor(rets)
    stressed_pf = profit_factor(stressed)
    reasons = []
    if n_eff < CRITERIA["min_effective_sample_size"]:
        reasons.append(f"EFFECTIVE_SAMPLE_{n_eff:.1f}_BELOW_"
                       f"{CRITERIA['min_effective_sample_size']}")
    if pooled_pf is None or pooled_pf < CRITERIA["min_pooled_profit_factor"]:
        reasons.append("POOLED_PROFIT_FACTOR_BELOW_THRESHOLD")
    if lower["profit_factor"] is None or lower["profit_factor"] <= \
            CRITERIA["min_bootstrap_lower_profit_factor"]:
        reasons.append("BOOTSTRAP_LOWER_PROFIT_FACTOR_NOT_ABOVE_1")
    if stressed_pf is None or stressed_pf <= CRITERIA["min_stressed_profit_factor"]:
        reasons.append("FAILS_2X_COST_STRESS")
    if top_share is not None and top_share > CRITERIA["max_top_instrument_profit_share"]:
        reasons.append("PROFIT_CONCENTRATED_IN_ONE_INSTRUMENT")
    if bench is None:
        reasons.append("REGIME_BENCHMARK_UNAVAILABLE")
    else:
        for name, r in regimes.items():
            pf = profit_factor(r)
            if len(r) < CRITERIA["min_regime_trades"]:
                reasons.append(f"REGIME_NOT_COVERED_{name}")
            elif pf is not None and pf < CRITERIA["min_regime_profit_factor"]:
                reasons.append(f"WEAK_IN_{name}")
    insufficient = ("EFFECTIVE_SAMPLE", "REGIME_NOT_COVERED", "REGIME_BENCHMARK_UNAVAILABLE")
    if not reasons:
        verdict = "PROPOSED_FOR_OWNER_REVIEW"
    elif pooled_pf is None or any(r.startswith(insufficient) for r in reasons):
        verdict = "INSUFFICIENT_EVIDENCE"
    else:
        verdict = "REJECTED"
    return {
        "strategy": f"{strategy_id}@{_spec(strategy_id).version}",
        "parameters": dict(_spec(strategy_id).parameters), "verdict": verdict,
        "reasons": reasons,
        "segments": {k: [str(a), str(b)] for k, (a, b) in seg.items() if k != "HOLDOUT"},
        "holdout": {"status": "SEALED", "starts": HOLDOUT_START.isoformat(),
                    "commitment_sha256": commitment,
                    "sessions_available": sum(1 for d in common if d >= HOLDOUT_START),
                    "min_sessions_to_unseal": MIN_HOLDOUT_SESSIONS,
                    "pass_rule": dict(HOLDOUT_PASS)},
        "instruments": instruments,
        "pooled_oos": {"trades": len(oos), "profit_factor": _r(pooled_pf),
                       "mean_return": _r(sum(rets) / len(rets) if rets else None, 6),
                       "win_rate": _r(sum(1 for r in rets if r > 0) / len(rets)
                                      if rets else None),
                       "boundary_exclusions": crossed_total},
        "effective_sample_size": {"value": round(n_eff, 2), "overlap_clusters": len(groups),
                                  "correlation_design_effect": round(n_eff_corr, 2),
                                  "mean_pairwise_correlation": round(rho, 4),
                                  "correlation_pairs_used": pairs,
                                  "correlation_evidence": ("AVAILABLE" if pairs else
                                                           "NONE_ASSUMED_ZERO_CLUSTER_CAP_APPLIES"),
                                  "contributing_instruments": contributing},
        "uncertainty": {"bootstrap_samples": BOOTSTRAP_SAMPLES, "one_sided_level": level,
                        "bonferroni_family": family,
                        "family_basis": f"{tested_strategies} strategies x {PRIOR_LOOKS} "
                                        "looks at these data (SD-021/SD-022 and this split)",
                        "lower_profit_factor": _r(lower["profit_factor"]),
                        "lower_mean_return": _r(lower["mean_return"], 6)},
        "concentration": {"top_instrument_profit_share": _r(top_share),
                          "top_10pct_trades_profit_share": _r(top_trade_share)},
        "regimes": {k: {"trades": len(v), "profit_factor": _r(profit_factor(v))}
                    for k, v in regimes.items()},
        "costs": {"per_side_bps": str(COST_BPS_PER_SIDE),
                  "stressed_2x_profit_factor": _r(stressed_pf)},
        "benchmark": {"equal_weight_buy_and_hold_oos_return": _r(
            sum(bench_returns) / len(bench_returns) if bench_returns else None),
            "equal_weight_strategy_oos_return": _r(
                sum(strategy_returns) / len(strategy_returns) if strategy_returns else None),
            "strategy_mean_exposure": _r(sum(exposures) / len(exposures) if exposures else None),
            "role": "CONTEXT_ONLY_NOT_A_CRITERION (long/flat strategies with partial exposure "
                    "are compared with full-exposure buy-and-hold)",
            "basis": "PRICE_ONLY_EXCLUDES_DIVIDENDS"}}


def _admit_all(bundles: Sequence[tuple[dict[str, Any], str]], basis: str
               ) -> tuple[dict[str, MarketEvidence], dict[str, str]]:
    evidence: dict[str, MarketEvidence] = {}
    excluded: dict[str, str] = {}
    for payload, sha in bundles:
        try:
            ev = admit_market_data(payload, basis=basis, through=date(2026, 12, 31),
                                   source_sha256=sha)
            evidence[ev.canonical_id] = ev
        except Exception as exc:  # noqa: BLE001 - every exclusion is reported
            excluded[str(payload.get("instrument_id"))] = str(exc)[:200]
    return evidence, excluded


def proposal(bundles: Sequence[tuple[dict[str, Any], str]], *, basis: str = REAL_DATA,
             strategies: Sequence[str] = SIGNAL_STRATEGIES) -> dict[str, Any]:
    evidence, excluded = _admit_all(bundles, basis)
    if len(evidence) < 2:
        raise PooledAdmissionError("pooling needs at least two admissible instruments")
    results = [evaluate_strategy(s, evidence, tested_strategies=len(strategies))
               for s in strategies]
    return {"schema": SCHEMA, "status": "PROPOSAL_ONLY", "data_basis": basis,
            "generated_at": datetime.now(UTC).isoformat(),
            "production_admission_gate": "UNCHANGED (SD-022 + SD-071 per instrument)",
            "instruments": sorted(evidence), "excluded_instruments": excluded,
            "criteria": dict(CRITERIA), "strategies": results,
            "note": "No strategy is admitted by this report. The holdout stays sealed until the "
                    "owner reviews the method and these results."}


def reveal_holdout(strategy_id: str, bundles: Sequence[tuple[dict[str, Any], str]], *,
                   marker_dir: Path, owner_unseal: bool, basis: str = REAL_DATA
                   ) -> dict[str, Any]:
    """One-time owner unseal of the calendar-pinned holdout for one strategy version.

    Refused (without consuming anything) until at least ``MIN_HOLDOUT_SESSIONS`` common
    sessions exist on or after ``HOLDOUT_START``. The one-time marker is keyed to the fixed
    cut-off and strategy version, so a data refresh can never re-arm it. The pass rule is
    pre-declared (``HOLDOUT_PASS``)."""
    if not owner_unseal:
        raise PooledAdmissionError("the holdout is unsealed only on explicit owner instruction")
    evidence, _excluded = _admit_all(bundles, basis)
    if len(evidence) < 2:
        raise PooledAdmissionError("pooling needs at least two admissible instruments")
    common = sorted(set.intersection(*(set(b.day for b in ev.bars) for ev in evidence.values())))
    available = sum(1 for d in common if d >= HOLDOUT_START)
    if available < MIN_HOLDOUT_SESSIONS:
        raise PooledAdmissionError(f"holdout has {available} sessions; at least "
                                   f"{MIN_HOLDOUT_SESSIONS} are needed (nothing consumed)")
    seg = segments(common)
    commitment = holdout_commitment(strategy_id)
    marker = marker_dir / f"holdout-revealed-{commitment[:16]}.json"
    marker_dir.mkdir(parents=True, exist_ok=True)
    try:
        with marker.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps({"strategy": strategy_id, "holdout_start":
                                     HOLDOUT_START.isoformat(),
                                     "revealed_at": datetime.now(UTC).isoformat()}))
    except FileExistsError:
        raise PooledAdmissionError("this holdout was already revealed; it is no longer "
                                   "untouched") from None
    trades = [t for cid, ev in evidence.items()
              for t in trades_for(strategy_id, ev.bars, seg, cid)[0] if t.segment == "HOLDOUT"]
    rets = [t.ret(COST_BPS_PER_SIDE) for t in trades]
    pf = profit_factor(rets)
    mean = sum(rets) / len(rets) if rets else None
    passed = (pf is not None and mean is not None and pf >= HOLDOUT_PASS["min_profit_factor"]
              and mean > HOLDOUT_PASS["min_mean_return"])
    return {"strategy": f"{strategy_id}@{_spec(strategy_id).version}",
            "holdout_sessions": available, "holdout_trades": len(rets),
            "holdout_profit_factor": _r(pf), "holdout_mean_return": _r(mean, 6),
            "pass_rule": dict(HOLDOUT_PASS), "result": "PASS" if passed else "FAIL",
            "status": "REVEALED_ONCE", "marker": str(marker)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SD-112 pooled OOS admission proposal")
    parser.add_argument("--bundles", nargs="*", default=[
        str(DATA_DIR / f"sd021-{t}-admitted.json") for t in ("spy", "qqq", "msft")])
    parser.add_argument("--out", default=str(DATA_DIR / "sd112" / "pooled-proposal.json"))
    args = parser.parse_args(argv)
    report = proposal([load_bundle(Path(p)) for p in args.bundles])
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"report": str(target), "instruments": report["instruments"],
                      "strategies": [{"strategy": s["strategy"], "verdict": s["verdict"],
                                      "reasons": s["reasons"],
                                      "oos_trades": s["pooled_oos"]["trades"],
                                      "n_eff": s["effective_sample_size"]["value"],
                                      "pooled_pf": s["pooled_oos"]["profit_factor"],
                                      "instruments": s["instruments"]}
                                     for s in report["strategies"]]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
