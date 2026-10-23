"""SD-067 broad deterministic market scanner and per-track quantitative shortlists.

Stage A computes cheap features from caller-supplied daily bars, in bounded
batches with a content-addressed cache so unchanged instruments are not
recomputed. Stage B ranks candidates separately for DAY, SWING and POSITION.

Scores are *ranking heuristics*, not expected returns. A shortlist is research
input only; it never authorizes an order. Bars dated after the cutoff, stale
series and malformed data exclude the instrument (fail closed) with a reason.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Callable, Iterable, Mapping, Sequence

from sidedeck.application.sd014_strategy_engine import StrategyBar
from sidedeck.application.sd089_exchange_calendar import XNYS, ExchangeCalendar
from sidedeck.application.us_equity_calendar import COMPLETE_CALENDAR_YEARS

FEATURE_VERSION = "sd067.features.v1"
TRACKS = ("DAY", "SWING", "POSITION")
_MIN_SESSIONS = 21
_CALENDAR_YEARS = COMPLETE_CALENDAR_YEARS
ZERO = Decimal(0)
ONE = Decimal(1)


class ScanError(ValueError):
    pass


@dataclass(frozen=True)
class ScanFeatures:
    canonical_id: str
    cutoff: date
    sessions: int
    last_close: Decimal
    adv20: Decimal
    dollar_adv20: Decimal
    atr14: Decimal
    atr_pct: Decimal
    vol20: Decimal
    ret_5: Decimal
    ret_20: Decimal
    ret_60: Decimal | None
    ret_126: Decimal | None
    gap_pct: Decimal
    unusual_volume: Decimal
    sma20: Decimal
    sma50: Decimal | None
    sma200: Decimal | None
    breakout_20: bool
    sweep_reversal_20: bool
    rs_60: Decimal | None = None
    regime: str = "UNAVAILABLE"
    spread_bps: Decimal | None = None
    event_flags: tuple[str, ...] = ()
    input_digest: str = ""

    @property
    def above_sma200(self) -> bool | None:
        return None if self.sma200 is None else self.last_close > self.sma200


def _validate(bars: Sequence[StrategyBar]) -> tuple[StrategyBar, ...]:
    ordered = tuple(sorted(bars, key=lambda b: b.day))
    if len({b.day for b in ordered}) != len(ordered):
        raise ScanError("DUPLICATE_BAR")
    for b in ordered:
        values = (b.open, b.high, b.low, b.close, b.volume)
        if any(not isinstance(v, Decimal) or not v.is_finite() or v < 0 for v in values):
            raise ScanError("INVALID_VALUE")
        if min(b.open, b.high, b.low, b.close) <= 0:
            raise ScanError("NON_POSITIVE_PRICE")
        if b.high < max(b.open, b.close) or b.low > min(b.open, b.close):
            raise ScanError("INCONSISTENT_OHLC")
    return ordered


def _require_contiguous(window: Sequence[StrategyBar], cal: ExchangeCalendar = XNYS) -> None:
    """Every regular session of the instrument's exchange between first and last bar."""
    first, last = window[0].day, window[-1].day
    if first.year not in cal.covered_years or last.year not in cal.covered_years:
        raise ScanError("CALENDAR_UNCOVERED")
    if tuple(b.day for b in window) != cal.sessions_between(first, last):
        raise ScanError("MISSING_OR_NON_SESSION_BARS")


def _mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, ZERO) / Decimal(len(values))


def _ret(closes: Sequence[Decimal], n: int) -> Decimal | None:
    return closes[-1] / closes[-1 - n] - ONE if len(closes) > n else None


def _digest(bars: Sequence[StrategyBar], context: str = "") -> str:
    h = hashlib.sha256(FEATURE_VERSION.encode())
    for b in bars:
        h.update(f"{b.day}|{b.open}|{b.high}|{b.low}|{b.close}|{b.volume};".encode())
    h.update(context.encode())
    return h.hexdigest()


def _context(
    benchmark: Sequence[StrategyBar] | None, spread_bps: Decimal | None, event_flags: Iterable[str]
) -> str:
    bench = "none" if benchmark is None else _digest(_validate(benchmark)[-253:])
    return f"|bench={bench}|spread={spread_bps}|events={','.join(sorted(set(event_flags)))}"


def compute_features(
    canonical_id: str,
    bars: Sequence[StrategyBar],
    cutoff: date,
    *,
    benchmark: Sequence[StrategyBar] | None = None,
    spread_bps: Decimal | None = None,
    event_flags: Iterable[str] = (),
    calendar: ExchangeCalendar = XNYS,
) -> ScanFeatures:
    """Features using only bars dated on or before ``cutoff``; later bars are refused.

    ``calendar`` is the instrument's exchange calendar (SD-089); the benchmark must
    trade on the same calendar or relative strength/regime become UNAVAILABLE.
    """
    ordered = _validate(bars)
    if not ordered:
        raise ScanError("NO_BARS")
    if ordered[-1].day > cutoff:
        raise ScanError("FUTURE_BAR")
    if ordered[-1].day != cutoff:
        raise ScanError("STALE")
    window = ordered[-253:]
    if len(window) < _MIN_SESSIONS:
        raise ScanError("INSUFFICIENT_SESSIONS")
    _require_contiguous(window, calendar)
    closes = [b.close for b in window]
    last = window[-1]
    prior = window[-21:-1]
    adv20_prior = _mean([b.volume for b in prior])
    last20 = window[-20:]
    adv20 = _mean([b.volume for b in last20])
    dollar_adv20 = _mean([b.volume * b.close for b in last20])
    trs = [
        max(b.high - b.low, abs(b.high - p.close), abs(b.low - p.close))
        for p, b in zip(window[-15:-1], window[-14:])
    ]
    atr14 = _mean(trs)
    logs = [(c / p).ln() for p, c in zip(closes[-21:-1], closes[-20:])]
    mu = _mean(logs)
    var = sum(((x - mu) ** 2 for x in logs), ZERO) / Decimal(len(logs) - 1)
    vol20 = var.sqrt() * Decimal(252).sqrt()
    flags = tuple(sorted(set(event_flags)))
    prev_high = max(b.high for b in prior)
    prev_low = min(b.low for b in prior)
    rs_60 = regime = None
    if benchmark is not None:
        bench = _validate(benchmark)
        bench = tuple(b for b in bench if b.day <= cutoff)[-253:]
        try:
            if bench:
                _require_contiguous(bench, calendar)
            bench_ok = bool(bench) and bench[-1].day == cutoff
        except ScanError:
            bench_ok = False  # benchmark gaps make RS/regime UNAVAILABLE, not the instrument
        if bench_ok:
            bcloses = [b.close for b in bench]
            own = _ret(closes, 60)
            bench_by_day = {b.day: b.close for b in bench}
            base_close = bench_by_day.get(window[-61].day) if len(window) > 60 else None
            # Relative strength is aligned by date; a missing benchmark date gives None.
            ref = None if base_close is None else bench[-1].close / base_close - ONE
            rs_60 = None if own is None or ref is None else own - ref
            if len(bcloses) >= 200:
                sma200 = _mean(bcloses[-200:])
                sma50 = _mean(bcloses[-50:])
                if bcloses[-1] > sma200 and sma50 > sma200:
                    regime = "RISK_ON"
                elif bcloses[-1] < sma200 and sma50 < sma200:
                    regime = "RISK_OFF"
                else:
                    regime = "NEUTRAL"
    return ScanFeatures(
        canonical_id=canonical_id, cutoff=cutoff, sessions=len(ordered),
        last_close=last.close, adv20=adv20, dollar_adv20=dollar_adv20, atr14=atr14,
        atr_pct=atr14 / last.close, vol20=vol20,
        ret_5=_ret(closes, 5) or ZERO, ret_20=_ret(closes, 20) or ZERO,
        ret_60=_ret(closes, 60), ret_126=_ret(closes, 126),
        gap_pct=last.open / window[-2].close - ONE,
        unusual_volume=(last.volume / adv20_prior) if adv20_prior > 0 else ZERO,
        sma20=_mean(closes[-20:]),
        sma50=_mean(closes[-50:]) if len(closes) >= 50 else None,
        sma200=_mean(closes[-200:]) if len(closes) >= 200 else None,
        breakout_20=last.close > prev_high,
        sweep_reversal_20=last.low < prev_low and last.close > prev_low,
        rs_60=rs_60, regime=regime or "UNAVAILABLE", spread_bps=spread_bps,
        event_flags=flags, input_digest=_digest(window, _context(benchmark, spread_bps, flags)),
    )


@dataclass
class FeatureCache:
    """Content-addressed cache: same instrument, cutoff and input bars -> reuse."""

    entries: dict[tuple[str, date, str], ScanFeatures] = field(default_factory=dict)

    def get(self, cid: str, cutoff: date, digest: str) -> ScanFeatures | None:
        return self.entries.get((cid, cutoff, digest))

    def put(self, features: ScanFeatures) -> None:
        self.entries[(features.canonical_id, features.cutoff, features.input_digest)] = features


@dataclass(frozen=True)
class ScanReport:
    cutoff: date
    universe_size: int
    features: tuple[ScanFeatures, ...]
    excluded: tuple[tuple[str, str], ...]
    cache_hits: int
    batches: int
    bars_read: int
    duration_seconds: float
    data_basis: str

    @property
    def coverage_ratio(self) -> Decimal:
        if self.universe_size == 0:
            return ZERO
        return Decimal(len(self.features)) / Decimal(self.universe_size)

    def exclusion_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for _, reason in self.excluded:
            counts[reason] = counts.get(reason, 0) + 1
        return dict(sorted(counts.items()))


BarLoader = Callable[[str], Sequence[StrategyBar]]


def run_broad_scan(
    universe: Sequence[str],
    load_bars: BarLoader,
    cutoff: date,
    *,
    data_basis: str,
    batch_size: int = 250,
    cache: FeatureCache | None = None,
    benchmark: Sequence[StrategyBar] | None = None,
    spreads: Mapping[str, Decimal] | None = None,
    events: Mapping[str, Iterable[str]] | None = None,
    clock: Callable[[], float] = time.perf_counter,
    calendar: ExchangeCalendar = XNYS,
) -> ScanReport:
    """Scan ``universe`` in bounded batches. One instrument's failure never stops the scan.

    ``data_basis`` must say what the bars are (e.g. ``FIXTURE`` or a source id); a
    fixture scan is never reported as market coverage. All instruments in one scan
    share ``calendar``; scan each exchange separately.
    """
    if cutoff.year not in calendar.covered_years or not calendar.is_session(cutoff):
        raise ScanError("cutoff must be a regular session inside the verified calendar")
    if not data_basis.strip():
        raise ScanError("data_basis is required")
    if not 1 <= batch_size <= 5000:
        raise ScanError("batch_size must be between 1 and 5000")
    if len(set(universe)) != len(universe):
        raise ScanError("universe contains duplicate ids")
    cache = cache if cache is not None else FeatureCache()
    bench_ctx = "|bench=" + ("none" if benchmark is None else _digest(_validate(benchmark)[-253:]))
    start = clock()
    features: list[ScanFeatures] = []
    excluded: list[tuple[str, str]] = []
    hits = bars_read = batches = 0
    ordered = sorted(universe)
    for offset in range(0, len(ordered), batch_size):
        batches += 1
        for cid in ordered[offset:offset + batch_size]:
            try:
                bars = tuple(load_bars(cid))
            except Exception:  # noqa: BLE001 - isolate any loader failure per instrument
                excluded.append((cid, "LOAD_FAILED"))
                continue
            bars_read += len(bars)
            spread = (spreads or {}).get(cid)
            flags = tuple((events or {}).get(cid, ()))
            try:
                window = _validate(bars)[-253:]
                key = _digest(window, bench_ctx + f"|spread={spread}|events="
                              f"{','.join(sorted(set(flags)))}")
                cached = cache.get(cid, cutoff, key)
                if cached is not None:
                    hits += 1
                    features.append(cached)
                    continue
                feat = compute_features(
                    cid, bars, cutoff, benchmark=benchmark, spread_bps=spread, event_flags=flags,
                    calendar=calendar,
                )
            except ScanError as exc:
                excluded.append((cid, str(exc)))
                continue
            except (AttributeError, TypeError, ArithmeticError):
                excluded.append((cid, "MALFORMED_BAR"))
                continue
            cache.put(feat)
            features.append(feat)
    return ScanReport(
        cutoff, len(ordered), tuple(features), tuple(excluded), hits, batches, bars_read,
        clock() - start, data_basis,
    )


# --- Stage B: per-track quantitative shortlist -------------------------------------

@dataclass(frozen=True)
class TrackScoring:
    track: str
    min_price: Decimal
    min_dollar_adv: Decimal
    min_sessions: int
    weights: tuple[tuple[str, Decimal], ...]
    max_atr_pct: Decimal | None = None
    min_atr_pct: Decimal | None = None
    max_spread_bps: Decimal | None = None
    require_above_sma200: bool = False
    exclude_event_flags: tuple[str, ...] = ()
    quant_size: int = 200
    research_size: int = 20

    def __post_init__(self) -> None:
        if self.track not in TRACKS:
            raise ScanError(f"unknown track {self.track}")
        if not 1 <= self.research_size <= self.quant_size <= 1000:
            raise ScanError("shortlist sizes must satisfy 1 <= research <= quant <= 1000")
        if not self.weights or any(w == 0 for _, w in self.weights):
            raise ScanError("non-zero weights are required")
        unknown = {name for name, _ in self.weights} - set(_FEATURE_GETTERS)
        if unknown:
            raise ScanError(f"unknown scoring features {sorted(unknown)}")


def _b(flag: bool) -> Decimal:
    return ONE if flag else ZERO


_FEATURE_GETTERS: dict[str, Callable[[ScanFeatures], Decimal | None]] = {
    "ret_5": lambda f: f.ret_5,
    "ret_20": lambda f: f.ret_20,
    "ret_60": lambda f: f.ret_60,
    "ret_126": lambda f: f.ret_126,
    "rs_60": lambda f: f.rs_60,
    "abs_gap": lambda f: abs(f.gap_pct),
    "atr_pct": lambda f: f.atr_pct,
    "vol20": lambda f: f.vol20,
    "unusual_volume": lambda f: f.unusual_volume,
    "dollar_adv20": lambda f: f.dollar_adv20,
    "breakout_20": lambda f: _b(f.breakout_20),
    "sweep_reversal_20": lambda f: _b(f.sweep_reversal_20),
}

DEFAULT_SCORING: dict[str, TrackScoring] = {
    "DAY": TrackScoring(
        "DAY", Decimal("5"), Decimal("50000000"), 21,
        (("unusual_volume", Decimal("0.35")), ("abs_gap", Decimal("0.25")),
         ("atr_pct", Decimal("0.20")), ("ret_5", Decimal("0.20"))),
        min_atr_pct=Decimal("0.02"), max_spread_bps=Decimal("10"),
        exclude_event_flags=("EARNINGS_TODAY",), quant_size=150, research_size=15,
    ),
    "SWING": TrackScoring(
        "SWING", Decimal("5"), Decimal("20000000"), 61,
        (("rs_60", Decimal("0.30")), ("ret_20", Decimal("0.25")),
         ("unusual_volume", Decimal("0.20")), ("breakout_20", Decimal("0.15")),
         ("sweep_reversal_20", Decimal("0.10"))),
        max_atr_pct=Decimal("0.08"), exclude_event_flags=("EARNINGS_WITHIN_5D",),
        quant_size=200, research_size=20,
    ),
    "POSITION": TrackScoring(
        "POSITION", Decimal("10"), Decimal("10000000"), 252,
        (("ret_126", Decimal("0.35")), ("rs_60", Decimal("0.25")),
         ("vol20", Decimal("-0.25")), ("ret_60", Decimal("0.15"))),
        require_above_sma200=True, quant_size=150, research_size=15,
    ),
}


@dataclass(frozen=True)
class Candidate:
    canonical_id: str
    track: str
    rank: int
    score: Decimal
    components: tuple[tuple[str, Decimal | None], ...]
    missing_features: tuple[str, ...]


@dataclass(frozen=True)
class Shortlist:
    track: str
    cutoff: date
    data_basis: str
    candidates: tuple[Candidate, ...]
    research: tuple[Candidate, ...]
    filtered: tuple[tuple[str, str], ...]
    note: str = "Ranking heuristic only; not an expected return or an order authorization."


def _filter_reason(f: ScanFeatures, cfg: TrackScoring) -> str | None:
    if f.sessions < cfg.min_sessions:
        return "INSUFFICIENT_SESSIONS"
    if f.last_close < cfg.min_price:
        return "PRICE_BELOW_MIN"
    if f.dollar_adv20 < cfg.min_dollar_adv:
        return "ILLIQUID"
    if cfg.max_atr_pct is not None and f.atr_pct > cfg.max_atr_pct:
        return "TOO_VOLATILE"
    if cfg.min_atr_pct is not None and f.atr_pct < cfg.min_atr_pct:
        return "INSUFFICIENT_RANGE"
    if cfg.max_spread_bps is not None:
        if f.spread_bps is None:
            return "SPREAD_UNAVAILABLE"
        if f.spread_bps > cfg.max_spread_bps:
            return "SPREAD_TOO_WIDE"
    if cfg.require_above_sma200 and f.above_sma200 is not True:
        return "BELOW_OR_NO_SMA200"
    if set(cfg.exclude_event_flags) & set(f.event_flags):
        return "EVENT_EXCLUDED"
    return None


def _percentile_ranks(values: Sequence[tuple[str, Decimal]]) -> dict[str, Decimal]:
    """Average-rank percentiles in [0, 1]; ties share a rank, deterministic."""
    if len(values) == 1:
        return {values[0][0]: Decimal("0.5")}
    ordered = sorted(values, key=lambda item: (item[1], item[0]))
    ranks: dict[str, Decimal] = {}
    i = 0
    denom = Decimal(len(ordered) - 1)
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        pct = Decimal(i + j) / 2 / denom
        for k in range(i, j + 1):
            ranks[ordered[k][0]] = pct
        i = j + 1
    return ranks


def build_shortlist(report: ScanReport, cfg: TrackScoring) -> Shortlist:
    eligible: list[ScanFeatures] = []
    filtered: list[tuple[str, str]] = []
    for f in report.features:
        reason = _filter_reason(f, cfg)
        if reason:
            filtered.append((f.canonical_id, reason))
        else:
            eligible.append(f)
    by_feature: dict[str, dict[str, Decimal]] = {}
    for name, _ in cfg.weights:
        getter = _FEATURE_GETTERS[name]
        present = [(f.canonical_id, v) for f in eligible if (v := getter(f)) is not None]
        by_feature[name] = _percentile_ranks(present) if present else {}
    scored: list[tuple[Decimal, str, Candidate]] = []
    for f in eligible:
        score = ZERO
        components: list[tuple[str, Decimal | None]] = []
        missing: list[str] = []
        for name, weight in cfg.weights:
            pct = by_feature[name].get(f.canonical_id)
            if pct is None:
                missing.append(name)  # a missing feature contributes nothing, never a guess
                components.append((name, None))
                continue
            contribution = weight * (pct if weight > 0 else pct - ONE)
            score += contribution
            components.append((name, contribution))
        scored.append((score, f.canonical_id,
                       Candidate(f.canonical_id, cfg.track, 0, score, tuple(components),
                                 tuple(missing))))
    scored.sort(key=lambda item: (-item[0], item[1]))
    ranked = tuple(
        Candidate(c.canonical_id, c.track, i + 1, c.score, c.components, c.missing_features)
        for i, (_, _, c) in enumerate(scored[:cfg.quant_size])
    )
    return Shortlist(cfg.track, report.cutoff, report.data_basis, ranked,
                     ranked[:cfg.research_size], tuple(filtered))
