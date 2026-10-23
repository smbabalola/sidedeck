from __future__ import annotations

from sidedeck.application.sd076_pipeline_demo import run_demo


def test_demo_is_labelled_synthetic_and_never_eligible_without_admission() -> None:
    summary = run_demo(count=30)
    assert summary["data_basis"] == "SYNTHETIC_FIXTURE"
    assert "not market coverage" in summary["warning"]
    assert summary["scan"]["scanned"] == 30 and summary["scan"]["excluded"] == {}
    # No spread data is supplied, so the DAY track refuses every candidate.
    assert summary["shortlists"]["DAY"]["quant"] == 0
    # Method-only signals without an admitted strategy can never be ELIGIBLE.
    assert "ELIGIBLE" not in summary["swing_decisions"]
    assert summary["execution_permission"] == "NOT_GRANTED_BY_DECISION_ENGINE"
    assert run_demo(count=30)["shortlists"] == summary["shortlists"]   # deterministic


def test_demo_streams_bars_so_peak_memory_does_not_scale_with_the_universe() -> None:
    import tracemalloc

    peaks = []
    for count in (50, 200):
        tracemalloc.start()
        run_demo(count=count)
        peaks.append(tracemalloc.get_traced_memory()[1])
        tracemalloc.stop()
    # Eager loading grows ~4x for 4x instruments; streaming keeps only per-instrument features.
    assert peaks[1] < peaks[0] * 2.5, peaks


def test_scanner_loads_each_instrument_once_and_keeps_no_bars() -> None:
    from datetime import date

    from sidedeck.application import sd076_pipeline_demo as demo
    from sidedeck.application.sd067_market_scanner import run_broad_scan

    days = demo.expected_regular_sessions(date(2025, 6, 2), demo.CUTOFF)
    calls: list[str] = []

    def loader(cid: str):
        calls.append(cid)
        return demo._synthetic_bars(int(cid[6:]), days)

    ids = [f"US:SYN{i:03d}" for i in range(40)]
    report = run_broad_scan(ids, loader, demo.CUTOFF, data_basis="SYNTHETIC_FIXTURE",
                            batch_size=7)
    assert sorted(calls) == ids and len(calls) == 40
    assert report.batches == 6 and report.bars_read == 40 * len(days)
