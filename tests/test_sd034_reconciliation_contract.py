from decimal import Decimal

from sidedeck.application.sd034_reconciliation_contract import (
    MockEvent, dormant_alpaca_read_proposal, reconcile_mock_events,
)


def test_mock_reconciliation_accepts_partial_full_exit_lineage():
    result = reconcile_mock_events((
        MockEvent(1, "intent-1", "ACK"), MockEvent(2, "intent-1", "PARTIAL_FILL", Decimal("1")),
        MockEvent(3, "intent-1", "FILL", Decimal("1")), MockEvent(4, "intent-1", "EXIT", Decimal("2")),
    ))
    assert result["status"] == "RECONCILED"
    assert result["broker_execution"] == "DISABLED"
    assert result["positions"] == [{"intent_id": "intent-1", "filled": "2", "exited": "2", "state": "EXITED"}]


def test_mock_reconciliation_detects_duplicates_missing_and_bad_exit():
    result = reconcile_mock_events((
        MockEvent(1, "intent-1", "ACK"), MockEvent(2, "intent-1", "FILL", Decimal("0")),
        MockEvent(4, "intent-1", "EXIT", Decimal("1")),
        MockEvent(4, "intent-1", "EXIT", Decimal("1")),
    ))
    assert result["status"] == "DISCREPANCY"
    assert "OUT_OF_ORDER_OR_MISSING_SEQUENCE" in result["discrepancies"]
    assert "DUPLICATE_SEQUENCE" in result["discrepancies"]
    assert "EXIT_EXCEEDS_FILL" in result["discrepancies"]


def test_owner_read_proposal_is_dormant_and_non_executing():
    proposal = dormant_alpaca_read_proposal()
    assert proposal["status"] == "DORMANT_OWNER_PROPOSAL"
    assert proposal["request_cap"] == 3
    assert proposal["execution_enabled"] is False
    assert proposal["orders"] == "DISABLED"
