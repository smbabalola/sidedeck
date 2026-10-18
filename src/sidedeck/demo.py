from __future__ import annotations

import argparse
import csv
import html
import json
import shutil
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from sidedeck.agents import (
    AITradingFixtureWorker,
    AgentRunCoordinator,
    AgentRunRequest,
    MarketBundle,
    SqlAuditStore,
    TradingAgentsFixtureWorker,
)
from sidedeck.domain.accounting import Ledger, opening_event
from sidedeck.domain.contracts import MarketSnapshot, PriceType, Session
from sidedeck.domain.risk import RiskGate
from sidedeck.domain.simulator import LocalArtifactStore, LocalExecutionSimulator, SimulatedFill
from sidedeck.infrastructure.database import create_database, create_schema, load_events, save_events


PORTFOLIOS = ("tradingagents", "ai-trading")
BASE_TIME = datetime(2026, 1, 5, 21, tzinfo=timezone.utc)


def _bundle(session: int) -> MarketBundle:
    prices = ((Decimal("100"), Decimal("200")), (Decimal("110"), Decimal("210")), (Decimal("105"), Decimal("205")))[session]
    at = BASE_TIME + timedelta(days=session)
    snapshots = tuple(
        MarketSnapshot(
            instrument_id=instrument,
            ticker=instrument[3:],
            provider="fixture://sidedeck-demo",
            price_type=PriceType.EOD_CLOSE,
            price=price,
            market_timestamp=at,
            ingestion_timestamp=at,
            session=Session.CLOSED,
            quality="FIXTURE_SYNTHETIC_NOT_LIVE",
        )
        for instrument, price in zip(("US:AAPL", "US:MSFT"), prices, strict=True)
    )
    return MarketBundle(
        bundle_id=f"demo-bundle-v1-session-{session}",
        decision_cutoff_utc=at,
        snapshots=snapshots,
        allowed_instruments=("US:AAPL", "US:MSFT"),
        max_snapshot_age_seconds=3600,
        provenance="FIXTURE / NOT LIVE MARKET DATA",
    )


def _request(
    adapter_id: str,
    revision: str,
    portfolio_id: str,
    session: int,
    bundle: MarketBundle,
    *,
    cash_usd: Decimal,
    holdings: dict[str, Decimal],
) -> AgentRunRequest:
    return AgentRunRequest(
        experiment_id="sidedeck-local-demo-v1",
        portfolio_id=portfolio_id,
        strategy_id=f"{adapter_id}-fixture-strategy",
        adapter_id=adapter_id,
        adapter_revision=revision,
        decision_cutoff_utc=bundle.decision_cutoff_utc,
        market_bundle_id=bundle.bundle_id,
        allowed_instruments=bundle.allowed_instruments,
        configuration_ref="local-fixture-only",
        cash_usd=cash_usd,
        holdings=holdings,
        deterministic_fixture=True,
    )


def _portfolio_value(ledger: Ledger, portfolio_id: str, bundle: MarketBundle) -> Decimal:
    marks = {snapshot.instrument_id: snapshot for snapshot in bundle.snapshots}
    state = ledger.replay(portfolio_id)
    return state.nav(marks, bundle.decision_cutoff_utc, timedelta(seconds=bundle.max_snapshot_age_seconds))


def run_demo(results_dir: Path) -> dict[str, Any]:
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / ".sidedeck-fixture").write_text("SideDeck disposable fixture results\n", encoding="utf-8")
    db_path = results_dir / "demo.sqlite3"
    artifact_path = results_dir / "demo.json"
    if artifact_path.exists():
        return cast(dict[str, Any], json.loads(artifact_path.read_text(encoding="utf-8")))
    engine = create_database(f"sqlite:///{db_path}")
    create_schema(engine)
    stored_events = load_events(engine)
    ledger = Ledger()
    for event in stored_events:
        ledger.append(event)
    if not stored_events:
        opening_at = BASE_TIME - timedelta(minutes=1)
        openings = [opening_event(portfolio_id, opening_at) for portfolio_id in PORTFOLIOS]
        for event in openings:
            ledger.append(event)
        save_events(engine, openings)
    if stored_events and len(stored_events) > len(PORTFOLIOS) and not artifact_path.exists():
        recovered: dict[str, Any] = {
            "label": "FIXTURE / NOT LIVE MARKET DATA; SIMULATED ORDERS / NO ETORO",
            "experiment_id": "sidedeck-local-demo-v1",
            "agent_status": {
                "tradingagents": "FIXTURE / CODE-READY / EXTERNAL RUN NOT VERIFIED",
                "ai-trading": "INDEPENDENT PROTOCOL FIXTURE / LICENSING BLOCKED",
            },
            "sessions": [],
            "recovery": "Reconstructed from canonical SQLite journal after an incomplete artifact write; no economic event was reposted.",
        }
        recovered["summary"] = _summary(ledger, recovered, _bundle(2))
        _write_exports(results_dir, recovered)
        engine.dispose()
        return recovered
    artifact_store = LocalArtifactStore(artifact_path)
    artifact = artifact_store.load()
    artifact["label"] = "FIXTURE / NOT LIVE MARKET DATA; SIMULATED ORDERS / NO ETORO"
    artifact["experiment_id"] = "sidedeck-local-demo-v1"
    artifact["agent_status"] = {
        "tradingagents": "FIXTURE / CODE-READY / EXTERNAL RUN NOT VERIFIED",
        "ai-trading": "INDEPENDENT PROTOCOL FIXTURE / LICENSING BLOCKED",
    }
    artifact["sessions"] = []
    audit = SqlAuditStore(engine)
    coordinator = AgentRunCoordinator(audit)
    risk_gate = RiskGate()
    simulator = LocalExecutionSimulator()
    workers = (
        ("tradingagents", TradingAgentsFixtureWorker, "tradingagents.fixture", "fixture-1"),
        ("ai-trading", AITradingFixtureWorker, "ai-trading.protocol-fixture", "independent-protocol-1"),
    )
    for session in range(3):
        market_bundle = _bundle(session)
        session_record: dict[str, Any] = {"session": session, "cutoff": market_bundle.decision_cutoff_utc.isoformat(), "portfolios": {}}
        for portfolio_id, worker_type, adapter_id, revision in workers:
            worker = worker_type(session=session)
            state_before = ledger.replay(portfolio_id)
            request = _request(
                adapter_id,
                revision,
                portfolio_id,
                session,
                market_bundle,
                cash_usd=state_before.cash,
                holdings={key: value.quantity for key, value in state_before.positions.items()},
            )
            record, envelope = coordinator.run_validated(request, market_bundle, worker)
            snapshot_by_id = {snapshot.instrument_id: snapshot for snapshot in market_bundle.snapshots}
            decisions: list[dict[str, Any]] = []
            fills: list[dict[str, Any]] = []
            if record.validation.accepted and envelope.proposals:
                for intent in envelope.proposals:
                    snapshot = snapshot_by_id[intent.instrument_id]
                    state = ledger.replay(portfolio_id)
                    value = _portfolio_value(ledger, portfolio_id, market_bundle)
                    decision = risk_gate.evaluate(
                        intent,
                        state,
                        snapshot,
                        portfolio_value=value,
                        marks=snapshot_by_id,
                    )
                    decisions.append({"accepted": decision.accepted, "reason": decision.reason.value, "policy_version": decision.policy_version, "intent_id": str(decision.intent_id)})
                    fill: SimulatedFill | None
                    order_id, fill = simulator.execute(ledger, intent, decision, snapshot.price, market_bundle.decision_cutoff_utc)
                    if fill is not None:
                        save_events(engine, [ledger.events[-1]])
                        fills.append({"order_id": str(order_id), "fill_id": str(fill.fill_id), "quantity": str(fill.quantity), "price": str(fill.price), "fee": str(fill.fee), "status": fill.status})
            else:
                decisions.append({"accepted": False, "reason": "HOLD", "policy_version": risk_gate.policy.version})
            state_after = ledger.replay(portfolio_id)
            session_record["portfolios"][portfolio_id] = {
                "run_id": str(record.run_id),
                "accepted": record.validation.accepted,
                "decisions": decisions,
                "fills": fills,
                "cash": str(state_after.cash),
                "nav": str(_portfolio_value(ledger, portfolio_id, market_bundle)),
                "positions": {key: str(value.quantity) for key, value in state_after.positions.items()},
                "exposure": str(sum((value.quantity * snapshot_by_id[key].price for key, value in state_after.positions.items()), Decimal("0"))),
            }
        artifact["sessions"].append(session_record)
    summary = _summary(ledger, artifact, _bundle(2))
    artifact["summary"] = summary
    artifact_store.replace(artifact)
    _write_exports(results_dir, artifact)
    engine.dispose()
    return artifact


def reset_fixture(results_dir: Path) -> None:
    resolved = results_dir.resolve()
    marker = resolved / ".sidedeck-fixture"
    if resolved.exists() and resolved.name != "results" and not marker.exists():
        raise ValueError("refusing to reset an unmarked directory; use a scoped results directory")
    if resolved.exists():
        shutil.rmtree(resolved)


def _summary(ledger: Ledger, artifact: dict[str, Any], bundle: MarketBundle) -> dict[str, Any]:
    marks = {snapshot.instrument_id: snapshot for snapshot in bundle.snapshots}
    result: dict[str, Any] = {}
    for portfolio_id in PORTFOLIOS:
        state = ledger.replay(portfolio_id)
        result[portfolio_id] = {
            "cash": str(state.cash),
            "positions": {key: {"quantity": str(value.quantity), "cost_basis": str(value.cost_basis)} for key, value in state.positions.items()},
            "nav": str(state.nav(marks, bundle.decision_cutoff_utc, timedelta(seconds=bundle.max_snapshot_age_seconds))),
            "realized_net": str(state.realized_net),
            "fees": str(state.fees),
        }
    return result


def _write_exports(results_dir: Path, artifact: dict[str, Any]) -> None:
    (results_dir / "report.json").write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (results_dir / "trades.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("session", "portfolio", "accepted", "reason", "quantity", "price", "fee", "status"))
        for session in artifact["sessions"]:
            for portfolio, details in session["portfolios"].items():
                for decision in details["decisions"]:
                    for fill in cast(list[dict[str, Any]], details["fills"] or [{}]):
                        writer.writerow((session["session"], portfolio, decision.get("accepted"), decision.get("reason"), fill.get("quantity", ""), fill.get("price", ""), fill.get("fee", ""), fill.get("status", "")))
    rows = "".join(f"<tr><td>{html.escape(name)}</td><td>{values['cash']}</td><td>{values['nav']}</td><td>{values['realized_net']}</td><td>{values['fees']}</td></tr>" for name, values in artifact["summary"].items())
    curve_rows = "".join(
        f"<tr><td>{session['session']}</td><td>{portfolio}</td><td>{details['cash']}</td><td>{details['nav']}</td><td>{html.escape(json.dumps(details['positions'], sort_keys=True))}</td><td>{details['exposure']}</td><td>{html.escape(json.dumps(details['decisions'], sort_keys=True))}</td></tr>"
        for session in artifact["sessions"] for portfolio, details in session["portfolios"].items()
    )
    statuses = "".join(f"<li>{html.escape(name)}: {html.escape(status)}</li>" for name, status in artifact["agent_status"].items())
    html_text = f"""<!doctype html><meta charset='utf-8'><title>SideDeck local demo</title><h1>SideDeck local demo</h1><p><strong>FIXTURE / NOT LIVE MARKET DATA</strong></p><p><strong>SIMULATED ORDERS / NO ETORO</strong></p><p>Prices are synthetic. This is not upstream AI evidence or a profitability claim.</p><h2>Agent status</h2><ul>{statuses}</ul><h2>Final summary</h2><table border='1'><tr><th>Portfolio</th><th>Cash</th><th>NAV</th><th>Realized P&amp;L</th><th>Fees</th></tr>{rows}</table><h2>Equity, positions, exposure and decisions by session</h2><table border='1'><tr><th>Session</th><th>Portfolio</th><th>Cash</th><th>NAV</th><th>Positions</th><th>Exposure</th><th>Risk decisions</th></tr>{curve_rows}</table><p>Download <a href='report.json'>report.json</a> or <a href='trades.csv'>trades.csv</a>.</p>"""
    (results_dir / "dashboard.html").write_text(html_text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the credential-free SideDeck fixture demo")
    parser.add_argument("command", choices=("run", "status", "report", "reset-fixture"))
    parser.add_argument("--results-dir", type=Path, default=Path("results"))
    args = parser.parse_args()
    if args.command == "reset-fixture":
        reset_fixture(args.results_dir)
        print(f"reset disposable fixture directory: {args.results_dir}")
    elif args.command == "run":
        artifact = run_demo(args.results_dir)
        print(json.dumps(artifact["summary"], indent=2, sort_keys=True))
        print(f"dashboard: {args.results_dir / 'dashboard.html'}")
    else:
        path = args.results_dir / "report.json"
        if not path.exists():
            raise SystemExit("no demo report; run `python -m sidedeck.demo run` first")
        artifact = json.loads(path.read_text(encoding="utf-8"))
        if args.command == "status":
            print(json.dumps(artifact["summary"], indent=2, sort_keys=True))
        else:
            print(json.dumps(artifact, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
