from __future__ import annotations

from decimal import Decimal

import pytest

from sidedeck.application.sd029_operator_rehearsal import Approval, DryRunDesk, RehearsalError, SimulatedOrder, rehearsal_report


def _desk() -> DryRunDesk:
    desk = DryRunDesk()
    desk.propose(SimulatedOrder("intent", "client", "tradingagents", "US:SPY", Decimal("2")))
    return desk


def test_full_isolated_lineage_handles_partial_fill_and_replay() -> None:
    desk = _desk()
    desk.approve("client", Approval("approval", "owner-reviewer", "sig:offline", "US:SPY"))
    desk.submit_simulated("client")
    desk.acknowledge("client")
    desk.fill("client", Decimal("1"))
    assert desk.replay()["client"].state == "PARTIALLY_FILLED"
    desk.fill("client", Decimal("1"))
    desk.exit("client", Decimal("2"))
    assert desk.replay()["client"].state == "EXITED"
    assert [event["type"] for event in desk.events] == [
        "INTENT_PROPOSED", "HUMAN_APPROVED", "SUBMISSION_SIMULATED", "ACK_RECEIVED",
        "FILL_SIMULATED", "FILL_SIMULATED", "EXIT_SIMULATED",
    ]


def test_auto_approval_emergency_stop_and_idempotency_fail_closed() -> None:
    desk = _desk()
    with pytest.raises(RehearsalError, match="external"):
        desk.approve("client", Approval("approval", "system", "sig", "US:SPY"))
    desk.approve("client", Approval("approval", "owner-reviewer", "sig", "US:SPY"))
    desk.submit_simulated("client")
    desk.emergency_stop()
    with pytest.raises(RehearsalError, match="emergency"):
        desk.submit_simulated("client-2")
    with pytest.raises(RehearsalError, match="conflict"):
        desk.propose(SimulatedOrder("different", "client", "tradingagents", "US:QQQ", Decimal("2")))


def test_rollback_and_rehearsal_report_are_local_only() -> None:
    desk = _desk()
    desk.approve("client", Approval("approval", "owner-reviewer", "sig", "US:SPY"))
    desk.submit_simulated("client")
    desk.acknowledge("client")
    desk.fill("client", Decimal("2"))
    assert desk.rollback_last_fill("client").state == "ACKED"
    report = rehearsal_report()
    assert report == {"status": "REHEARSED", "final_state": "EXITED", "event_count": 7, "broker_execution": "DISABLED"}
