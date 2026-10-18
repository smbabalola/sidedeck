from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sidedeck.demo import run_demo
from sidedeck.domain.accounting import Ledger, opening_event
from sidedeck.domain.contracts import MarketSnapshot, PriceType, Session, Side, TradeIntent
from sidedeck.domain.risk import RiskGate, RiskReason
from sidedeck.domain.simulator import SimulatedOrder


def test_risk_gate_enforces_cash_position_exposure_and_stop_budget() -> None:
    at = datetime(2026, 1, 2, 21, tzinfo=timezone.utc)
    snapshot = MarketSnapshot(
        instrument_id="US:AAPL", ticker="AAPL", provider="fixture", price_type=PriceType.EOD_CLOSE,
        price=Decimal("100"), market_timestamp=at, ingestion_timestamp=at,
        session=Session.CLOSED, quality="FIXTURE",
    )
    ledger = Ledger()
    ledger.append(opening_event("tradingagents", at))
    intent = TradeIntent(
        experiment_id="demo", portfolio_id="tradingagents", strategy_id="s", instrument_id="US:AAPL",
        side=Side.BUY, quantity=Decimal("3"), rationale="test", model_revision="fixture",
        decision_timestamp=at, data_as_of=at, stop_price=Decimal("90"), invalidation="test stop",
    )

    decision = RiskGate().evaluate(intent, ledger.replay("tradingagents"), snapshot, portfolio_value=Decimal("1000"))

    assert decision.accepted is False
    assert decision.reason is RiskReason.POSITION_CAP


def test_demo_has_two_independent_ledgers_and_restart_safe_report(tmp_path) -> None:
    first = run_demo(tmp_path / "results")
    second = run_demo(tmp_path / "results")

    assert set(first["summary"]) == {"tradingagents", "ai-trading"}
    assert first["summary"] == second["summary"]
    assert first["summary"]["tradingagents"]["fees"] != "0"
    assert (tmp_path / "results" / "dashboard.html").read_text(encoding="utf-8").find("NO ETORO") >= 0
    report = json.loads((tmp_path / "results" / "report.json").read_text(encoding="utf-8"))
    assert report["label"].startswith("FIXTURE")


def test_simulated_order_supports_partial_fill_and_cancel() -> None:
    order = SimulatedOrder(
        order_id=uuid4(),
        portfolio_id="tradingagents",
        instrument_id="US:AAPL",
        side=Side.BUY,
        requested_quantity=Decimal("2"),
    )
    order.apply_fill(Decimal("1"))
    assert order.status == "PARTIALLY_FILLED"
    order.cancel()
    assert order.status == "CANCELLED"
