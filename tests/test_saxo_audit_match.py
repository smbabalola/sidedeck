import pytest
from sidedeck.application.saxo_audit_match import (
    match_order_activity, match_unique_activity, note_broker_order_reference,
)
from sidedeck.application.saxo_order_lifecycle import (
    create_lifecycle, advance_lifecycle, lifecycle_state, LifecycleConflict,
)


def test_account_and_reference_and_broker_id_required():
    record = {"AccountId": "22866064", "ExternalReference": "agent-1", "OrderId": "S123"}
    assert match_order_activity(record, account_id="22866064",
                                external_reference="agent-1").broker_order_id == "S123"
    assert match_order_activity(record, account_id="other", external_reference="agent-1") is None
    assert match_order_activity(record, account_id="22866064",
                                external_reference="other") is None
    assert match_order_activity({**record, "OrderId": None},
                                account_id="22866064", external_reference="agent-1") is None


def test_ambiguous_and_incomplete_audit_rejected():
    record = {"AccountId": "22866064", "ExternalReference": "agent-1", "OrderId": "S123"}
    for response in ({"Data": [record, record]},
                     {"Data": [record], "__next": "next"},
                     {"Data": [], "__count": 3}):
        with pytest.raises(ValueError):
            match_unique_activity(response, account_id="22866064",
                                  external_reference="agent-1")


def test_broker_order_id_can_be_attached_but_not_filled(tmp_path):
    path = str(tmp_path / "journal.sqlite")
    create_lifecycle(path, "agent-1")
    advance_lifecycle(path, "agent-1", "SUBMITTING")
    match = match_unique_activity(
        {"Data": [{"AccountId": "22866064", "ExternalReference": "agent-1",
                   "OrderId": "S123"}]},
        account_id="22866064", external_reference="agent-1")
    assert match is not None
    assert note_broker_order_reference(path, order_key="agent-1", match=match)
    assert lifecycle_state(path, "agent-1") == ("ACKNOWLEDGED", "S123", 2)
    with pytest.raises(LifecycleConflict):
        note_broker_order_reference(path, order_key="agent-1", match=match)
