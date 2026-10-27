"""Deterministic offline Day Trader lifecycle acceptance simulation.

This is an explicitly fixture-only test harness. Its synthetic admission and execution
eligibility can never be read from a production data bundle or passed to a broker route.
Ledger fills and accounting are delegated to SideDeck SD-079; decisions use SD-071 and risk
limits use SD-072.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sidedeck.application.sd071_decision_engine import (
    MarketContext, PortfolioState, StrategyAdmission, TrackPolicy, decide,
)
from sidedeck.application.sd072_track_risk_limits import TrackLimits
from sidedeck.application.sd070_research_signal import EvidenceRef, ResearchSignal
from sidedeck.application.sd079_track_ledgers import TrackLedger

_BASIS = "SYNTHETIC_FIXTURE_ACCEPTANCE_ONLY_NOT_MARKET_DATA"
_STRATEGY = ("day-trader-acceptance-orb", "fixture-v1")
_NOW = datetime(2026, 10, 27, 14, 0, tzinfo=UTC)


@dataclass(frozen=True)
class SyntheticBar:
    at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


def _policy() -> TrackPolicy:
    return TrackPolicy(
        policy_id="sd121-fixture-acceptance-only", track="DAY",
        virtual_capital=Decimal("1000"), max_position_pct=Decimal("0.05"),
        max_positions=1, max_gross_exposure_pct=Decimal("0.5"),
        max_instrument_total_pct=Decimal("0.05"), max_sector_pct=Decimal("0.5"),
        max_correlation=Decimal("0.85"), risk_per_trade_pct=Decimal("0.005"),
        stop_atr_multiple=Decimal("2"), min_notional=Decimal("10"),
        max_signal_age=timedelta(minutes=5), max_signal_data_age=timedelta(minutes=5),
        max_price_age=timedelta(minutes=5), expires_at=_NOW + timedelta(hours=1),
        allowed_strategies=frozenset({_STRATEGY}), allowed_instruments=frozenset({"US:SIM"}),
    )


def run_simulation(workdir: Path, *, fixture_acceptance: bool = False) -> dict[str, Any]:
    """Run synthetic scan→decision→simulated fill→protective exit→restart reconcile.

    The explicit fixture flag is required to create the temporary synthetic admission and
    instrument-eligibility assertions. No broker API is imported or reachable from this path.
    """
    if fixture_acceptance is not True:
        raise PermissionError("SD-121 simulation requires explicit fixture_acceptance=True")
    workdir.mkdir(parents=True, exist_ok=True)
    ledger_path = workdir / "day-trader-simulated-ledger.sqlite3"
    if ledger_path.exists():
        raise ValueError("simulation workdir is not empty; use a fresh directory")
    signal = ResearchSignal(
        canonical_id="US:SIM", track="DAY", source_kind="NATIVE_STRATEGY",
        source_id=_STRATEGY[0], source_version=_STRATEGY[1], horizon_min_days=0,
        horizon_max_days=0, direction="LONG",
        evidence=(EvidenceRef("SYNTHETIC_FIXTURE", "sd121://scan/US:SIM", "a" * 64),),
        generated_at=_NOW, data_cutoff=_NOW, invalidation=("synthetic stop touched",),
        rationale="Deterministic acceptance fixture only.",
    )
    admission = StrategyAdmission(_STRATEGY[0], _STRATEGY[1], "DAY", "ADMITTED",
                                  "FIXTURE_ONLY_OVERRIDE_NOT_EVIDENCE", 30, True)
    policy = _policy()
    market = MarketContext("US:SIM", Decimal("100"), _NOW, Decimal("1"),
                           "SYNTHETIC", True, True)
    decision = decide([signal], [admission], policy,
                      PortfolioState((), {"DAY": Decimal("1000")}), market, _NOW)
    if decision.status != "ELIGIBLE" or decision.sizing is None:
        raise RuntimeError(f"fixture decision failed: {decision.status} {decision.reasons}")

    ledger = TrackLedger.open(ledger_path, "DAY", Decimal("1000"))
    quantity = decision.sizing.quantity
    entry_price = Decimal("100")
    fee = Decimal("0.05")
    position = ledger.open_from_decision(
        "sd121-synthetic-order-1", decision, entry_price, fee, _NOW + timedelta(minutes=1),
        limits=TrackLimits("DAY", Decimal("0.10"), Decimal("0.03"), 1),
        prices={"US:SIM": entry_price}, session_start_equity=Decimal("1000"),
    )
    stop_bar = SyntheticBar(_NOW + timedelta(minutes=2), Decimal("97"), Decimal("101"),
                            Decimal("97"), Decimal("98"))
    exit_reason = "PROTECTIVE_STOP" if stop_bar.low <= position.stop_price else "SAME_SESSION_CLOSE"
    exit_price = min(stop_bar.open, position.stop_price) if exit_reason == "PROTECTIVE_STOP" else stop_bar.close
    exit_fee = Decimal("0.05")
    ledger.close(position.ref, exit_price, exit_fee, stop_bar.at, exit_reason)
    recovered = TrackLedger.open(ledger_path, "DAY", Decimal("1000"))
    recovered.refresh()
    reconciled_cash = Decimal("1000") + recovered.realized_pnl
    matched = (recovered.cash == reconciled_cash and not recovered.positions
               and bool(recovered.closed))
    if not matched:
        raise RuntimeError("restart reconciliation failed")
    events = [
        {"stage": "SCAN", "candidate": "US:SIM", "basis": _BASIS},
        {"stage": "SIGNAL", "signal_id": "sd121-synthetic-orb-1", "direction": "LONG"},
        {"stage": "DECISION", "status": decision.status, "reasons": list(decision.reasons)},
        {"stage": "SIMULATED_ORDER", "route": "SIMULATED_LOCAL", "permission": "FIXTURE_ONLY"},
        {"stage": "FILL", "quantity": str(quantity), "price": str(entry_price), "basis": "SIMULATED_LOCAL"},
        {"stage": "POSITION_MANAGEMENT", "stop": str(position.stop_price)},
        {"stage": "CLOSE", "reason": exit_reason, "price": str(exit_price)},
        {"stage": "RECONCILIATION", "status": "MATCHED"},
    ]
    digest = hashlib.sha256(json.dumps(events, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "schema": "sidedeck.sd121.day-trader-simulation/1", "basis": _BASIS,
        "mode": "FIXTURE_ACCEPTANCE_ONLY", "broker_execution": "DISABLED",
        "production_admission": "UNCHANGED", "decision": decision.status,
        "quantity": str(quantity), "entry_price": str(entry_price), "exit_price": str(exit_price),
        "realized_pnl": str(recovered.realized_pnl), "cash": str(recovered.cash),
        "open_positions_after_restart": len(recovered.positions), "reconciliation": "MATCHED",
        "event_count": len(events), "event_sha256": digest, "events": events,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the offline synthetic Day Trader acceptance lifecycle")
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--fixture-acceptance", action="store_true")
    args = parser.parse_args(argv)
    print(json.dumps(run_simulation(args.workdir, fixture_acceptance=args.fixture_acceptance),
                     sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
