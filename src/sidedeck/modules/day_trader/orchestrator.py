"""Day Trader module orchestrator: the 11 upstream skills in order, then SideDeck's own gates.

Stage order: scanner -> news -> entry -> exit -> timemachine -> budget -> risk -> broker
(tickets only) -> alerts (clock) -> analyst -> pelosi. Every stage records OK / FAILED /
MALFORMED / UNAVAILABLE / SKIPPED with a reason and the SHA-256 of its raw output; a failed
stage never stops the stages that do not depend on it.

Risk-PASS plans become SideDeck ``ResearchSignal``s (track ``DAY``, kind ``DAY_TRADER_METHOD``)
and proposals that keep the upstream skill, version, evidence digests, data cutoff, entry and
exit rules, size and reasons. SideDeck's SD-071 decision engine then decides on a separate
DAY policy: a method signal without an admitted native strategy can reach WATCHLIST at most,
so the skill's own PASS can never bypass SideDeck admission or risk. No proposal is ever
submitted; the only broker route is SideDeck's gateway after separate owner release.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, cast
from zoneinfo import ZoneInfo

from sidedeck.application.sd070_research_signal import EvidenceRef, ResearchSignal
from sidedeck.application.sd071_decision_engine import (
    MarketContext, PortfolioState, TrackPolicy, decide,
)
from sidedeck.modules.day_trader import adapters
from sidedeck.modules.day_trader.manifest import (
    MODULE_BOOK, SKILLS, SOURCE_VERSION, UPSTREAM, Verification, resolve,
)
from sidedeck.modules.day_trader.research import (
    chart_bars, orb_backtest, reconcile_sd069,
)
from sidedeck.modules.day_trader.sandbox import SandboxRefused, SkillRun, Workspace, run_skill

SCHEMA = "sidedeck-day-trader-run/1"
NY = ZoneInfo("America/New_York")
MODES = ("RESEARCH_ONLY", "SIMULATION_ONLY")
UPSTREAM_FIXTURE = "UPSTREAM_FIXTURE_UNAPPROVED_SOURCE"
EXECUTION = "NOT_RELEASED: Day Trader broker execution needs approved intraday data, a DAY " \
            "strategy admission, the SD-107 gateway and a separate owner release"


class ModuleRefused(PermissionError):
    pass


@dataclass(frozen=True)
class DayTraderConfig:
    """Module settings; execution modes cannot be configured here."""

    enabled: bool = True
    mode: str = "RESEARCH_ONLY"
    virtual_capital_usd: Decimal = Decimal("1000")      # dedicated DAY_TRADER_SKILL book
    max_loss_per_trade_usd: Decimal = Decimal("10")
    max_trades_per_day: int = 3
    replays: int = 2000
    max_entry_checks: int = 5

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ModuleRefused(f"mode {self.mode!r} is not allowed (only {MODES})")
        if self.virtual_capital_usd <= 0 or self.max_loss_per_trade_usd <= 0:
            raise ModuleRefused("capital and loss limits must be positive")

    @classmethod
    def load(cls, path: Path) -> "DayTraderConfig":
        if not path.is_file():
            return cls()
        doc = json.loads(path.read_text(encoding="utf-8"))
        if any(k in doc for k in ("broker", "execution", "orders_enabled", "live")):
            raise ModuleRefused("execution settings are not configurable in the module")
        return cls(enabled=bool(doc.get("enabled", True)), mode=str(doc.get("mode",
                                                                            "RESEARCH_ONLY")),
                   virtual_capital_usd=Decimal(str(doc.get("virtual_capital_usd", "1000"))),
                   max_loss_per_trade_usd=Decimal(str(doc.get("max_loss_per_trade_usd", "10"))),
                   max_trades_per_day=int(doc.get("max_trades_per_day", 3)),
                   replays=int(doc.get("replays", 2000)))


@dataclass(frozen=True)
class Inputs:
    """Files the skills read offline, with one declared basis for the whole run."""

    basis: str
    now_ny: str                                   # "YYYY-MM-DD HH:MM" New York
    scanner: Path | None = None                   # 5m wall file (.json.gz)
    entry_charts: dict[str, Path] = field(default_factory=dict)   # symbol -> 5m chart
    history_charts: dict[str, Path] = field(default_factory=dict)  # symbol -> 60d 5m chart
    news_dir: Path | None = None
    analyst_dir: Path | None = None
    pelosi_zip: Path | None = None


def upstream_fixture_inputs(root: Path) -> Inputs:
    f = root / "tests" / "fixtures"
    return Inputs(UPSTREAM_FIXTURE, "2026-10-19 10:15",
                  scanner=f / "trader-scanner" / "wall5m-2026-10-19.json.gz",
                  entry_charts={"TSLA": f / "trader-entry" / "TSLA-2026-10-19-5m.json"},
                  history_charts={"TSLA": f / "trader-timemachine" / "TSLA-60d5m.json.gz"},
                  news_dir=f / "trader-news", analyst_dir=f / "trader-analyst",
                  pelosi_zip=f / "trader-pelosi" / "2026FD.zip")


def _stage(name: str, skill: str, run: SkillRun | None, *, status: str | None = None,
           reason: str = "", summary: Any = None) -> dict[str, Any]:
    return {"stage": name, "skill": skill, "status": status or (run.status if run else
                                                                 "SKIPPED"),
            "reason": reason[:300], "output_sha256": run.stdout_sha256 if run else None,
            "seconds": round(run.seconds, 3) if run else 0.0, "summary": summary}


def _safe(name: str, skill: str, fn: Callable[[], tuple[SkillRun, Any]]) -> tuple[dict[str, Any],
                                                                                    Any]:
    try:
        run, parsed = fn()
    except SandboxRefused as exc:
        return _stage(name, skill, None, status="UNAVAILABLE", reason=str(exc)), None
    except adapters.AdapterError as exc:
        return _stage(name, skill, None, status="MALFORMED", reason=str(exc)), None
    if run.status != "OK":
        return _stage(name, skill, run, reason=run.stderr[-300:]), None
    return _stage(name, skill, run), parsed


def _now_utc(now_ny: str) -> datetime:
    return datetime.strptime(now_ny, "%Y-%m-%d %H:%M").replace(tzinfo=NY).astimezone(UTC)


def run_module(inputs: Inputs, config: DayTraderConfig = DayTraderConfig(), *,
               verification: Verification | None = None) -> dict[str, Any]:
    if not config.enabled:
        return {"schema": SCHEMA, "status": "DISABLED", "mode": config.mode}
    found = verification or resolve()
    ws = Workspace()
    now_utc = _now_utc(inputs.now_ny)
    stages: list[dict[str, Any]] = []
    out: dict[str, Any] = {}
    try:
        upstream_cfg = json.loads((found.root / "trader-budget" / "config.example.json")
                                  .read_text(encoding="utf-8")) if found.root else {}
        upstream_cfg.update({"budget": float(config.virtual_capital_usd),
                             "max_loss_per_trade_usd": float(config.max_loss_per_trade_usd),
                             "max_trades_per_day": config.max_trades_per_day, "paper": True})
        ws.write_json("trader/config.json", upstream_cfg)

        def call(skill: str, command: str | None, args: list[str],
                 parse: Callable[[Any], Any]) -> tuple[SkillRun, Any]:
            run = run_skill(skill, command, args, ws, verification=found)
            return run, (parse(run.output) if run.status == "OK" else None)

        # 1. scanner
        hits: list[adapters.ScanHit] = []
        if inputs.scanner is not None:
            wall = ws.add_input(inputs.scanner)
            st, parsed = _safe("scan", "trader-scanner", lambda: call(
                "trader-scanner", "orb", ["--offline", wall, "--now", inputs.now_ny,
                                          "--min-price", "0", "--no-write"], adapters.scan))
            if parsed:
                hits = parsed["hits"]
                st["summary"] = {"universe": parsed["universe"], "scanned": parsed["scanned"],
                                 "hits": len(hits), "note": parsed["note"]}
                out["scan"] = {**parsed, "hits": [_hit(h) for h in hits[:50]]}
            stages.append(st)
        else:
            stages.append(_stage("scan", "trader-scanner", None, status="UNAVAILABLE",
                                 reason="no approved intraday scan data"))
        candidates = [s for s in inputs.entry_charts if not hits or s in {h.symbol for h in
                                                                       hits}]
        candidates = (candidates or list(inputs.entry_charts))[:config.max_entry_checks]
        # 2. news
        if inputs.news_dir is not None and candidates:
            nd = ws.add_input(inputs.news_dir, "news")
            st, parsed = _safe("news", "trader-news", lambda: call(
                "trader-news", None, ["--tickers", *candidates, "--offline", nd, "--now",
                                      now_utc.isoformat(), "--dry-run"], _news))
            st["summary"] = parsed and {"items": len(parsed["items"]),
                                        "moving": parsed["moving"]}
            out["news"] = parsed
            stages.append(st)
        else:
            stages.append(_stage("news", "trader-news", None, status="UNAVAILABLE",
                                 reason="no approved news data"))
        # 3-8. per candidate: entry -> exit -> timemachine -> budget -> risk -> tickets
        out["plans"] = []
        for sym in candidates:
            out["plans"].append(_plan_chain(sym, inputs, config, ws, call, stages, now_utc))
        # 9. alerts: market clock (no data needed)
        st, parsed = _safe("alerts_clock", "trader-alerts", lambda: call(
            "trader-alerts", "clock", ["--offline", ".", "--now", inputs.now_ny], _clock))
        out["clock"] = parsed
        stages.append(st)
        # 10. analyst
        if inputs.analyst_dir is not None:
            ad = ws.add_input(inputs.analyst_dir, "analyst")
            tickers = [t for t in ("AAPL", "KO") if t]          # upstream fixture coverage
            st, parsed = _safe("analyst", "trader-analyst", lambda: call(
                "trader-analyst", None, [*tickers, "--offline", ad, "--no-filings"], _analyst))
            st["summary"] = parsed and {"companies": len(parsed)}
            out["analyst"] = parsed
            stages.append(st)
        # 11. pelosi
        if inputs.pelosi_zip is not None:
            pz = ws.add_input(inputs.pelosi_zip)
            st, parsed = _safe("pelosi", "trader-pelosi", lambda: call(
                "trader-pelosi", "index", ["--offline", pz, "--limit", "10"], _pelosi))
            st["summary"] = parsed and {"filings": len(parsed)}
            out["pelosi"] = parsed
            stages.append(st)
        if config.mode == "SIMULATION_ONLY":
            out["simulation"] = _simulation(inputs, out["plans"])
    finally:
        ws.close()
    return _report(inputs, config, found, stages, out, now_utc)


def _hit(h: adapters.ScanHit) -> dict[str, Any]:
    return {"symbol": h.symbol, "setups": list(h.setups), "price": str(h.price), "at": h.at}


def _news(doc: Any) -> dict[str, Any]:
    d = doc if isinstance(doc, dict) else {}
    items = [{"ticker": adapters.text(i.get("ticker")), "kind": adapters.text(i.get("kind")),
              "source": adapters.text(i.get("source")), "title": adapters.text(i.get("title")),
              "published": adapters.text(i.get("published") or i.get("time"))}
             for i in d.get("items", []) if isinstance(i, dict)][:40]
    moving = [adapters.text(m.get("ticker")) for m in d.get("moves", [])
              if isinstance(m, dict) and m.get("moving")]
    return {"items": items, "moving": moving, "label": "UNTRUSTED_TEXT_DISPLAY_ONLY"}


def _clock(doc: Any) -> dict[str, Any]:
    d = doc if isinstance(doc, dict) else {}
    return {k: adapters.text(d.get(k)) for k in ("now_new_york", "open", "reason", "closes")}


def _analyst(doc: Any) -> list[dict[str, Any]]:
    rows = []
    for item in doc if isinstance(doc, list) else []:
        result = item.get("result") if isinstance(item, dict) else None
        if isinstance(result, dict):
            latest = (result.get("rows") or [{}])[0]
            rows.append({"ticker": adapters.text(item.get("ticker")),
                         "entity": adapters.text(result.get("entity")),
                         "latest_period": adapters.text(latest.get("fiscal")),
                         "revenue": latest.get("revenue"), "eps_diluted": latest.get("eps_diluted")})
    return rows


def _pelosi(doc: Any) -> list[dict[str, Any]]:
    return [{"name": adapters.text(r.get("name")), "filed": adapters.text(r.get("filed")),
             "type": adapters.text(r.get("type_name"))}
            for r in (doc if isinstance(doc, list) else []) if isinstance(r, dict)][:10]


def _plan_chain(sym: str, inputs: Inputs, config: DayTraderConfig, ws: Workspace,
                call: Callable[..., tuple[SkillRun, Any]], stages: list[dict[str, Any]],
                now_utc: datetime) -> dict[str, Any]:
    plan: dict[str, Any] = {"symbol": sym}
    chart = ws.add_input(inputs.entry_charts[sym], f"{sym}-entry.json")
    st, entry = _safe(f"entry:{sym}", "trader-entry", lambda: call(
        "trader-entry", "check", [sym, "--offline", chart, "--now", inputs.now_ny,
                                  "--write", "trader/entry.json"], adapters.entry))
    stages.append(st)
    plan["entry"] = _jsonable(entry)
    if not entry or entry["status"] != "triggered":
        plan["result"] = "NO_ENTRY" if entry else "ENTRY_UNAVAILABLE"
        return plan
    st, exit_doc = _safe(f"exit:{sym}", "trader-exit", lambda: call(
        "trader-exit", "plan", ["--from", "trader/entry.json", "--now", inputs.now_ny,
                                "--write", "trader/plan.json"], adapters.exit_plan))
    stages.append(st)
    plan["exit"] = _jsonable(exit_doc)
    if not exit_doc:
        plan["result"] = "NO_EXIT_PLAN"
        return plan
    if sym in inputs.history_charts:
        hist = ws.add_input(inputs.history_charts[sym], f"{sym}-60d5m.json.gz")
        st, tm = _safe(f"timemachine:{sym}", "trader-timemachine", lambda: call(
            "trader-timemachine", "run", ["--plan", "trader/plan.json", "--offline", hist,
                                          "--now", inputs.now_ny, "--replays",
                                          str(config.replays)], adapters.timemachine))
        stages.append(st)
        plan["timemachine"] = _jsonable(tm)
    st, budget = _safe(f"budget:{sym}", "trader-budget", lambda: call(
        "trader-budget", None, ["--plan", "trader/plan.json", "--config", "trader/config.json",
                                "--now", inputs.now_ny, "--write", "trader/orders.json"],
        adapters.budget))
    stages.append(st)
    plan["budget"] = _jsonable(budget)
    if not budget:
        plan["result"] = "NOT_SIZED"
        return plan
    today = inputs.now_ny[:10]
    st, risk = _safe(f"risk:{sym}", "trader-risk", lambda: call(
        "trader-risk", None, ["--orders", "trader/orders.json", "--config", "trader/config.json",
                              "--now", inputs.now_ny, "--today", today], adapters.risk))
    stages.append(st)
    plan["risk"] = _jsonable(risk)
    st, tickets = _safe(f"broker_tickets:{sym}", "trader-broker", lambda: call(
        "trader-broker", "show", ["--now", inputs.now_ny, "--today", today], adapters.tickets))
    stages.append(st)
    plan["tickets"] = _jsonable(tickets)
    passed = bool(risk) and all(r["verdict"] == "PASS" for r in risk["results"])
    plan["result"] = "SKILL_RISK_PASS" if passed else "SKILL_RISK_BLOCK"
    plan["proposal"] = _proposal(sym, inputs, entry, exit_doc, budget, risk, stages, now_utc,
                                 config) if passed else None
    return plan


def _proposal(sym: str, inputs: Inputs, entry: dict[str, Any], plan: dict[str, Any],
              budget: dict[str, Any], risk: dict[str, Any], stages: list[dict[str, Any]],
              now_utc: datetime, config: DayTraderConfig) -> dict[str, Any]:
    digests = {s["stage"]: s["output_sha256"] for s in stages
               if s["stage"].endswith(f":{sym}") and s["output_sha256"]}
    trigger_close = _now_utc(f"{plan['date']} {_hhmm(plan['entry_time'])}")
    signal = ResearchSignal(
        canonical_id=f"US:{sym}", track="DAY", source_kind="DAY_TRADER_METHOD",
        source_id=f"day_trader_skill.{plan['setup']}", source_version=SOURCE_VERSION,
        horizon_min_days=0, horizon_max_days=0, direction="LONG",
        evidence=tuple(EvidenceRef("day_trader_skill_output", stage, sha)
                       for stage, sha in sorted(digests.items())),
        generated_at=now_utc, data_cutoff=min(trigger_close, now_utc),
        invalidation=(f"trades at or below the stop {plan['stop']}",
                      f"flat by {plan['flat_by']} New York"),
        rationale=adapters.text(entry["reason"]))
    qty = budget["orders"][0]["qty"] if budget["orders"] else Decimal(0)
    policy = TrackPolicy(
        policy_id="day-trader-skill-research", track="DAY",
        virtual_capital=config.virtual_capital_usd, max_position_pct=Decimal("0.5"),
        max_positions=config.max_trades_per_day, max_gross_exposure_pct=Decimal("1"),
        max_instrument_total_pct=Decimal("0.5"), max_sector_pct=Decimal("1"),
        max_correlation=Decimal("0.9"),
        risk_per_trade_pct=config.max_loss_per_trade_usd / config.virtual_capital_usd,
        stop_atr_multiple=Decimal("1"), min_notional=Decimal("10"),
        max_signal_age=timedelta(minutes=30), max_signal_data_age=timedelta(minutes=30),
        max_price_age=timedelta(minutes=10), expires_at=now_utc + timedelta(hours=8),
        allowed_strategies=frozenset())
    market = MarketContext(f"US:{sym}", plan["entry"], min(trigger_close, now_utc),
                           plan["risk_per_share"], "UNKNOWN", session_open=True,
                           execution_eligible=False)
    decision = decide([signal], [], policy, PortfolioState((), {"DAY": config.virtual_capital_usd}),
                      market, now_utc)
    return {
        "proposal_id": hashlib.sha256(f"{SOURCE_VERSION}|{sym}|{plan['date']}|"
                                      f"{plan['entry_time']}".encode()).hexdigest()[:16],
        "book": MODULE_BOOK, "symbol": sym, "data_basis": inputs.basis,
        "skill": "trader-entry -> trader-exit -> trader-budget -> trader-risk",
        "upstream": {"version": UPSTREAM["version"], "commit": UPSTREAM["commit"]},
        "evidence_sha256": digests, "data_cutoff": signal.data_cutoff.isoformat(),
        "entry_rule": {"setup": plan["setup"], "level": str(entry["level"]),
                       "trigger": _jsonable(entry["trigger"])},
        "exit_rule": {"stop": str(plan["stop"]), "stop_rule": plan["stop_rule"],
                      "target": str(plan["target"]), "target_r": str(plan["target_r"]),
                      "flat_by": plan["flat_by"]},
        "size": {"qty": str(qty), "max_loss_usd": str(risk["results"][0]["max_loss"])},
        "skill_risk": "PASS (advisory)", "signal_id": signal.signal_id,
        "sidedeck_decision": {"status": decision.status, "reasons": list(decision.reasons),
                              "execution_permission": decision.execution_permission},
        "execution": EXECUTION}


def _hhmm(label: str) -> str:
    return datetime.strptime(label.strip(), "%I:%M %p").strftime("%H:%M")


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    return value


def _simulation(inputs: Inputs, plans: list[dict[str, Any]]) -> dict[str, Any]:
    """SideDeck's independent checks (SIMULATION_ONLY): SD-069 parity and an ORB backtest."""
    sim: dict[str, Any] = {"label": "SIMULATION_ONLY_NOT_PERFORMANCE_EVIDENCE"}
    for plan in plans:
        sym = plan["symbol"]
        entry, exit_doc = plan.get("entry"), plan.get("exit")
        if entry and sym in inputs.entry_charts:
            try:
                bars = chart_bars(inputs.entry_charts[sym])
                sim.setdefault("sd069_reconciliation", {})[sym] = reconcile_sd069(
                    bars, _now_utc(inputs.now_ny), _decimals(entry), _decimals(exit_doc))
            except Exception as exc:  # noqa: BLE001 - recorded, never hidden
                sim.setdefault("sd069_reconciliation", {})[sym] = {"verdict": "NOT_RUN",
                                                                  "reason": str(exc)[:200]}
        if sym in inputs.history_charts:
            try:
                sim.setdefault("orb_backtest", {})[sym] = orb_backtest(
                    chart_bars(inputs.history_charts[sym]))
            except Exception as exc:  # noqa: BLE001
                sim.setdefault("orb_backtest", {})[sym] = {"status": "NOT_RUN",
                                                           "reason": str(exc)[:200]}
    return sim


def _decimals(doc: Any) -> Any:
    if doc is None:
        return None
    out = dict(doc)
    for key in ("range_high", "range_low", "stop", "target", "entry", "level"):
        if isinstance(out.get(key), str):
            out[key] = Decimal(out[key])
    if isinstance(out.get("trigger"), dict):
        out["trigger"] = {**out["trigger"], "price": Decimal(out["trigger"]["price"])}
    return out


def _report(inputs: Inputs, config: DayTraderConfig, found: Verification,
            stages: list[dict[str, Any]], out: dict[str, Any], now_utc: datetime
            ) -> dict[str, Any]:
    proposals = [p["proposal"] for p in out.get("plans", []) if p.get("proposal")]
    counts: dict[str, int] = {}
    for s in stages:
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    return cast(dict[str, Any], _jsonable({
        "schema": SCHEMA, "status": "COMPLETED", "module": "DAY_TRADER", "book": MODULE_BOOK,
        "mode": config.mode, "data_basis": inputs.basis, "as_of_new_york": inputs.now_ny,
        "as_of_utc": now_utc.isoformat(), "generated_at": datetime.now(UTC).isoformat(),
        "upstream": {**UPSTREAM, "source": found.source, "verification": found.status},
        "capabilities": {name: {"hosts_blocked": list(s.hosts), "role": s.role,
                                "claude_only_not_used": s.claude_only,
                                "allowed_commands": sorted(s.allowed) if s.allowed else []}
                         for name, s in SKILLS.items()},
        "stages": stages, "stage_counts": counts, **out, "proposals": proposals,
        "execution": EXECUTION,
        "gates": {"DATA": "BLOCKED: no approved intraday data; upstream fixtures only"
                  if inputs.basis == UPSTREAM_FIXTURE else "NOT_ASSESSED",
                  "STRATEGY_ADMISSION": "BLOCKED: no admitted DAY strategy (skill signals are "
                                        "WATCHLIST at most)",
                  "BROKER": "BLOCKED: module has no broker path; SD-107 gateway not released",
                   "PAPER_EXECUTION": "BLOCKED: separate owner release required"}}))
