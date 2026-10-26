"""Independent checks of the Day Trader skill: SD-069 parity and a SideDeck ORB backtest.

* ``reconcile_sd069`` runs SideDeck's earlier native re-implementation (SD-069 entry trigger
  and exit plan) on the same bars the upstream skill saw and reports agreement field by field.
  SD-069 stays in place (SD-076/SD-092 use it); duplication is only removed after parity.
* ``orb_backtest`` evaluates the opening-range-breakout setup across every session in an
  intraday file with SideDeck's own rules and realistic frictions: entry at the *next* bar's
  open after the trigger bar closes (latency), slippage and spread per side, gap-through stops
  filled at the open, stop wins when stop and target touch in one bar, flat by 15:55 ET.
  It is independent of the skill's Time Machine, whose replays are scenario estimates.
"""
from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sidedeck.application.sd069_day_trader_methods import IntradayBar, opening_range_breakout
from sidedeck.application.sd069_entry_exit import entry_trigger, exit_plan

NY = ZoneInfo("America/New_York")
STEP = timedelta(minutes=5)


def chart_bars(path: Path) -> list[IntradayBar]:
    """Bars from a saved Yahoo chart JSON (5-minute). Null rows are dropped, never filled."""
    raw = path.read_bytes()
    doc = json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)
    result = doc["chart"]["result"][0]
    if result.get("meta", {}).get("dataGranularity") not in (None, "5m"):
        raise ValueError("expected 5-minute bars")
    q = result["indicators"]["quote"][0]
    bars = []
    for i, ts in enumerate(result["timestamp"]):
        row = [q[k][i] for k in ("open", "high", "low", "close", "volume")]
        if any(v is None for v in row):
            continue
        o, h, lo, c, v = (Decimal(str(round(x, 4))) for x in row)
        start = datetime.fromtimestamp(ts, UTC)
        if start.minute % 5 or start.second:
            continue
        bars.append(IntradayBar(start, o, max(h, o, c), min(lo, o, c), c, v))
    return sorted(bars, key=lambda b: b.start)


def reconcile_sd069(bars: list[IntradayBar], now: datetime, upstream_entry: dict[str, Any],
                    upstream_plan: dict[str, Any] | None) -> dict[str, Any]:
    status = entry_trigger(bars, now)
    rows = {"status": (status.status, str(upstream_entry["status"]).upper()),
            "range_high": (status.range_high, upstream_entry["range_high"]),
            "range_low": (status.range_low, upstream_entry["range_low"])}
    trig = upstream_entry.get("trigger")
    if trig is not None:
        rows["trigger_price"] = (status.price, trig["price"])
    plan = None
    if status.price is not None and status.at is not None and upstream_plan is not None:
        try:
            plan = exit_plan(entry=status.price, entry_at=status.at,
                             range_high=status.range_high, range_low=status.range_low)
        except Exception as exc:  # noqa: BLE001 - parity report records the refusal
            plan = None
            rows["exit_plan"] = (f"REFUSED: {exc}", "PLANNED")
    if plan is not None and upstream_plan is not None:
        rows["stop"] = (plan.stop, upstream_plan["stop"])
        rows["target"] = (plan.target, upstream_plan["target"])
    report: dict[str, Any] = {}
    for key, (ours, theirs) in rows.items():
        if isinstance(ours, Decimal) and isinstance(theirs, Decimal):
            agree = abs(ours - theirs) <= Decimal("0.01")
        else:
            agree = str(ours) == str(theirs)
        report[key] = {"sd069": str(ours), "upstream": str(theirs), "agree": agree}
    report["verdict"] = ("EQUIVALENT_ON_THIS_INPUT" if all(v["agree"] for v in report.values()
                                                           if isinstance(v, dict))
                         else "DIFFERS_SD069_KEPT_UNCHANGED")
    return report


@dataclass(frozen=True)
class Frictions:
    slippage_bps: Decimal = Decimal("5")     # per side
    half_spread_bps: Decimal = Decimal("2")  # per side
    fee_per_share: Decimal = Decimal("0")

    def buy(self, price: Decimal) -> Decimal:
        return price * (1 + (self.slippage_bps + self.half_spread_bps) / Decimal(10000))

    def sell(self, price: Decimal) -> Decimal:
        return price * (1 - (self.slippage_bps + self.half_spread_bps) / Decimal(10000))


def orb_backtest(bars: list[IntradayBar], *, frictions: Frictions = Frictions(),
                 target_r: Decimal = Decimal(2)) -> dict[str, Any]:
    sessions: dict[Any, list[IntradayBar]] = {}
    for b in bars:
        sessions.setdefault(b.start.astimezone(NY).date(), []).append(b)
    trades, skipped = [], {"INCOMPLETE_OR_GAPPED": 0, "NO_TRIGGER": 0, "NO_NEXT_BAR": 0}
    for day, rows in sorted(sessions.items()):
        rows.sort(key=lambda b: b.start)
        close_at = datetime.combine(day, datetime.min.time(), NY).replace(hour=16)
        try:
            hit = opening_range_breakout(rows, close_at.astimezone(UTC))
        except Exception:  # noqa: BLE001 - halted/thin sessions are skipped, never repaired
            skipped["INCOMPLETE_OR_GAPPED"] += 1
            continue
        if hit is None:
            skipped["NO_TRIGGER"] += 1
            continue
        nxt = [b for b in rows if b.start >= hit.hit_at]
        if not nxt or hit.hit_at.astimezone(NY).time() > datetime.strptime("15:30",
                                                                            "%H:%M").time():
            skipped["NO_NEXT_BAR"] += 1
            continue
        entry = frictions.buy(nxt[0].open)            # latency: next bar's open
        stop = ((hit.range_high + hit.range_low) / 2).quantize(Decimal("0.01"), ROUND_DOWN)
        if stop >= entry:
            skipped["NO_TRIGGER"] += 1
            continue
        risk = entry - stop
        target = entry + target_r * risk
        flat_by = datetime.combine(day, datetime.min.time(), NY).replace(hour=15, minute=55)
        outcome, exit_price = "FLAT_BY", None
        for b in nxt:
            if b.start.astimezone(NY) >= flat_by:
                exit_price = b.open
                break
            if b.low <= stop:
                outcome, exit_price = "STOP", min(b.open, stop)
                break
            if b.high >= target:
                outcome, exit_price = "TARGET", max(b.open, target)
                break
            exit_price = b.close
        assert exit_price is not None
        realized = frictions.sell(exit_price) - frictions.fee_per_share * 2
        trades.append({"date": day.isoformat(), "outcome": outcome,
                       "R": float(((realized - entry) / risk).quantize(Decimal("0.001")))})
    rs = [t["R"] for t in trades]
    gains, losses = sum(r for r in rs if r > 0), -sum(r for r in rs if r < 0)
    return {"basis": "BACKTEST_ON_UPSTREAM_FIXTURE_UNAPPROVED_SOURCE_NOT_ADMISSION_EVIDENCE",
            "sessions": len(sessions), "trades": len(trades), "skipped": skipped,
            "win_rate": round(sum(1 for r in rs if r > 0) / len(rs), 3) if rs else None,
            "avg_R": round(sum(rs) / len(rs), 3) if rs else None,
            "profit_factor": (round(gains / losses, 3) if losses else None) if rs else None,
            "frictions": {"slippage_bps": str(frictions.slippage_bps),
                          "half_spread_bps": str(frictions.half_spread_bps),
                          "entry_latency": "next 5-minute bar open"},
            "trades_detail": trades[-60:]}
