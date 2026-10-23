"""SD-069 native entry timer and exit planner (offline, deterministic, long side only).

Methodology attribution: rules follow the MIT-licensed ``day-trader-skill`` 2.0.0
``trader-entry`` and ``trader-exit`` documentation (Copyright (c) 2026 Jake Schincariol). No code
from that package runs here and no LLM is involved: SideDeck evaluates the rules on bars the
caller supplies. A trigger is "a bar closed above a level", never an order or a recommendation;
an exit plan is a plan, not a guarantee (gaps and fast markets fill past stops).

Entry: the opening range is the first ``or_minutes`` (15) of 5-minute bars. The trigger is the
first *completed* bar after the range that closes strictly above the level (the range high, or a
level you give). Its time is the bar's close time and its price the close. No entries before
09:45 or after 15:30 New York time (on an early close the cutoff is 30 minutes before the close).
Optional volume check: trigger-bar volume >= ``min_volume_x`` x the range bars' mean volume.
One trigger per setup per day.

Exit: stop ``or-mid`` (default), ``or-low``, ``price:X``, ``pct:X`` or ``atr:K`` (K x the mean true
range of the last 14 session bars up to the entry bar, or of all of them if fewer, which is
reported). The stop rounds down to the cent; risk = entry - stop; target = entry + R x risk,
rounded half up (``2R`` default, ``1R``, ``1.5R`` or ``price:X``). Refused: stop at or above the
entry, target at or below it, risk under 0.05 % of the entry, an entry at or after the flat-by time
(15:55, or 5 minutes before an early close), and a level setup without a named stop.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Sequence

from sidedeck.application.sd068_track_scheduler import NEW_YORK, session_for
from sidedeck.application.sd069_day_trader_methods import IntradayBar, MethodError

STEP = timedelta(minutes=5)
CENT = Decimal("0.01")
NO_ENTRIES_BEFORE = time(9, 45)
NO_ENTRIES_AFTER = time(15, 30)
FLAT_BY = time(15, 55)
MIN_RISK_FRACTION = Decimal("0.0005")
ATR_BARS = 14


@dataclass(frozen=True)
class EntryStatus:
    status: str                  # NOT_OPEN | RANGE_FORMING | WAITING | TRIGGERED | EXPIRED
    setup: str
    level: Decimal | None
    range_high: Decimal | None
    range_low: Decimal | None
    price: Decimal | None = None
    at: datetime | None = None   # trigger bar close time (UTC)
    bar_index: int | None = None  # 0 = the 09:30 bar
    note: str = ""


def _ny_time(dt: datetime, hour_minute: time) -> datetime:
    local = dt.astimezone(NEW_YORK)
    return local.replace(hour=hour_minute.hour, minute=hour_minute.minute, second=0,
                         microsecond=0).astimezone(dt.tzinfo)


def entry_trigger(
    bars: Sequence[IntradayBar], now: datetime, *, setup: str = "orb",
    level: Decimal | None = None, or_minutes: int = 15, min_volume_x: Decimal | None = None,
) -> EntryStatus:
    """Evaluate the entry rule on completed 5-minute bars as of ``now``."""
    if now.tzinfo is None:
        raise MethodError("timezone-aware time required")
    if setup not in ("orb", "level"):
        raise MethodError("setup must be orb or level")
    if setup == "level" and (level is None or not level.is_finite() or level <= 0):
        raise MethodError("a level setup needs a positive level")
    if or_minutes % 5 or not 5 <= or_minutes <= 60:
        raise MethodError("opening range must be 5-60 minutes on the 5-minute grid")
    if min_volume_x is not None and (not min_volume_x.is_finite() or min_volume_x <= 0):
        raise MethodError("min_volume_x must be positive")
    session = session_for(now.astimezone(NEW_YORK).date())
    if session is None:
        raise MethodError("market closed (weekend or NYSE holiday)")
    if now < session.open_utc:
        return EntryStatus("NOT_OPEN", setup, level, None, None)
    complete = sorted((b for b in bars if b.start >= session.open_utc
                       and b.start + STEP <= min(now, session.close_utc)),
                      key=lambda b: b.start)
    expected = session.open_utc
    for bar in complete:
        if bar.start.tzinfo is None or bar.start != expected:
            raise MethodError("missing or off-grid 5-minute bar (halt or thin chart)")
        expected += STEP
    range_end = session.open_utc + timedelta(minutes=or_minutes)
    in_range = [b for b in complete if b.start < range_end]
    if len(in_range) < or_minutes // 5:
        return EntryStatus("RANGE_FORMING", setup, level, None, None)
    high, low = max(b.high for b in in_range), min(b.low for b in in_range)
    target_level = high if setup == "orb" else level
    assert target_level is not None
    earliest = _ny_time(now, NO_ENTRIES_BEFORE)
    latest = min(_ny_time(now, NO_ENTRIES_AFTER), session.close_utc - timedelta(minutes=30))
    mean_volume = sum((b.volume for b in in_range), Decimal(0)) / len(in_range)
    thin = False
    for index, bar in enumerate(complete):
        closes_at = bar.start + STEP
        if bar.start < range_end or closes_at < earliest:
            continue
        if closes_at > latest:
            break
        if bar.close > target_level:
            if min_volume_x is not None and bar.volume < min_volume_x * mean_volume:
                thin = True
                continue                         # too thin: the trigger moves to a later bar
            return EntryStatus("TRIGGERED", setup, target_level, high, low,
                               bar.close.quantize(CENT), closes_at, index)
    note = "volume check rejected a close above" if thin else ""
    if now >= latest:
        return EntryStatus("EXPIRED", setup, target_level, high, low, note=note)
    return EntryStatus("WAITING", setup, target_level, high, low, note=note)


@dataclass(frozen=True)
class ExitPlan:
    entry: Decimal
    stop: Decimal
    stop_rule: str
    target: Decimal
    target_rule: str
    risk_per_share: Decimal
    risk_pct: Decimal
    reward_risk: Decimal
    flat_by: datetime            # UTC
    note: str = ""


def _true_ranges(bars: Sequence[IntradayBar]) -> list[Decimal]:
    out: list[Decimal] = []
    prev_close: Decimal | None = None
    for b in bars:
        tr = b.high - b.low
        if prev_close is not None:
            tr = max(tr, abs(b.high - prev_close), abs(b.low - prev_close))
        out.append(tr)
        prev_close = b.close
    return out


def exit_plan(
    *, entry: Decimal, entry_at: datetime, stop_rule: str = "or-mid", target_rule: str = "2R",
    range_high: Decimal | None = None, range_low: Decimal | None = None,
    session_bars: Sequence[IntradayBar] = (), setup: str = "orb",
) -> ExitPlan:
    """Stop and target for a long entry, set before the entry. Raises with the reason."""
    if entry_at.tzinfo is None:
        raise MethodError("timezone-aware time required")
    if not entry.is_finite() or entry <= 0:
        raise MethodError("entry must be a positive price")
    session = session_for(entry_at.astimezone(NEW_YORK).date())
    if session is None:
        raise MethodError("market closed (weekend or NYSE holiday)")
    flat_by = min(_ny_time(entry_at, FLAT_BY), session.close_utc - timedelta(minutes=5))
    if entry_at >= flat_by:
        raise MethodError("entry at or after the flat-by time is refused")
    note = ""
    kind, _, arg = stop_rule.partition(":")
    try:
        if kind in ("or-mid", "or-low"):
            if setup == "level":
                raise MethodError("a level setup has no opening range: name a stop")
            if range_high is None or range_low is None:
                raise MethodError("the opening range is required for this stop")
            raw = (range_high + range_low) / 2 if kind == "or-mid" else range_low
        elif kind == "price":
            raw = Decimal(arg)
        elif kind == "pct":
            raw = entry * (1 - Decimal(arg) / 100)
        elif kind == "atr":
            k = Decimal(arg)
            upto = [b for b in session_bars if b.start + STEP <= entry_at]
            if not upto or k <= 0:
                raise MethodError("an ATR stop needs session bars up to the entry and K > 0")
            trs = _true_ranges(sorted(upto, key=lambda b: b.start))
            window = trs[-ATR_BARS:]
            if len(window) < ATR_BARS:
                note = f"ATR averaged over {len(window)} bars (fewer than {ATR_BARS})"
            raw = entry - k * (sum(window, Decimal(0)) / len(window))
        else:
            raise MethodError("unknown stop rule")
        if not raw.is_finite():
            raise MethodError("malformed stop rule")
    except (InvalidOperation, ValueError) as exc:
        if isinstance(exc, MethodError):
            raise
        raise MethodError("malformed stop rule") from None
    stop = raw.quantize(CENT, rounding=ROUND_FLOOR)      # away from the entry, for a long
    if stop >= entry:
        raise MethodError("stop at or above the entry is refused")
    risk = entry - stop
    if risk < entry * MIN_RISK_FRACTION:
        raise MethodError("risk under 0.05% of the price: too tight to survive the spread")
    try:
        if target_rule.endswith("R"):
            multiple = Decimal(target_rule[:-1])
            if not multiple.is_finite() or multiple <= 0:
                raise MethodError("R multiple must be positive")
            target = (entry + multiple * risk).quantize(CENT, rounding=ROUND_HALF_UP)
        elif target_rule.startswith("price:"):
            target = Decimal(target_rule[6:]).quantize(CENT, rounding=ROUND_HALF_UP)
        else:
            raise MethodError("unknown target rule")
    except InvalidOperation:
        raise MethodError("malformed target rule") from None
    if target <= entry:
        raise MethodError("target at or below the entry is refused")
    return ExitPlan(entry, stop, stop_rule, target, target_rule, risk,
                    (risk / entry * 100).quantize(CENT, rounding=ROUND_HALF_UP),
                    ((target - entry) / risk).quantize(CENT, rounding=ROUND_HALF_UP),
                    flat_by, note)
