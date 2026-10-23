from __future__ import annotations

import socket
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from sidedeck.application.sd092_uk_scanner import UK_SCORING, UkScanError, run_uk_scan
from sidedeck.application.sd096_uk_acceptance import (
    CUTOFF,
    FIXTURE_BASIS,
    SCAN_NOW,
    TRADE_AT,
    UkFixture,
    build_uk_fixture,
    fixture_isin,
    run_fixture_scan,
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_: Any, **__: Any) -> None:
        raise AssertionError("network access attempted in an offline UK test")
    monkeypatch.setattr(socket.socket, "connect", refuse)


@pytest.fixture(scope="module")
def fixture() -> UkFixture:
    return build_uk_fixture()


def test_fixture_scan_identity_units_and_exclusions(fixture: UkFixture) -> None:
    result = run_fixture_scan(fixture)
    excluded = dict(result.excluded)
    assert excluded[f"UK:{fixture_isin(9)}"] == "UNKNOWN_OR_AMBIGUOUS_UNIT:'gbp'"
    assert excluded[f"UK:{fixture_isin(10)}"].startswith("SUSPECTED_UNIT_FLIP")
    assert result.report is not None
    assert dict(result.report.excluded)[f"UK:{fixture_isin(11)}"] == "STALE"
    assert result.universe == 12 and len(result.report.features) == 9
    for row in result.identities:
        raw = fixture.series[row.canonical_id].bars[-1].close
        assert Decimal(row.last_close_gbp) == raw / Decimal(row.divisor)
        assert row.data_basis == FIXTURE_BASIS and row.provenance and row.retrieved_at
        assert row.isin and row.tidm and row.quote_unit in ("GBX", "GBP")
    gbx = [r for r in result.identities if r.quote_unit == "GBX"]
    assert gbx and all(r.divisor == "100" for r in gbx)


def test_tracks_rankings_and_correct_abstention(fixture: UkFixture) -> None:
    result = run_fixture_scan(fixture)
    assert set(result.shortlists) == {"DAY", "SWING", "POSITION"}
    assert result.shortlists["DAY"].candidates == ()
    assert "SPREAD_UNAVAILABLE" in {r for _, r in result.shortlists["DAY"].filtered}
    ranks = [c.rank for c in result.shortlists["SWING"].candidates]
    assert ranks == list(range(1, len(ranks) + 1)) and ranks
    assert all(c.components for c in result.shortlists["SWING"].candidates)
    assert not any(d.status == "ELIGIBLE" for d in result.decisions)
    assert {d.execution_permission for d in result.decisions} == {
        "NOT_GRANTED_BY_DECISION_ENGINE"}
    assert all(s.track == "SWING" and s.source_kind == "DAY_TRADER_METHOD"
               for s in result.signals)
    assert len({s.signal_id for s in result.signals}) == len(result.signals)  # no duplicates
    assert result.acceptance == "ABSTAIN_NO_GENUINE_DATA_FIXTURE_RUN"
    summary = result.summary()
    assert summary["calendar"] == "XLON" and summary["price_unit"] == "GBP"


def test_fixture_cannot_be_scanned_as_real_data(fixture: UkFixture) -> None:
    result = run_uk_scan(fixture.registry, fixture.series, CUTOFF, SCAN_NOW,
                         data_basis="REAL_DATA")
    assert {r for _, r in result.excluded} == {"DATA_BASIS_MISMATCH"}
    assert result.report is None and result.acceptance == "ABSTAIN_INSUFFICIENT_GENUINE_DATA"


def test_cutoff_must_be_completed_lse_session(fixture: UkFixture) -> None:
    with pytest.raises(UkScanError, match="not closed"):
        run_uk_scan(fixture.registry, fixture.series, CUTOFF,
                    datetime(2026, 10, 22, 12, tzinfo=UTC), data_basis=FIXTURE_BASIS)
    with pytest.raises(UkScanError, match="not an LSE session"):
        run_uk_scan(fixture.registry, fixture.series, date(2026, 8, 31), SCAN_NOW,
                    data_basis=FIXTURE_BASIS)
    with pytest.raises(UkScanError, match="data basis"):
        run_uk_scan(fixture.registry, fixture.series, CUTOFF, SCAN_NOW, data_basis="LIVE")


def test_fresh_quotes_enable_spreads_and_stale_quotes_are_excluded(fixture: UkFixture) -> None:
    now = TRADE_AT
    quotes = dict(fixture.quotes)
    stale_cid = f"UK:{fixture_isin(2)}"
    quotes[stale_cid] = replace(quotes[stale_cid], quoted_at=now - timedelta(hours=1))
    result = run_uk_scan(fixture.registry, fixture.series, CUTOFF, now,
                         data_basis=FIXTURE_BASIS, quotes=quotes)
    assert dict(result.excluded)[stale_cid] == "QUOTE_STALE_QUOTE"
    assert result.spreads_bps and all(Decimal(0) < v < Decimal(15)
                                      for v in result.spreads_bps.values())
    assert stale_cid not in result.spreads_bps


def test_uk_thresholds_are_in_pounds() -> None:
    assert UK_SCORING["SWING"].min_price == Decimal("0.20")
    assert UK_SCORING["DAY"].max_spread_bps == Decimal("15")
