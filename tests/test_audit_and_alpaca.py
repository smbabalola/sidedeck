from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine

from sidedeck.infrastructure.alpaca_paper import AlpacaPaperBinding, submit_order
from sidedeck.infrastructure.proposal_audit import (
    AuditConflict, create_audit_schema, load_proposal_audit, record_proposal,
)
from test_proposals import make_case


def test_proposal_audit_is_durable_and_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'audit.db'}")
    create_audit_schema(engine)
    _, _, intent = make_case()
    at = datetime(2026, 10, 19, tzinfo=timezone.utc)
    first = record_proposal(engine, intent, key="intent-1", accepted=True,
                            reason="proposal_only", created_at=at)
    again = record_proposal(engine, intent, key="intent-1", accepted=True,
                            reason="proposal_only", created_at=at + timedelta(minutes=1))
    assert first == again
    engine.dispose()
    reopened = create_engine(f"sqlite:///{tmp_path / 'audit.db'}")
    records = load_proposal_audit(reopened, "tradingagents")
    assert len(records) == 1
    assert records[0]["accepted"] is True
    assert records[0]["intent"]["strategy_id"] == "test"


def test_proposal_audit_rejects_conflicting_retry(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'audit.db'}")
    create_audit_schema(engine)
    _, _, intent = make_case()
    at = datetime(2026, 10, 19, tzinfo=timezone.utc)
    record_proposal(engine, intent, key="same", accepted=True, reason="ok", created_at=at)
    with pytest.raises(AuditConflict):
        record_proposal(engine, intent, key="same", accepted=False,
                        reason="rejected", created_at=at)


def test_paper_binding_never_enables_network():
    binding = AlpacaPaperBinding()
    assert binding.api_key_env == "ALPACA_API_KEY2"
    assert not binding.enabled
    with pytest.raises(ValueError):
        AlpacaPaperBinding(base_url="https://api.alpaca.markets")
    with pytest.raises(ValueError):
        AlpacaPaperBinding(api_key_env="ALPACA_API_KEY")
    with pytest.raises(ValueError):
        AlpacaPaperBinding(enabled=True)
    with pytest.raises(PermissionError):
        submit_order()
