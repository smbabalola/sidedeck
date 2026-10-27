from datetime import UTC, datetime

import pytest

from sidedeck.application.sd123_day_demo_integration import (
    admit_fixture_day_strategy, release_status, research_day_sample,
)

from test_sd122_etoro_intraday_bridge import _CUTOFF, _payload


def test_day_research_stays_research_only_and_keeps_independent_admission():
    result = research_day_sample(
        _payload(), instrument_id=1004, symbol="MSFT", cutoff=_CUTOFF,
        generated_at=datetime(2026, 10, 23, 13, 40, tzinfo=UTC),
    )
    assert result.signal is None
    assert result.status == "NO_SIGNAL"
    assert result.admission.status == "RESEARCH_ONLY"
    assert result.metadata["strategy_admission_eligible"] is False


def test_fixture_admission_requires_explicit_override_and_oos_floor():
    with pytest.raises(PermissionError, match="fixture_acceptance"):
        admit_fixture_day_strategy(evidence_ref="sd071://fixture", oos_trades=30,
                                   oos_validated=True)
    with pytest.raises(ValueError):
        admit_fixture_day_strategy(evidence_ref="sd071://fixture", oos_trades=29,
                                   oos_validated=True, fixture_acceptance=True)
    admission = admit_fixture_day_strategy(
        evidence_ref="sd071://fixture", oos_trades=30, oos_validated=True,
        fixture_acceptance=True,
    )
    assert admission.status == "ADMITTED"
    assert admission.track == "DAY"


def test_release_status_remains_fail_closed():
    status = release_status()
    assert status["broker_route"] == "ETORO_DEMO_NOT_RELEASED"
    assert status["etoro_real"] == "PERMANENTLY_EXCLUDED"
