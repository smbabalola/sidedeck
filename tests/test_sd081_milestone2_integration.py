"""Milestone 2 integration on FIXTURES (mock SIP transport, synthetic bars, hand-written agent
records). Demonstrates wiring only; nothing here is market data or performance evidence."""
from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sidedeck.application.p5_agents import TRADINGAGENTS_REVISION
from sidedeck.application.sd069_agent_signal_adapters import adapt_agent_record
from sidedeck.application.sd070_research_signal import EvidenceRef, ResearchSignal
from sidedeck.application.sd071_decision_engine import (
    MarketContext,
    PortfolioState,
    StrategyAdmission,
    TrackPolicy,
    decide,
)
from sidedeck.application.sd067_market_scanner import DEFAULT_SCORING, build_shortlist, run_broad_scan
from sidedeck.application.sd077_data_authorization import DataRequestLedger
from sidedeck.application.sd078_alpaca_sip_pilot import (
    PILOT_END,
    PILOT_START,
    draft_authorization,
    run_pilot,
)
from sidedeck.application.sd072_track_risk_limits import TrackLimits
from sidedeck.application.sd079_track_ledgers import TrackLedger
from sidedeck.application.sd014_strategy_engine import StrategyBar
from sidedeck.application.us_equity_calendar import expected_regular_sessions

NOW = datetime(2026, 10, 22, 14, tzinfo=UTC)
SESSIONS = expected_regular_sessions(PILOT_START, PILOT_END)


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *a: object) -> None:
        self.close()


def _fixture_payload(symbol: str) -> bytes:
    seed = sum(map(ord, symbol))
    price = 50.0 + seed % 200
    bars = []
    for i, d in enumerate(SESSIONS):
        drift = 1 + ((seed % 5) - 1) / 2000 + (0.004 if i % 2 else -0.004)
        close = round(price * drift, 2)
        bars.append({"t": f"{d}T04:00:00Z", "o": price, "h": round(max(price, close) * 1.01, 2),
                     "l": round(min(price, close) * 0.99, 2), "c": close,
                     "v": 5_000_000 + seed * 1000})
        price = close
    return json.dumps({"bars": bars, "next_page_token": None}).encode()


def test_fixture_pipeline_end_to_end(tmp_path: Path) -> None:
    auth = draft_authorization(NOW - timedelta(minutes=1))
    ledger = DataRequestLedger(tmp_path / "req.sqlite3", auth)

    def opener(request: Any, timeout: float = 20) -> _Resp:
        symbol = request.full_url.split("/stocks/")[1].split("/")[0]
        return _Resp(_fixture_payload(symbol))

    summary = run_pilot(auth, ledger, tmp_path / "pilot", key_id="k", secret="s",
                        now=lambda: NOW, opener=opener, pause=lambda: None)
    assert summary["coverage_counts"]["COVERED"] == 20 and summary["benchmark_status"] == "COVERED"

    bars: dict[str, tuple[StrategyBar, ...]] = {}
    for path in (tmp_path / "pilot" / "raw").rglob("*.json"):
        data = json.loads(path.read_text())
        bars["US:" + data["ticker"]] = tuple(
            StrategyBar(datetime.fromisoformat(r["date"]).date(), Decimal(r["open"]),
                        Decimal(r["high"]), Decimal(r["low"]), Decimal(r["close"]),
                        Decimal(r["volume"])) for r in data["records"])
    report = run_broad_scan(sorted(bars), bars.__getitem__, PILOT_END, data_basis="FIXTURE",
                            benchmark=bars["US:SPY"])
    assert len(report.features) == 20 and report.excluded == ()
    swing = build_shortlist(report, DEFAULT_SCORING["SWING"])
    top = swing.research[0].canonical_id

    agent = adapt_agent_record({
        "portfolio": "tradingagents", "ticker": top[3:], "upstream": "TauricResearch/TradingAgents",
        "status": "RESEARCH_ONLY", "decision": "BUY", "rationale": "fixture", "instrument_id": top,
        "market_cutoff": (NOW - timedelta(hours=18)).isoformat(),
        "decision_timestamp": (NOW - timedelta(hours=1)).isoformat(),
        "upstream_version": TRADINGAGENTS_REVISION, "evidence_references": ["fixture"],
    }, invoked="tradingagents", allowed_ids=[c.canonical_id for c in swing.research], now=NOW)
    assert agent.signal is not None
    feature = next(f for f in report.features if f.canonical_id == top)
    native = ResearchSignal(
        canonical_id=top, track="SWING", source_kind="NATIVE_STRATEGY",
        source_id="channel_mean_reversion", source_version="1.0.0", horizon_min_days=5,
        horizon_max_days=15, direction="LONG",
        evidence=(EvidenceRef("fixture_backtest", "fixture", "b" * 64),),
        generated_at=NOW - timedelta(hours=1), data_cutoff=NOW - timedelta(hours=18),
        invalidation=("fixture invalidation",))
    admission = StrategyAdmission("channel_mean_reversion", "1.0.0", "SWING", "ADMITTED",
                                  "FIXTURE-ONLY admission for wiring test", 30, True)
    policy = TrackPolicy(
        policy_id="fixture", track="SWING", virtual_capital=Decimal(1000),
        max_position_pct=Decimal("0.2"), max_positions=5, max_gross_exposure_pct=Decimal("0.8"),
        max_instrument_total_pct=Decimal("0.25"), max_sector_pct=Decimal("0.4"),
        max_correlation=Decimal("0.85"), risk_per_trade_pct=Decimal("0.01"),
        stop_atr_multiple=Decimal(2), min_notional=Decimal(10),
        max_signal_age=timedelta(days=1), max_signal_data_age=timedelta(days=4),
        max_price_age=timedelta(days=1), expires_at=NOW + timedelta(days=1),
        allowed_strategies=frozenset({("channel_mean_reversion", "1.0.0")}))
    market = MarketContext(top, feature.last_close, NOW - timedelta(hours=18), feature.atr14,
                           "FIXTURE", session_open=True, execution_eligible=True)
    agent_only = decide([agent.signal], [admission], policy,
                        PortfolioState((), {"SWING": Decimal(1000)}), market, NOW)
    assert agent_only.status == "WATCHLIST"
    decision = decide([native, agent.signal], [admission], policy,
                      PortfolioState((), {"SWING": Decimal(1000)}), market, NOW)
    assert decision.status == "ELIGIBLE" and decision.sizing is not None

    track = TrackLedger.open(tmp_path / "swing.sqlite3", "SWING", Decimal(1000))
    position = track.open_from_decision(
        "fx-1", decision, feature.last_close, Decimal(0), NOW + timedelta(minutes=1),
        limits=TrackLimits("SWING", Decimal("0.1"), Decimal("0.03"), 5), prices={},
        session_start_equity=Decimal(1000))
    assert position.signal_ids == decision.qualified_signal_ids
    assert decision.execution_permission == "NOT_GRANTED_BY_DECISION_ENGINE"
