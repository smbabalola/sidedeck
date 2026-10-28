"""SD-069 native re-implementation of day-trader-skill scanner setups (offline).

Methodology attribution: the setup rules follow the MIT-licensed
``day-trader-skill`` 2.0.0 ``trader-scanner`` documentation (Copyright (c) 2026
Jake Schincariol). No code from that package runs here and no Claude/LLM is
involved at runtime: SideDeck evaluates the rules deterministically on bars the
caller supplies, and emits ``ResearchSignal`` opinions of kind
``DAY_TRADER_METHOD``. A setup is "a chart matched a rule", never a buy
recommendation; the SD-071 decision engine caps such signals at WATCHLIST.

Daily setups (closes only, complete sessions on or before the cutoff):
``breakout_20d``, ``bull_flag``, ``reclaim_ma20``, ``oversold`` (Wilder RSI14 < 30),
``oversold_bounce``. Intraday: 5-minute opening-range breakout on completed bars.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Sequence

from sidedeck.application.sd014_strategy_engine import StrategyBar
from sidedeck.application.sd068_track_scheduler import NEW_YORK, session_for
from sidedeck.application.sd070_research_signal import EvidenceRef, ResearchSignal

METHOD_VERSION = "dts-2.0.0-native.1"
ZERO = Decimal(0)
HUNDRED = Decimal(100)


class MethodError(ValueError):
    pass


def wilder_rsi(closes: Sequence[Decimal], n: int = 14) -> Decimal | None:
    if len(closes) < n + 1:
        return None
    gains = [max(ZERO, b - a) for a, b in zip(closes, closes[1:])]
    losses = [max(ZERO, a - b) for a, b in zip(closes, closes[1:])]
    avg_gain = sum(gains[:n], ZERO) / n
    avg_loss = sum(losses[:n], ZERO) / n
    for g, loss in zip(gains[n:], losses[n:]):
        avg_gain = (avg_gain * (n - 1) + g) / n
        avg_loss = (avg_loss * (n - 1) + loss) / n
    if avg_loss == 0:
        return HUNDRED
    return HUNDRED - HUNDRED / (1 + avg_gain / avg_loss)


def _closes(bars: Sequence[StrategyBar], cutoff: date) -> list[tuple[date, Decimal]]:
    ordered = sorted(bars, key=lambda b: b.day)
    if len({b.day for b in ordered}) != len(ordered):
        raise MethodError("duplicate daily bars")
    if any(b.day > cutoff for b in ordered):
        raise MethodError("bars after the cutoff (look-ahead)")
    if not ordered or ordered[-1].day != cutoff:
        raise MethodError("series does not end at the cutoff session (stale)")
    if any(not b.close.is_finite() or b.close <= 0 for b in ordered):
        raise MethodError("invalid close")
    return [(b.day, b.close) for b in ordered]


def daily_setups(bars: Sequence[StrategyBar], cutoff: date) -> dict[str, str]:
    """Return ``{setup: invalidation}`` for every documented rule that matches."""
    series = _closes(bars, cutoff)
    closes = [c for _, c in series]
    hits: dict[str, str] = {}
    if len(closes) >= 21:
        prior_high = max(closes[-21:-1])
        if closes[-1] > prior_high:
            hits["breakout_20d"] = f"close back at or below prior 20-day closing high {prior_high}"
        ma20_today = sum(closes[-20:], ZERO) / 20
        ma20_prev = sum(closes[-21:-1], ZERO) / 20
        if closes[-2] < ma20_prev and closes[-1] > ma20_today:
            hits["reclaim_ma20"] = f"close back below the 20-day average {ma20_today:.4f}"
    if len(closes) >= 16:
        base, pole_top = closes[-16], closes[-6]
        last5 = closes[-5:]
        if pole_top / base - 1 > Decimal("0.10") and max(last5) / min(last5) - 1 <= Decimal("0.05"):
            hits["bull_flag"] = f"close below the flag low {min(last5)}"
    rsi_now = wilder_rsi(closes)
    rsi_prev = wilder_rsi(closes[:-1])
    if rsi_now is not None and rsi_now < 30:
        hits["oversold"] = "further decline without a reversal close (research only)"
    if rsi_prev is not None and rsi_prev < 30 and closes[-1] > closes[-2]:
        hits["oversold_bounce"] = f"close below the prior close {closes[-2]}"
    return hits


@dataclass(frozen=True)
class IntradayBar:
    start: datetime  # UTC, aligned to the 5-minute grid
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class OrbHit:
    range_high: Decimal
    range_low: Decimal
    hit_close: Decimal
    hit_at: datetime  # bar close time


def opening_range_breakout(
    bars: Sequence[IntradayBar], now: datetime, *, or_minutes: int = 15
) -> OrbHit | None:
    """First completed 5-minute bar after the range to close above the range high.

    The chart is usable only when every 5-minute bar from the open to the last
    completed bar is present (a gap means a halt or thin trading: refuse).
    """
    if now.tzinfo is None:
        raise MethodError("timezone-aware time required")
    if or_minutes % 5 or not 5 <= or_minutes <= 60:
        raise MethodError("opening range must be 5-60 minutes on the 5-minute grid")
    session = session_for(now.astimezone(NEW_YORK).date())
    if session is None:
        raise MethodError("no regular session on this date")
    step = timedelta(minutes=5)
    if any(b.start.tzinfo is None or b.start.utcoffset() is None for b in bars):
        raise MethodError("bar timestamps must be timezone-aware")
    complete = [b for b in bars if b.start + step <= now and b.start >= session.open_utc]
    complete.sort(key=lambda b: b.start)
    expected = session.open_utc
    for bar in complete:
        if bar.start != expected:
            raise MethodError("missing or off-grid 5-minute bar (halt or thin chart)")
        expected += step
    range_end = session.open_utc + timedelta(minutes=or_minutes)
    in_range = [b for b in complete if b.start < range_end]
    if len(in_range) != or_minutes // 5:
        return None  # range not complete yet
    high = max(b.high for b in in_range)
    low = min(b.low for b in in_range)
    for bar in complete:
        if bar.start >= range_end and bar.start + step <= session.close_utc and bar.close > high:
            return OrbHit(high, low, bar.close, bar.start + step)
    return None


def _evidence(cid: str, payload: str) -> tuple[EvidenceRef, ...]:
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return (EvidenceRef("bars", f"{cid}:{METHOD_VERSION}", digest),)


def daily_signals(
    cid: str, bars: Sequence[StrategyBar], cutoff: date, *, cutoff_time: datetime,
    generated_at: datetime,
) -> tuple[ResearchSignal, ...]:
    """SWING-track research signals for each matched daily setup (horizon 2-10 sessions)."""
    hits = daily_setups(bars, cutoff)
    payload = "|".join(f"{b.day}:{b.close}" for b in sorted(bars, key=lambda b: b.day))
    evidence = _evidence(cid, payload)
    return tuple(
        ResearchSignal(
            canonical_id=cid, track="SWING", source_kind="DAY_TRADER_METHOD",
            source_id=f"day_trader_skill.{setup}", source_version=METHOD_VERSION,
            horizon_min_days=2, horizon_max_days=10,
            direction="NEUTRAL" if setup == "oversold" else "LONG",
            evidence=evidence, generated_at=generated_at, data_cutoff=cutoff_time,
            invalidation=(invalidation,),
            rationale=f"chart matched rule {setup}; not a recommendation",
        )
        for setup, invalidation in sorted(hits.items())
    )


def orb_signal(
    cid: str, bars: Sequence[IntradayBar], now: datetime, *, or_minutes: int = 15,
) -> ResearchSignal | None:
    hit = opening_range_breakout(bars, now, or_minutes=or_minutes)
    if hit is None:
        return None
    payload = "|".join(f"{b.start.isoformat()}:{b.high}:{b.low}:{b.close}"
                       for b in sorted(bars, key=lambda b: b.start) if b.start < hit.hit_at)
    return ResearchSignal(
        canonical_id=cid, track="DAY", source_kind="DAY_TRADER_METHOD",
        source_id="day_trader_skill.orb", source_version=METHOD_VERSION,
        horizon_min_days=0, horizon_max_days=0, direction="LONG",
        evidence=_evidence(cid, payload), generated_at=now, data_cutoff=hit.hit_at,
        invalidation=(f"close back below the opening-range high {hit.range_high}",
                      f"price below the opening-range low {hit.range_low}"),
        rationale="5-minute close above the opening range; not a recommendation",
    )
