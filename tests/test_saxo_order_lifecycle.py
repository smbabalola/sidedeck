import pytest

from sidedeck.application.saxo_order_lifecycle import (
    LifecycleConflict, advance_lifecycle, create_lifecycle, lifecycle_state,
)


def test_persistent_unique_order_and_unknown_requires_reconciliation(tmp_path):
    path = tmp_path / "saxo-journal.sqlite"
    assert create_lifecycle(path, "agent-001")
    assert not create_lifecycle(path, "agent-001")
    assert advance_lifecycle(path, "agent-001", "SUBMITTING") == 1
    assert advance_lifecycle(path, "agent-001", "UNKNOWN") == 2
    with pytest.raises(LifecycleConflict, match="broker evidence"):
        advance_lifecycle(path, "agent-001", "ACKNOWLEDGED", broker_order_id="saxo-1")
    assert advance_lifecycle(path, "agent-001", "ACKNOWLEDGED",
                             broker_order_id="saxo-1", broker_evidence=True) == 3
    assert advance_lifecycle(path, "agent-001", "FILLED",
                             broker_order_id="saxo-1", broker_evidence=True) == 4
    assert lifecycle_state(path, "agent-001") == ("FILLED", "saxo-1", 4)
    with pytest.raises(LifecycleConflict):
        advance_lifecycle(path, "agent-001", "SUBMITTING")


def test_no_double_broker_order_id(tmp_path):
    path = tmp_path / "saxo-journal.sqlite"
    for key in ("one", "two"):
        create_lifecycle(path, key)
        advance_lifecycle(path, key, "SUBMITTING")
    advance_lifecycle(path, "one", "ACKNOWLEDGED",
                      broker_order_id="saxo-1", broker_evidence=True)
    with pytest.raises(LifecycleConflict):
        advance_lifecycle(path, "two", "ACKNOWLEDGED",
                          broker_order_id="saxo-1", broker_evidence=True)
    assert lifecycle_state(path, "two") == ("SUBMITTING", None, 1)


def test_fill_without_broker_id_is_blocked(tmp_path):
    path = tmp_path / "saxo-journal.sqlite"
    create_lifecycle(path, "one")
    advance_lifecycle(path, "one", "SUBMITTING")
    with pytest.raises(LifecycleConflict):
        advance_lifecycle(path, "one", "ACKNOWLEDGED", broker_evidence=True)
