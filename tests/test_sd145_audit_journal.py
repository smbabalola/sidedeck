from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import sqlite3

import pytest

from sidedeck.application.sd063_autonomous_demo_policy import GENESIS
from sidedeck.application.sd074_external_anchor import WriteOnceDirectoryAnchor
from sidedeck.application.sd145_audit_journal import AuditJournal, AuditJournalError

NOW = datetime(2026, 10, 27, 12, tzinfo=UTC)
KEY = b"audit-device-test-key-32-bytes-long!"


class FailingAnchor:
    def __init__(self, wrapped):
        self.wrapped, self.fail = wrapped, False

    def history(self, ledger_id):
        if self.fail:
            raise OSError("offline")
        return self.wrapped.history(ledger_id)

    def append(self, checkpoint):
        if self.fail:
            raise OSError("offline")
        return self.wrapped.append(checkpoint)


def test_audit_events_anchor_policy_grant_reservation_reconcile_and_revocation(tmp_path):
    anchor = WriteOnceDirectoryAnchor(tmp_path / "remote")
    journal = AuditJournal(tmp_path / "audit.sqlite", stream_id="demo-controller",
                           anchor=anchor, device_key=KEY)
    journal.initialize(NOW)
    types = ("POLICY", "GRANT", "GRANT_USE", "ORDER_RESERVATION", "SEND",
             "RECONCILIATION", "REVOCATION")
    for index, kind in enumerate(types, 1):
        record = journal.append(kind, entity_id=f"entity-{index}",
                                payload={"digest": f"{index:064x}"},
                                at=NOW + timedelta(seconds=index))
        assert record.sequence == index
    assert journal.verify()[0] == len(types)
    assert [r.event_type for r in journal.records()] == list(types)
    journal.close()

    restarted = AuditJournal(tmp_path / "audit.sqlite", stream_id="demo-controller",
                             anchor=anchor, device_key=KEY)
    assert restarted.verify()[0] == len(types)
    restarted.close()


def test_external_head_detects_local_tampering_and_rollback(tmp_path):
    anchor = WriteOnceDirectoryAnchor(tmp_path / "remote")
    path = tmp_path / "audit.sqlite"
    journal = AuditJournal(path, stream_id="controller", anchor=anchor, device_key=KEY)
    journal.initialize(NOW)
    journal.append("POLICY", entity_id="p1", payload={"limit": 10}, at=NOW)
    journal.close()
    db = sqlite3.connect(path)
    db.execute("UPDATE audit_records SET payload='{}' WHERE sequence=1")
    db.commit()
    db.close()
    reopened = AuditJournal(path, stream_id="controller", anchor=anchor, device_key=KEY)
    with pytest.raises(AuditJournalError, match="modified"):
        reopened.verify()
    reopened.close()

    rollback_path = tmp_path / "rollback.sqlite"
    original = AuditJournal(rollback_path, stream_id="rollback", anchor=anchor,
                           device_key=KEY)
    original.initialize(NOW)
    original.append("GRANT", entity_id="g", payload={"scope": "one"}, at=NOW)
    original.close()
    db = sqlite3.connect(rollback_path)
    db.execute("DELETE FROM audit_records")
    db.commit()
    db.close()
    rolled_back = AuditJournal(rollback_path, stream_id="rollback", anchor=anchor,
                              device_key=KEY)
    with pytest.raises(AuditJournalError, match="rolled back"):
        rolled_back.verify()
    rolled_back.close()


def test_anchor_outage_rolls_back_local_event_and_fails_closed(tmp_path):
    wrapped = WriteOnceDirectoryAnchor(tmp_path / "remote")
    anchor = FailingAnchor(wrapped)
    journal = AuditJournal(tmp_path / "audit.sqlite", stream_id="outage", anchor=anchor,
                           device_key=KEY)
    journal.initialize(NOW)
    anchor.fail = True
    with pytest.raises(AuditJournalError, match="anchor"):
        journal.append("ORDER_RESERVATION", entity_id="o1", payload={"units": "1"}, at=NOW)
    anchor.fail = False
    assert journal.verify() == (0, GENESIS)
    journal.close()


def test_audit_rejects_secret_and_account_fields_before_persistence(tmp_path):
    journal = AuditJournal(tmp_path / "audit.sqlite", stream_id="privacy",
                           anchor=WriteOnceDirectoryAnchor(tmp_path / "remote"),
                           device_key=KEY)
    journal.initialize(NOW)
    for payload in ({"api_key": "redacted"}, {"nested": [{"account_id": "redacted"}]}):
        with pytest.raises(AuditJournalError, match="credential/account"):
            journal.append("GRANT", entity_id="g1", payload=payload, at=NOW)
    assert journal.verify() == (0, GENESIS)
    journal.close()


def test_two_writers_serialize_against_sqlite_and_remote_compare_append(tmp_path):
    path = tmp_path / "audit.sqlite"
    remote = WriteOnceDirectoryAnchor(tmp_path / "remote")
    first = AuditJournal(path, stream_id="concurrent", anchor=remote, device_key=KEY)
    first.initialize(NOW)

    def write(index):
        journal = AuditJournal(path, stream_id="concurrent", anchor=remote, device_key=KEY)
        try:
            return journal.append("GRANT_USE", entity_id=f"g{index}",
                                 payload={"counter": index},
                                 at=NOW + timedelta(seconds=index))
        finally:
            journal.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(write, range(1, 21)))
    assert sorted(r.sequence for r in records) == list(range(1, 21))
    assert first.verify()[0] == 20
    first.close()
