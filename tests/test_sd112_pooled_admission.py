"""SD-112 pooled OOS admission proposal: method properties on labelled synthetic fixtures."""
from __future__ import annotations

import copy
from datetime import date
from pathlib import Path

import pytest

from sidedeck.application import sd071_decision_engine
from sidedeck.application import sd103_trading_pipeline as p
from sidedeck.application import sd112_pooled_admission as pa

DATA = Path(__file__).resolve().parents[1] / "data"
START, END = date(2022, 1, 3), date(2026, 12, 31)   # fixtures may reach past the cut-off


def _bundles(tickers=("SPY", "QQQ", "MSFT")):
    out = []
    for seed, t in enumerate(tickers, start=1):
        payload = p.synthetic_bundle(t, start=START, end=END, seed=seed)
        out.append((payload, p._sha(payload)))
    return out


@pytest.fixture(scope="module")
def report():
    return pa.proposal(_bundles(), basis=p.FIXTURE)


def test_report_is_proposal_only_and_never_admits(report):
    assert report["status"] == "PROPOSAL_ONLY"
    assert report["production_admission_gate"].startswith("UNCHANGED")
    assert all(s["verdict"] in pa.VERDICTS for s in report["strategies"])
    assert "ADMITTED" not in {s["verdict"] for s in report["strategies"]}
    assert sd071_decision_engine.MIN_OOS_TRADES_FLOOR == 30          # production gate untouched


def test_shared_chronological_segments_and_sealed_holdout(report):
    for s in report["strategies"]:
        train, oos = s["segments"]["TRAIN"], s["segments"]["OOS"]
        assert train[1] < oos[0]
        assert s["holdout"]["status"] == "SEALED" and len(s["holdout"]["commitment_sha256"]) == 64
        assert "HOLDOUT" not in s["segments"]
        assert oos[1] < pa.HOLDOUT_START.isoformat() <= s["holdout"]["starts"]


def test_no_trade_touches_another_segment():
    evidence, _ = pa._admit_all(_bundles(), p.FIXTURE)
    common = sorted(set.intersection(*(set(b.day for b in ev.bars) for ev in evidence.values())))
    seg = pa.segments(common)
    for cid, ev in evidence.items():
        trades, _ = pa.trades_for("channel_mean_reversion", ev.bars, seg, cid)
        for t in trades:
            lo, hi = seg[t.segment]
            assert lo <= t.entry_day <= t.exit_day <= hi


def test_effective_sample_never_exceeds_trades_or_clusters(report):
    for s in report["strategies"]:
        e = s["effective_sample_size"]
        assert e["value"] <= s["pooled_oos"]["trades"]
        assert e["value"] <= e["overlap_clusters"]


def test_identical_instruments_are_not_independent_evidence():
    payload = p.synthetic_bundle("SPY", start=START, end=END, seed=1)
    twin = copy.deepcopy(payload)
    twin.update(ticker="QQQ", instrument_id="US:QQQ", exchange="NASDAQ")
    duplicated = pa.proposal([(payload, p._sha(payload)), (twin, p._sha(twin))],
                             basis=p.FIXTURE, strategies=("channel_mean_reversion",))
    d = duplicated["strategies"][0]
    assert d["effective_sample_size"]["mean_pairwise_correlation"] > 0.99
    # twice the trades, but no more effective evidence than one copy provides
    assert d["effective_sample_size"]["value"] <= d["pooled_oos"]["trades"] / 2 + 1


def test_losing_instruments_stay_visible(report):
    for s in report["strategies"]:
        assert set(s["instruments"]) == set(report["instruments"])
        for row in s["instruments"].values():
            assert row["instrument_exclusion"] in ("NONE", "EXCLUDED_LOSES_ON_ITS_OWN")


def test_multiple_testing_adjustment_and_cost_stress_are_reported(report):
    for s in report["strategies"]:
        assert s["uncertainty"]["bonferroni_family"] == 3 * pa.PRIOR_LOOKS
        assert s["uncertainty"]["one_sided_level"] == pytest.approx(0.05 / (3 * pa.PRIOR_LOOKS))
        assert "stressed_2x_profit_factor" in s["costs"]
        assert set(s["regimes"]) == {"UPTREND", "DOWNTREND"}


def test_holdout_reveals_only_on_owner_instruction_and_only_once(tmp_path):
    bundles = _bundles()
    with pytest.raises(pa.PooledAdmissionError, match="explicit owner"):
        pa.reveal_holdout("channel_mean_reversion", bundles, marker_dir=tmp_path,
                          owner_unseal=False, basis=p.FIXTURE)
    first = pa.reveal_holdout("channel_mean_reversion", bundles, marker_dir=tmp_path,
                              owner_unseal=True, basis=p.FIXTURE)
    assert first["status"] == "REVEALED_ONCE"
    with pytest.raises(pa.PooledAdmissionError, match="already revealed"):
        pa.reveal_holdout("channel_mean_reversion", bundles, marker_dir=tmp_path,
                          owner_unseal=True, basis=p.FIXTURE)


def test_fixture_and_real_bases_never_mix():
    with pytest.raises(pa.PooledAdmissionError):
        pa.proposal(_bundles(), basis=p.REAL_DATA)       # fixtures refused as real data


def test_needs_two_instruments():
    with pytest.raises(pa.PooledAdmissionError):
        pa.proposal(_bundles(("SPY",)), basis=p.FIXTURE)


@pytest.mark.skipif(not (DATA / "sd021-spy-admitted.json").is_file(),
                    reason="ignored local SD-021 bundles are not present")
def test_genuine_three_instruments_propose_nothing():
    bundles = [p.load_bundle(DATA / f"sd021-{t}-admitted.json") for t in ("spy", "qqq", "msft")]
    result = pa.proposal(bundles)
    verdicts = {s["strategy"]: s["verdict"] for s in result["strategies"]}
    assert "PROPOSED_FOR_OWNER_REVIEW" not in verdicts.values()
    assert verdicts["channel_mean_reversion@1.0.0"] == "REJECTED"


def test_holdout_commitment_ignores_data_refreshes():
    a = pa.holdout_commitment("channel_mean_reversion")
    assert a == pa.holdout_commitment("channel_mean_reversion")
    assert a != pa.holdout_commitment("moving_average_trend")


def test_reveal_refused_without_enough_holdout_sessions_and_consumes_nothing(tmp_path):
    short = []
    for seed, t in enumerate(("SPY", "QQQ"), start=1):
        payload = p.synthetic_bundle(t, start=START, end=date(2026, 11, 6), seed=seed)
        short.append((payload, p._sha(payload)))
    with pytest.raises(pa.PooledAdmissionError, match="nothing consumed"):
        pa.reveal_holdout("channel_mean_reversion", short, marker_dir=tmp_path,
                          owner_unseal=True, basis=p.FIXTURE)
    assert not list(tmp_path.glob("holdout-revealed-*"))


def test_reveal_applies_the_pre_declared_pass_rule(tmp_path):
    out = pa.reveal_holdout("channel_mean_reversion", _bundles(), marker_dir=tmp_path,
                            owner_unseal=True, basis=p.FIXTURE)
    assert out["result"] in ("PASS", "FAIL") and out["pass_rule"] == pa.HOLDOUT_PASS


def test_missing_benchmark_or_uncovered_regime_is_insufficient_not_proposed():
    bundles = _bundles(("QQQ", "MSFT"))                 # no US:SPY benchmark
    result = pa.proposal(bundles, basis=p.FIXTURE, strategies=("channel_mean_reversion",))
    s = result["strategies"][0]
    assert "REGIME_BENCHMARK_UNAVAILABLE" in s["reasons"]
    assert s["verdict"] == "INSUFFICIENT_EVIDENCE"


def test_strategy_return_is_reported_next_to_the_benchmark(report):
    for s in report["strategies"]:
        b = s["benchmark"]
        assert "equal_weight_strategy_oos_return" in b and "strategy_mean_exposure" in b
        assert b["role"].startswith("CONTEXT_ONLY")
