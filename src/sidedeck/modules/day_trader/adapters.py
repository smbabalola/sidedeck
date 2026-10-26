"""Strict, versioned adapters from day-trader-skill 2.0.0 JSON outputs to SideDeck records.

Upstream output is *untrusted data*: shapes and types are checked, numbers parsed to Decimal,
free text truncated, and nothing in a field is ever executed or followed as an instruction.
Broker tickets keep only their plain description and risk figures; the ``tool_input`` meant
for an MCP broker connector is dropped and recorded as ``REFUSED_NOT_FORWARDED``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, cast

MAX_TEXT = 300
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.\-]{0,9}")


class AdapterError(ValueError):
    """An upstream output did not match the expected 2.0.0 contract."""


def text(value: Any) -> str:
    return "" if value is None else str(value)[:MAX_TEXT]


def dec(value: Any, what: str, *, positive: bool = True) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise AdapterError(f"{what} is not numeric")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise AdapterError(f"{what} is not numeric") from None
    if not result.is_finite() or (positive and result <= 0):
        raise AdapterError(f"{what} must be a positive finite number")
    return result


def symbol(value: Any) -> str:
    if not isinstance(value, str) or not _SYMBOL.fullmatch(value):
        raise AdapterError("symbol is not a plain ticker")
    return value


def _obj(value: Any, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AdapterError(f"{what} is not an object")
    return value


def _creator(doc: dict[str, Any], expected: str) -> None:
    if doc.get("created_by") not in (None, expected):
        raise AdapterError(f"output claims to come from {doc.get('created_by')!r}")


@dataclass(frozen=True)
class ScanHit:
    symbol: str
    setups: tuple[str, ...]
    price: Decimal
    at: str
    or_high: Decimal | None
    or_low: Decimal | None


def scan(doc: Any) -> dict[str, Any]:
    d = _obj(doc, "scan")
    _creator(d, "trader-scanner")
    hits = d.get("hits")
    if not isinstance(hits, list):
        raise AdapterError("scan lacks hits")
    out = []
    for h in hits:
        h = _obj(h, "hit")
        setups = h.get("setups")
        if not isinstance(setups, list) or not all(isinstance(s, str) for s in setups):
            raise AdapterError("hit setups malformed")
        out.append(ScanHit(symbol(h.get("symbol")), tuple(text(s) for s in setups),
                           dec(h.get("price"), "hit price"), text(h.get("at")),
                           None if h.get("or_high") is None else dec(h["or_high"], "or_high"),
                           None if h.get("or_low") is None else dec(h["or_low"], "or_low")))
    return {"mode": text(d.get("mode")), "as_of": text(d.get("as_of")),
            "universe": int(d.get("universe", 0)), "scanned": int(d.get("scanned", 0)),
            "source": text(d.get("source")), "note": text(d.get("note")), "hits": out}


def entry(doc: Any) -> dict[str, Any]:
    d = _obj(doc, "entry")
    status = d.get("status")
    if status not in ("triggered", "waiting", "expired", "no_trade", "invalid", "closed",
                      "not_yet", "pending", "no_setup"):
        if not isinstance(status, str):
            raise AdapterError("entry status missing")
    rng = _obj(d.get("opening_range"), "opening_range")
    trig = d.get("trigger")
    trigger = None
    if status == "triggered":
        t = _obj(trig, "trigger")
        trigger = {"price": dec(t.get("price"), "trigger price"), "time": text(t.get("time")),
                   "bar_index": int(t.get("bar_index", -1)),
                   "volume_x": None if t.get("volume_x") is None else
                   dec(t["volume_x"], "volume_x", positive=False)}
    return {"symbol": symbol(d.get("symbol")), "setup": text(d.get("setup")),
            "side": text(d.get("side")), "date": text(d.get("date")), "status": text(status),
            "reason": text(d.get("reason")), "level": None if d.get("level") is None
            else dec(d["level"], "level"),
            "range_high": dec(rng.get("high"), "range high"),
            "range_low": dec(rng.get("low"), "range low"),
            "range_complete": rng.get("complete") is True, "trigger": trigger}


def exit_plan(doc: Any) -> dict[str, Any]:
    d = _obj(doc, "exit plan")
    _creator(d, "trader-exit")
    if d.get("side") != "buy":
        raise AdapterError("only long plans are supported")
    e, s, t = dec(d.get("entry"), "entry"), dec(d.get("stop"), "stop"), dec(d.get("target"),
                                                                             "target")
    if not s < e < t:
        raise AdapterError("plan must have stop < entry < target")
    return {"symbol": symbol(d.get("symbol")), "date": text(d.get("date")),
            "setup": text(d.get("setup")), "entry": e, "stop": s, "target": t,
            "entry_time": text(d.get("entry_time")), "stop_rule": text(d.get("stop_rule")),
            "target_r": dec(d.get("target_r"), "target_r"),
            "risk_per_share": dec(d.get("risk_per_share"), "risk_per_share"),
            "flat_by": text(d.get("flat_by")), "note": text(d.get("note")),
            "warnings": [text(w) for w in d.get("warnings") or []][:10]}


def timemachine(doc: Any) -> dict[str, Any]:
    d = _obj(doc, "timemachine")
    _creator(d, "trader-timemachine")
    mc = _obj(d.get("mc"), "mc")
    probs = {}
    for key in ("p_target", "p_stop", "p_neither", "p_green"):
        value = dec(mc.get(key), key, positive=False)
        if not Decimal(0) <= value <= Decimal(1):
            raise AdapterError(f"{key} is not a probability")
        probs[key] = value
    history_value = d.get("history")
    history: dict[str, Any] = cast(dict[str, Any], history_value) if isinstance(history_value, dict) else {}
    return {"replays": int(mc.get("replays", 0)), "seed": mc.get("seed"),
            "bars_left": mc.get("bars_left"), **probs,
            "avg_R": dec(mc.get("avg_R"), "avg_R", positive=False),
            "median_close": dec(mc.get("median_close"), "median_close"),
            "history": {k: text(v) for k, v in list(history.items())[:20]},
            "label": "SCENARIO_ESTIMATE_NOT_A_FORECAST_NOT_OOS_EVIDENCE"}


def budget(doc: Any) -> dict[str, Any]:
    d = _obj(doc, "budget")
    sizing = _obj(d.get("sizing"), "sizing")
    orders = d.get("orders")
    if not isinstance(orders, list):
        raise AdapterError("budget lacks orders")
    return {"symbol": symbol(sizing.get("symbol")), "budget": dec(sizing.get("budget"), "budget"),
            "max_loss_per_trade_usd": dec(sizing.get("max_loss_per_trade_usd"), "max loss"),
            "orders": [{"symbol": symbol(o.get("symbol")), "side": text(o.get("side")),
                        "qty": dec(o.get("qty"), "qty")} for o in map(
                            lambda o: _obj(o, "order"), orders)]}


def risk(doc: Any) -> dict[str, Any]:
    d = _obj(doc, "risk")
    rows = d.get("results")
    if not isinstance(rows, list):
        raise AdapterError("risk lacks results")
    out = []
    for r in rows:
        r = _obj(r, "risk row")
        if r.get("verdict") not in ("PASS", "BLOCK"):
            raise AdapterError("risk verdict must be PASS or BLOCK")
        out.append({"symbol": symbol(r.get("symbol")), "verdict": r["verdict"],
                    "fingerprint": text(r.get("fingerprint")),
                    "max_loss": dec(r.get("max_loss"), "max_loss", positive=False),
                    "value_usd": dec(r.get("value_usd"), "value_usd", positive=False),
                    "reasons": [text(x) for x in r.get("reasons") or []][:10]})
    return {"paper": d.get("paper") is True, "results": out,
            "role": "ADVISORY_ONLY: SideDeck risk and admission gates decide"}


def tickets(doc: Any) -> list[dict[str, Any]]:
    if not isinstance(doc, list):
        raise AdapterError("tickets must be a list")
    out = []
    for t in doc:
        t = _obj(t, "ticket")
        out.append({"index": int(t.get("index", 0)), "ready": t.get("ready") is True,
                    "status": text(t.get("status")), "plain": text(t.get("plain")),
                    "fingerprint": text(t.get("fingerprint")),
                    "max_loss": None if t.get("max_loss") is None
                    else dec(t["max_loss"], "max_loss", positive=False),
                    "broker_connector_payload": "REFUSED_NOT_FORWARDED"})
    return out
