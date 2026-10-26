"""SD-103 integrated pipeline: acceptance on labelled fixtures plus negative scenarios.

Fixture results prove wiring only. The genuine-data smoke test uses the ignored local SD-021
bundles when present and is skipped otherwise (CI has no private data)."""
from __future__ import annotations

import copy
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from sidedeck.application import sd103_trading_pipeline as p
from sidedeck.application.sd014_strategy_engine import StrategyBar, generate_signals
from sidedeck.application.sd079_track_ledgers import Position

DATA = Path(__file__).resolve().parents[1] / "data"
SHORT = (date(2026, 5, 1), date(2026, 7, 31))


@pytest.fixture(scope="module")
def ctx_bundle():
    return p.fixture_context()


def fresh(ctx_bundle):
    ctx, excluded = ctx_bundle
    return replace(ctx, signal_maps={}), excluded


@pytest.fixture(scope="module")
def acceptance_report(tmp_path_factory):
    return p.acceptance(tmp_path_factory.mktemp("acceptance"))


# ---- end-to-end acceptance -----------------------------------------------------------------------

def test_acceptance_runs_the_full_lifecycle(acceptance_report):
    r = acceptance_report
    assert r["data_basis"] == p.FIXTURE
    perf = r["replay"]["performance"]
    assert perf["basis"] == "SIMULATION_ON_SYNTHETIC_FIXTURE_NOT_PERFORMANCE_EVIDENCE"
    assert perf["closed_trades"] > 0
    assert perf["cash_reconciliation"]["status"] == "MATCHED"
    assert perf["kill_switch"] == "CLEAR"
    assert set(perf["by_strategy"]) == {"channel_mean_reversion@1.0.0"}
    reasons = {pos.get("exit_reason") for pos in r["replay"]["positions"].values()}
    assert "STOP_LOSS" in reasons and reasons & {"STRATEGY_EXIT", "TARGET"}
    fills = [e for e in r["replay"]["events"] if e["event"] in ("FILLED", "PARTIALLY_FILLED")]
    assert fills and all(e["fill"]["basis"] == p.SIMULATED_LOCAL for e in fills)


def test_acceptance_labels_every_non_evidence_part(acceptance_report):
    r = acceptance_report
    overridden = [s for s in r["strategies"] if s.get("override")]
    assert overridden and all(s["override"] == p.FIXTURE_OVERRIDE for s in overridden)
    assert all("admission_without_override" in s for s in overridden)
    assert r["gates"]["STRATEGY_ADMISSION"].startswith("NOT_ASSESSED")
    assert r["gates"]["BROKER"].startswith("BLOCKED")
    assert r["gates"]["PAPER_EXECUTION"].startswith("BLOCKED")
    assert r["execution"]["orders_submitted_to_a_broker"] == 0
    assert all(o["status"] == "PROPOSED_NOT_SUBMITTED" for o in r["orders"])


def test_decision_rows_carry_the_required_fields(acceptance_report):
    required = {"symbol", "direction", "strategy", "entry", "stop_loss", "target",
                "holding_period", "quantity", "capital_required_usd", "risk_reward",
                "evidence", "decision"}
    for row in acceptance_report["decisions"]:
        assert required <= set(row)
        assert row["execution_permission"] == "NOT_GRANTED_BY_DECISION_ENGINE"
        assert row["entry"]["reference_basis"] == "HISTORICAL_CLOSE_NOT_EXECUTABLE"


def test_eligible_decision_sizing_respects_the_position_cap(acceptance_report):
    for d in acceptance_report["decisions"]:
        if d["decision"] == "ELIGIBLE":
            assert Decimal(d["capital_required_usd"]) <= Decimal("50.05")
            assert Decimal(d["stop_loss"]) < Decimal(d["entry"]["reference_close"])


def test_agents_unavailable_without_authorized_runs(acceptance_report):
    agents = acceptance_report["agents"]
    assert {a["portfolio"] for a in agents} == {"tradingagents", "ai-trading"}
    assert all(a["status"] == "UNAVAILABLE" for a in agents)
    assert acceptance_report["gates"]["AI_RESEARCH"].startswith("BLOCKED")


# ---- strategy admission and signals ---------------------------------------------------------------

def test_without_override_nothing_is_admitted_and_no_trade_is_explained():
    ctx, _ = p.fixture_context(override=frozenset())
    assert not [a for r in ctx.research.values() for a in r.admissions if a.status == "ADMITTED"]
    report = p.run_report(ctx, {}, now=p.session_close_utc(p.ACCEPTANCE_WINDOW[1])
                          + timedelta(minutes=5), mode="run")
    assert report["orders"] == [] and report["no_trade"].startswith("NO TRADE")
    assert all(d["decision"] != "ELIGIBLE" for d in report["decisions"])


def test_admission_override_is_refused_for_real_data(ctx_bundle):
    ctx, _ = ctx_bundle
    research = next(iter(ctx.research.values()))
    with pytest.raises(p.PipelineError):
        p.apply_fixture_override(research, frozenset({"channel_mean_reversion"}), p.REAL_DATA)
    with pytest.raises(p.PipelineError):
        p.build_context([], basis=p.REAL_DATA, admission_through=date(2026, 4, 30),
                        cfg=p.PipelineConfig(), fixture_override=frozenset({"x"}))


def test_signals_are_causal_no_look_ahead(ctx_bundle):
    ctx, _ = ctx_bundle
    bars = ctx.evidence["US:SPY"].bars
    spec = p._spec("channel_mean_reversion")
    full = generate_signals(spec, bars)
    for cut in (400, 777, 1100):
        prefix = generate_signals(spec, bars[:cut])
        assert all(prefix[b.day] == full[b.day] for b in bars[:cut])


def test_strategy_admission_is_locked_before_the_replay_window(ctx_bundle):
    ctx, _ = ctx_bundle
    for research in ctx.research.values():
        for record in research.records:
            assert record["evidence"]["admission_data_through"] <= "2026-04-30"


# ---- market data negatives ---------------------------------------------------------------------

def _bundle(**changes):
    payload = p.synthetic_bundle("SPY", start=date(2025, 1, 2), end=date(2026, 4, 30))
    payload.update(changes)
    return payload


def test_one_data_basis_per_run():
    with pytest.raises(p.PipelineError):
        p.admit_market_data(_bundle(), basis=p.REAL_DATA, through=date(2026, 4, 30),
                            source_sha256="a" * 64)
    real_looking = _bundle(synthetic_fixture=False, admission_status="ADMITTED_RESEARCH_ONLY",
                           source="https://example.invalid/bars")
    with pytest.raises(p.PipelineError):
        p.admit_market_data(real_looking, basis=p.FIXTURE, through=date(2026, 4, 30),
                            source_sha256="a" * 64)


def test_invalid_prices_are_refused():
    payload = _bundle()
    payload["records"][10] = {**payload["records"][10], "high": "1.00"}
    with pytest.raises(p.PipelineError):
        p.admit_market_data(payload, basis=p.FIXTURE, through=date(2026, 4, 30),
                            source_sha256="a" * 64)
    payload = _bundle()
    payload["records"][5] = {**payload["records"][5], "close": "-3"}
    with pytest.raises(p.PipelineError):
        p.admit_market_data(payload, basis=p.FIXTURE, through=date(2026, 4, 30),
                            source_sha256="a" * 64)


def test_missing_sessions_are_refused():
    payload = _bundle()
    del payload["records"][100]
    with pytest.raises(p.PipelineError, match="missing"):
        p.admit_market_data(payload, basis=p.FIXTURE, through=date(2026, 4, 30),
                            source_sha256="a" * 64)


def test_stale_market_data_never_produces_an_order(ctx_bundle):
    ctx, _ = fresh(ctx_bundle)
    late = p.session_close_utc(p.ACCEPTANCE_WINDOW[1]) + timedelta(days=10)
    report = p.run_report(ctx, {}, now=late, mode="run")
    assert report["data_freshness"]["status"] == "STALE_FOR_EXECUTION"
    assert report["orders"] == []
    assert all(d["decision"] != "ELIGIBLE" for d in report["decisions"])


# ---- risk, capital and broker negatives -----------------------------------------------------------

def test_missing_owner_authorisation_refuses_broker_routes():
    for route in ("ETORO_DEMO", "ALPACA_PAPER", "ETORO_REAL", "SOMETHING_ELSE"):
        with pytest.raises(p.ExecutionNotReleased):
            p.require_route(route)
    assert p.require_route(p.SIMULATED_LOCAL) == p.SIMULATED_LOCAL


def test_replay_refuses_a_non_simulated_route(ctx_bundle, tmp_path):
    ctx, _ = fresh(ctx_bundle)
    blocked = replace(ctx, cfg=replace(ctx.cfg, route="ETORO_DEMO"))
    with pytest.raises(p.ExecutionNotReleased):
        p.replay(blocked, start=SHORT[0], end=SHORT[1], workdir=tmp_path)


def test_insufficient_capital_produces_no_fills(tmp_path):
    ctx, _ = p.fixture_context(virtual_capital=Decimal("100"))
    result = p.replay(ctx, start=SHORT[0], end=SHORT[1], workdir=tmp_path)
    assert not [e for e in result["events"] if e["event"] in ("FILLED", "PARTIALLY_FILLED")]
    rejected = [e for e in result["events"] if e["event"] == "DECISION"
                and e["decision"] == "REJECTED"]
    assert rejected and all(any("INSUFFICIENT_CAPACITY" in r for r in e["reasons"])
                            for e in rejected)


def test_no_account_mixing_between_runs(ctx_bundle, tmp_path):
    ctx, _ = fresh(ctx_bundle)
    p.replay(ctx, start=SHORT[0], end=date(2026, 5, 8), workdir=tmp_path)
    other = replace(ctx, cfg=replace(ctx.cfg, virtual_capital=Decimal("2000")), signal_maps={})
    with pytest.raises(p.PipelineError, match="account mixing"):
        p.replay(other, start=SHORT[0], end=date(2026, 5, 8), workdir=tmp_path)


def test_duplicate_submission_is_refused():
    broker = p.SimulatedBroker(Decimal(5), Decimal(5))
    bar = StrategyBar(date(2026, 5, 1), Decimal(100), Decimal(101), Decimal(99), Decimal(100),
                      Decimal(1000))
    intent = {"intent_id": "abc", "units": "1", "limit_price": "100000"}
    assert broker.entry(intent, bar)["status"] == "FILLED"
    with pytest.raises(p.PipelineError, match="duplicate"):
        broker.entry(intent, bar)


def test_ioc_limit_is_honoured():
    broker = p.SimulatedBroker(Decimal(5), Decimal(5))
    bar = StrategyBar(date(2026, 5, 1), Decimal(100), Decimal(101), Decimal(99), Decimal(100),
                      Decimal(1000))
    result = broker.entry({"intent_id": "x", "units": "1", "limit_price": "99.99"}, bar)
    assert result["status"] == "EXPIRED_IOC_LIMIT" and result["units"] == "0"


def test_partial_fills_open_only_the_filled_units(ctx_bundle, tmp_path):
    ctx, _ = fresh(ctx_bundle)
    broker = p.SimulatedBroker(Decimal(5), Decimal(5), partial_ratio=Decimal("0.5"))
    result = p.replay(ctx, start=SHORT[0], end=SHORT[1], workdir=tmp_path, broker=broker)
    partial = [a for a in result["attribution"].values()
               if a["fill_status"] == "PARTIALLY_FILLED"]
    assert partial
    for item in partial:
        assert Decimal(item["units_filled"]) * 2 <= Decimal(item["units_ordered"])
    perf = p.performance(result, ctx, start=SHORT[0], end=SHORT[1])
    assert perf["cash_reconciliation"]["status"] == "MATCHED"


def test_unexpected_overfill_is_unresolved_and_halts(ctx_bundle, tmp_path):
    ctx, _ = fresh(ctx_bundle)
    broker = p.SimulatedBroker(Decimal(5), Decimal(5), overfill=True)
    result = p.replay(ctx, start=SHORT[0], end=SHORT[1], workdir=tmp_path, broker=broker)
    assert result["halted"] and "exceeds" in result["halted"]
    assert not result["attribution"] and not result["ledger"].positions
    assert len([e for e in result["events"] if e["event"] == "UNRESOLVED"]) == 1


def test_broker_outage_is_unresolved_and_stops_new_entries(ctx_bundle, tmp_path):
    ctx, _ = fresh(ctx_bundle)
    days = frozenset(date(2026, 5, 1) + timedelta(days=n) for n in range(120))
    broker = p.SimulatedBroker(Decimal(5), Decimal(5), outage_days=days)
    result = p.replay(ctx, start=SHORT[0], end=SHORT[1], workdir=tmp_path, broker=broker)
    unresolved = [e for e in result["events"] if e["event"] == "UNRESOLVED"]
    assert len(unresolved) == 1 and result["halted"]
    assert p.performance(result, ctx, start=SHORT[0], end=SHORT[1])["kill_switch"] == "HALTED"
    first = unresolved[0]["day"]
    assert not [e for e in result["events"] if e["event"] == "DECISION" and e["day"] > first]


def test_stop_wins_when_stop_and_target_touch_and_gaps_fill_at_open():
    pos = Position("r", "US:SPY", Decimal(1), Decimal(100), Decimal(0),
                   datetime(2026, 5, 1, tzinfo=UTC), "x", (), Decimal(95))
    both = StrategyBar(date(2026, 5, 4), Decimal(100), Decimal(110), Decimal(90), Decimal(100),
                       Decimal(1))
    assert p.manage_position(pos, both, sessions_held=1, horizon=15,
                             target=Decimal(105)) == ("STOP_LOSS", Decimal(95))
    gap = StrategyBar(date(2026, 5, 5), Decimal(90), Decimal(91), Decimal(89), Decimal(90),
                      Decimal(1))
    assert p.manage_position(pos, gap, sessions_held=1, horizon=15,
                             target=None) == ("STOP_LOSS", Decimal(90))
    quiet = StrategyBar(date(2026, 5, 6), Decimal(100), Decimal(101), Decimal(99), Decimal(100),
                        Decimal(1))
    assert p.manage_position(pos, quiet, sessions_held=15, horizon=15,
                             target=None) == ("TIME_EXIT", Decimal(100))


def test_agent_signal_cannot_create_an_eligible_trade_alone(ctx_bundle):
    from sidedeck.application.p5_agents import TRADINGAGENTS_REVISION
    ctx, _ = p.fixture_context(override=frozenset())
    now = p.session_close_utc(p.ACCEPTANCE_WINDOW[1]) + timedelta(minutes=5)
    record = {"portfolio": "tradingagents", "ticker": "QQQ", "instrument_id": "US:QQQ",
              "upstream": "TauricResearch/TradingAgents", "status": "RESEARCH_ONLY",
              "decision": "BUY", "rationale": "fixture", "upstream_version":
              TRADINGAGENTS_REVISION, "market_cutoff": (now - timedelta(hours=2)).isoformat(),
              "decision_timestamp": (now - timedelta(hours=1)).isoformat(),
              "evidence_references": ["fixture"]}
    with_agent = replace(ctx, agent_records=(copy.deepcopy(record),))
    report = p.run_report(with_agent, {}, now=now, mode="run")
    qqq = next(d for d in report["decisions"] if d["symbol"] == "US:QQQ")
    assert qqq["decision"] == "WATCHLIST"
    assert "NO_ADMITTED_STRATEGY_SIGNAL" in qqq["reasons"]
    assert any(a["status"] == "SIGNAL" for a in report["agents"])
    assert report["orders"] == []


def test_report_writer_keeps_history_and_latest(acceptance_report, tmp_path):
    first = p.write_report(acceptance_report, tmp_path)
    assert first.is_file() and (tmp_path / "latest-run.json").is_file()
    assert "_decision" not in (tmp_path / "latest-run.json").read_text(encoding="utf-8")


# ---- genuine data (local only) -------------------------------------------------------------------

@pytest.mark.skipif(not (DATA / "sd021-spy-admitted.json").is_file(),
                    reason="ignored local SD-021 bundles are not present")
def test_genuine_bundles_produce_an_honest_no_trade():
    bundles = [p.load_bundle(DATA / f"sd021-{t}-admitted.json") for t in ("spy", "qqq", "msft")]
    ctx, excluded = p.build_context(bundles, basis=p.REAL_DATA,
                                    admission_through=date(2026, 12, 31),
                                    cfg=p.PipelineConfig())
    assert excluded == {}
    report = p.run_report(ctx, excluded, now=datetime(2026, 10, 26, 12, tzinfo=UTC), mode="run")
    assert report["gates"]["REAL_DATA"].startswith("VERIFIED")
    assert report["admitted_strategies"] == []
    assert report["gates"]["STRATEGY_ADMISSION"].startswith("BLOCKED")
    assert report["orders"] == [] and report["no_trade"].startswith("NO TRADE")
    cmr = {s["instrument"]: s for s in report["strategies"]
           if s["strategy_id"] == "channel_mean_reversion"}
    assert cmr["US:SPY"]["out_of_sample"]["oos_trades"] == 12
