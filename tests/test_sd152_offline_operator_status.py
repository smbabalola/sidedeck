from datetime import UTC, datetime
from types import SimpleNamespace

from sidedeck.application.sd152_offline_operator_status import (
    is_safe_operator_status_document,
    operator_status_document,
)


class GoodService:
    def health(self, *, now):
        return SimpleNamespace(report=lambda: {
            "schema": "sidedeck.sd152.offline-fence-health/1",
            "state": "IDLE", "alerts": [],
            "broker_route": "SIMULATED_LOCAL",
            "execution_release": "ETORO_DEMO_NOT_RELEASED",
        })

    def recovery_dossier(self, *, now):
        return {"uncertain_orders": [], "execution_release": "ETORO_DEMO_NOT_RELEASED"}

    def run_due(self, **kwargs):
        raise AssertionError("read-only status must not run cycles")


def test_operator_status_read_only_and_not_released():
    status = operator_status_document(GoodService(), now=datetime.now(UTC))
    assert status["status"] == "INFORMATIONAL"
    assert is_safe_operator_status_document(status)
    assert not status["safe_to_trade"]
    assert not status["automatic_get_allowed"]
    assert not status["automatic_post_allowed"]


def test_operator_status_outage_is_explicit_incident():
    class Broken:
        def health(self, *, now):
            raise RuntimeError("unavailable")

    report = operator_status_document(Broken(), now=datetime.now(UTC))
    assert report["status"] == "ACTION_REQUIRED"
    assert report["incidents"] == ["OPERATOR_EVIDENCE_UNAVAILABLE"]
    assert is_safe_operator_status_document(report)


def test_contract_rejects_forged_release_and_recovery():
    report = operator_status_document(GoodService(), now=datetime.now(UTC))
    for change in (
        {"execution_release": "RELEASED"},
        {"clear_halt_allowed": True},
        {"automatic_post_allowed": True},
        {"broker_account_verified": True},
        {"source": "ETORO_LIVE"},
    ):
        assert not is_safe_operator_status_document({**report, **change})
