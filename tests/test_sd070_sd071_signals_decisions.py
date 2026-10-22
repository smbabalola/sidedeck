"""SD-070 signal contract and SD-071 decision engine. All inputs are synthetic fixtures."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from sidedeck.application.sd070_research_signal import (
    EvidenceRef,
    ResearchSignal,
    SignalError,
    normalize_signal,
)
from sidedeck.application.sd071_decision_engine import (
    EXECUTION_PERMISSION,
    Decision,
    DecisionError,
    Holding,
    MarketContext,
    PortfolioState,
    StrategyAdmission,
    TrackPolicy,
    decide,
)

NOW = datetime(2026, 10, 22, 15, tzinfo=UTC)
SHA = "a" * 64
EVIDENCE = (EvidenceRef("backtest", "docs/fixture.md", SHA),)


def _sig(**kw: Any) -> ResearchSignal:
    base = ResearchSignal(
        canonical_id="US:AAA", track="SWING", source_kind="NATIVE_STRATEGY",
        source_id="channel_mean_reversion", source_version="1.0.0", horizon_min_days=5,
        horizon_max_days=15, direction="LONG", evidence=EVIDENCE,
        generated_at=NOW - timedelta(hours=1), data_cutoff=NOW - timedelta(hours=18),
        invalidation=("close below 20-day low",),
    )
    return replace(base, **kw)


ADMIT = StrategyAdmission("channel_mean_reversion", "1.0.0", "SWING", "ADMITTED",
                          "docs/fixture-oos.md", 40, True)
POLICY = TrackPolicy(
    policy_id="fixture-swing", track="SWING", virtual_capital=Decimal("1000"),
    max_position_pct=Decimal("0.20"), max_positions=5, max_gross_exposure_pct=Decimal("0.80"),
    max_instrument_total_pct=Decimal("0.25"), max_sector_pct=Decimal("0.40"),
    max_correlation=Decimal("0.85"), risk_per_trade_pct=Decimal("0.01"),
    stop_atr_multiple=Decimal("2"), min_notional=Decimal("10"),
    max_signal_age=timedelta(days=1), max_signal_data_age=timedelta(days=4),
    max_price_age=timedelta(minutes=15),
    expires_at=NOW + timedelta(days=7),
    allowed_strategies=frozenset({("channel_mean_reversion", "1.0.0")}),
)
MARKET = MarketContext("US:AAA", Decimal("100"), NOW - timedelta(minutes=1), Decimal("2"),
                       "TECH", session_open=True, execution_eligible=True)
EMPTY = PortfolioState((), {"SWING": Decimal("1000"), "DAY": Decimal("500")})


# --- SD-070 -----------------------------------------------------------------------

def _raw(**kw: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "canonical_id": "US:AAA", "track": "SWING", "source_kind": "TRADINGAGENTS",
        "source_id": "tradingagents", "source_version": "0.7.0", "horizon_min_days": 3,
        "horizon_max_days": 10, "direction": "LONG",
        "evidence": [{"kind": "report", "reference": "r1", "sha256": SHA}],
        "generated_at": (NOW - timedelta(hours=1)).isoformat(),
        "data_cutoff": (NOW - timedelta(hours=20)).isoformat(),
        "invalidation": ["thesis broken"], "confidence": "0.6",
    }
    raw.update(kw)
    return raw


def _norm(raw: dict[str, Any]) -> ResearchSignal:
    return normalize_signal(raw, now=NOW, source_kind="TRADINGAGENTS", source_id="tradingagents")


def test_normalize_valid_signal_is_stable() -> None:
    signal = _norm(_raw())
    assert signal.is_agent and signal.confidence == Decimal("0.6")
    assert signal.signal_id == _norm(_raw()).signal_id
    assert len(signal.signal_id) == 64


@pytest.mark.parametrize("extra", [
    {"order_type": "market"}, {"execute": True}, {"permission": "granted"},
    {"quantity": 10}, {"position_size": "5%"}, {"broker_account": "x"}, {"approved": True},
])
def test_agents_cannot_carry_execution_fields(extra: dict[str, Any]) -> None:
    with pytest.raises(SignalError, match="execution fields"):
        _norm(_raw(**extra))


@pytest.mark.parametrize("change, message", [
    ({"surprise": 1}, "unknown"),
    ({"track": "CRYPTO"}, "track"),
    ({"source_kind": "CHATGPT"}, "does not match"),
    ({"source_kind": "NATIVE_STRATEGY"}, "does not match"),
    ({"source_id": "channel_mean_reversion"}, "does not match"),
    ({"horizon_max_days": 9.9}, "integer"),
    ({"horizon_min_days": True}, "integer"),
    ({"horizon_max_days": 40}, "horizon"),
    ({"track": "DAY"}, "horizon"),
    ({"direction": "BUY"}, "direction"),
    ({"evidence": []}, "evidence"),
    ({"invalidation": []}, "invalidation"),
    ({"confidence": "1.5"}, "confidence"),
    ({"confidence": "NaN"}, "confidence"),
    ({"calibration": "CALIBRATED"}, "calibration reference"),
    ({"data_cutoff": NOW.isoformat()}, "look-ahead"),
    ({"generated_at": (NOW + timedelta(minutes=1)).isoformat(),
      "data_cutoff": NOW.isoformat()}, "future"),
    ({"generated_at": "2026-10-22T10:00:00"}, "timezone"),
    ({"canonical_id": "AAA"}, "canonical"),
    ({"source_version": " "}, "versioned"),
    ({"evidence": [{"kind": "r", "reference": "x", "sha256": "nothex"}]}, "SHA-256"),
])
def test_malformed_signals_fail_closed(change: dict[str, Any], message: str) -> None:
    with pytest.raises(SignalError, match=message):
        _norm(_raw(**change))


def test_abstain_and_neutral_need_no_evidence() -> None:
    assert _norm(_raw(direction="ABSTAIN", evidence=[],
                      invalidation=[])).direction == "ABSTAIN"


# --- SD-071 -----------------------------------------------------------------------

def test_admitted_native_long_is_eligible_with_risk_sizing() -> None:
    d = decide([_sig()], [ADMIT], POLICY, EMPTY, MARKET, NOW)
    assert d.status == "ELIGIBLE" and d.sizing is not None
    # Risk budget 1% of 1000 = 10; stop 2*ATR = 4 -> 2.5 units = 250 notional;
    # max position 20% = 200 binds.
    assert d.sizing.notional == Decimal("200.00") and d.sizing.quantity == Decimal("2.0000")
    assert d.sizing.stop_price == Decimal("96") and "BINDING_LIMIT:MAX_POSITION" in d.reasons
    assert d.execution_permission == EXECUTION_PERMISSION


def test_agent_only_agreement_is_watchlist_not_eligible() -> None:
    agents = [_sig(source_kind="TRADINGAGENTS", source_id="ta", source_version="0.7.0"),
              _sig(source_kind="AI_HEDGE_FUND", source_id="buffett", source_version="2.5.0")]
    d = decide(agents, [ADMIT], POLICY, EMPTY, MARKET, NOW)
    assert d.status == "WATCHLIST" and "AGENT_AGREEMENT_IS_NOT_PROOF_OF_EDGE" in d.reasons
    assert d.sizing is None


def test_unadmitted_or_research_only_strategy_cannot_qualify() -> None:
    research_only = replace(ADMIT, status="RESEARCH_ONLY")
    assert decide([_sig()], [research_only], POLICY, EMPTY, MARKET, NOW).status == "WATCHLIST"
    with pytest.raises(DecisionError, match="out-of-sample"):
        replace(ADMIT, oos_validated=False)
    with pytest.raises(DecisionError):
        replace(ADMIT, oos_trades=5)


def test_cross_track_signals_are_never_reused() -> None:
    position_signal = _sig(track="POSITION", horizon_min_days=20, horizon_max_days=120)
    day_policy = replace(POLICY, track="DAY", policy_id="fixture-day")
    d = decide([position_signal], [ADMIT], day_policy, EMPTY, MARKET, NOW)
    assert d.status == "ABSTAIN" and "IGNORED_OTHER_TRACK:POSITION" in d.reasons


def test_disagreement_conflict_and_long_only() -> None:
    bearish_agent = _sig(source_kind="TRADINGAGENTS", source_id="ta", source_version="0.7.0",
                         direction="SHORT")
    d = decide([_sig(), bearish_agent], [ADMIT], POLICY, EMPTY, MARKET, NOW)
    assert d.status == "WATCHLIST" and d.disagreements == ("TRADINGAGENTS:ta:SHORT",)
    other = StrategyAdmission("moving_average_trend", "1.0.0", "SWING", "ADMITTED", "x", 40, True)
    short_native = _sig(source_id="moving_average_trend", direction="SHORT")
    assert decide([_sig(), short_native], [ADMIT, other], POLICY, EMPTY, MARKET,
                  NOW).reasons[0] == "QUALIFIED_SIGNALS_CONFLICT"
    assert decide([short_native], [other], POLICY, EMPTY, MARKET,
                  NOW).reasons[0] == "LONG_ONLY_POLICY"


@pytest.mark.parametrize("signals, policy, portfolio, market, reason", [
    ([_sig(generated_at=NOW - timedelta(days=2), data_cutoff=NOW - timedelta(days=3))],
     POLICY, EMPTY, MARKET, "NO_CURRENT_SIGNAL"),
    ([_sig()], replace(POLICY, expires_at=NOW), EMPTY, MARKET, "POLICY_EXPIRED"),
    ([_sig()], replace(POLICY, allowed_strategies=frozenset()), EMPTY, MARKET,
     "STRATEGY_NOT_IN_POLICY_SCOPE"),
    ([_sig()], replace(POLICY, allowed_instruments=frozenset({"US:BBB"})), EMPTY, MARKET,
     "INSTRUMENT_NOT_IN_POLICY_SCOPE"),
    ([_sig()], POLICY, EMPTY, replace(MARKET, price_time=NOW - timedelta(hours=1)),
     "STALE_OR_FUTURE_MARKET_DATA"),
    ([_sig()], POLICY, EMPTY, replace(MARKET, price_time=NOW + timedelta(minutes=1)),
     "STALE_OR_FUTURE_MARKET_DATA"),
    ([_sig()], POLICY, EMPTY, replace(MARKET, atr=Decimal(0)), "INVALID_MARKET_DATA"),
    ([_sig()], POLICY, EMPTY, replace(MARKET, atr=Decimal(60)), "STOP_DISTANCE_EXCEEDS_PRICE"),
    ([_sig()], POLICY, PortfolioState((Holding("US:AAA", "SWING", Decimal(100), "TECH"),),
                                      {"SWING": Decimal(900)}), MARKET, "ALREADY_HELD_IN_TRACK"),
    ([_sig()], replace(POLICY, max_positions=1),
     PortfolioState((Holding("US:BBB", "SWING", Decimal(100), "X"),), {"SWING": Decimal(900)}),
     MARKET, "MAX_POSITIONS"),
    ([_sig()], POLICY,
     PortfolioState((Holding("US:BBB", "SWING", Decimal(100), "X"),), {"SWING": Decimal(900)}),
     replace(MARKET, correlations={"US:BBB": Decimal("0.95")}), "CORRELATED_WITH_HOLDING:US:BBB"),
    ([_sig()], POLICY, PortfolioState((), {"SWING": Decimal(5)}), MARKET,
     "INSUFFICIENT_CAPACITY:CASH"),
])
def test_constraints_reject(signals: list[ResearchSignal], policy: TrackPolicy,
                            portfolio: PortfolioState, market: MarketContext, reason: str) -> None:
    d = decide(signals, [ADMIT], policy, portfolio, market, NOW)
    assert d.status in ("REJECTED", "ABSTAIN") and d.reasons[0] == reason and d.sizing is None


def test_cross_track_instrument_cap_and_sector_cap_bind() -> None:
    day_holding = Holding("US:AAA", "DAY", Decimal("200"), "TECH")
    d = decide([_sig()], [ADMIT], POLICY, PortfolioState((day_holding,), EMPTY.cash_by_track),
               MARKET, NOW)
    # 25% instrument cap = 250 minus 200 already held in DAY -> 50.
    assert d.status == "ELIGIBLE" and d.sizing and d.sizing.notional == Decimal("50.00")
    assert "BINDING_LIMIT:INSTRUMENT_TOTAL" in d.reasons
    sector = PortfolioState((Holding("US:BBB", "SWING", Decimal("395"), "TECH"),),
                            {"SWING": Decimal("605")})
    correlated = replace(MARKET, correlations={"US:BBB": Decimal("0.2")})
    assert decide([_sig()], [ADMIT], POLICY, sector, correlated,
                  NOW).reasons[0] == "INSUFFICIENT_CAPACITY:SECTOR"


def test_not_execution_eligible_is_watchlist_and_day_requires_open_session() -> None:
    d = decide([_sig()], [ADMIT], POLICY, EMPTY, replace(MARKET, execution_eligible=False), NOW)
    assert d.status == "WATCHLIST" and d.reasons == ("NOT_BROKER_EXECUTION_ELIGIBLE",)
    day_sig = _sig(track="DAY", horizon_min_days=0, horizon_max_days=0)
    day_admit = replace(ADMIT, track="DAY")
    day_policy = replace(POLICY, track="DAY")
    closed = decide([day_sig], [day_admit], day_policy, EMPTY,
                    replace(MARKET, session_open=False), NOW)
    assert closed.reasons[0] == "OUTSIDE_TRADING_HOURS"
    opened = decide([day_sig], [day_admit], day_policy, EMPTY, MARKET, NOW)
    assert opened.sizing and opened.sizing.exit_rule == "SAME_SESSION_LIQUIDATION"


def test_decision_cannot_be_forged_with_permission() -> None:
    with pytest.raises(DecisionError, match="cannot grant"):
        Decision("ELIGIBLE", "US:AAA", "SWING", "p", NOW, (), execution_permission="GRANTED")
    with pytest.raises(DecisionError):
        Decision("ELIGIBLE", "US:AAA", "SWING", "p", NOW, ())   # ELIGIBLE without sizing
    with pytest.raises(DecisionError):
        decide([_sig()], [ADMIT], POLICY, EMPTY, MARKET, NOW.replace(tzinfo=None))
    with pytest.raises(DecisionError):
        replace(POLICY, max_position_pct=Decimal("1.5"))


def test_review_external_payload_cannot_become_native_or_qualified() -> None:
    raw = _raw(source_version="1.0.0")
    raw.pop("source_kind")
    raw.pop("source_id")
    with pytest.raises(SignalError, match="only agent"):
        normalize_signal(raw, now=NOW, source_kind="NATIVE_STRATEGY",
                         source_id="channel_mean_reversion")
    agent = normalize_signal(raw, now=NOW, source_kind="TRADINGAGENTS", source_id="ta")
    assert decide([agent], [ADMIT], POLICY, EMPTY, MARKET, NOW).status == "WATCHLIST"


def test_review_admission_floor_cannot_be_lowered() -> None:
    with pytest.raises(DecisionError):
        StrategyAdmission("x", "1", "SWING", "ADMITTED", "ev", 0, True, min_oos_trades=0)
    with pytest.raises(DecisionError):
        StrategyAdmission("x", "1", "SWING", "ADMITTED", "ev", 29, True, min_oos_trades=10)


def test_review_stale_data_cutoff_cannot_reach_eligible() -> None:
    stale = _sig(generated_at=NOW, data_cutoff=NOW - timedelta(days=400))
    d = decide([stale], [ADMIT], POLICY, EMPTY, MARKET, NOW)
    assert d.status == "ABSTAIN" and "STALE_SIGNAL_DATA:channel_mean_reversion" in d.reasons


@pytest.mark.parametrize("corr", [None, Decimal("NaN"), Decimal("1.5")])
def test_review_missing_or_invalid_correlation_fails_closed(corr: Decimal | None) -> None:
    held = PortfolioState((Holding("US:BBB", "SWING", Decimal(100), "X"),), {"SWING": Decimal(900)})
    market = replace(MARKET, correlations={} if corr is None else {"US:BBB": corr})
    d = decide([_sig()], [ADMIT], POLICY, held, market, NOW)
    assert d.status == "REJECTED" and d.reasons[0] == "MISSING_CORRELATION:US:BBB"


def test_review_naive_price_time_and_utc_stable_signal_id() -> None:
    with pytest.raises(DecisionError):
        decide([_sig()], [ADMIT], POLICY, EMPTY,
                replace(MARKET, price_time=MARKET.price_time.replace(tzinfo=None)), NOW)
    from zoneinfo import ZoneInfo

    ny = ZoneInfo("America/New_York")
    a = _sig()
    b = _sig(generated_at=a.generated_at.astimezone(ny), data_cutoff=a.data_cutoff.astimezone(ny))
    assert a.signal_id == b.signal_id
