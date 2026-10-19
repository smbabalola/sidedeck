from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy import create_engine

from sidedeck.infrastructure.proposal_audit import (
    create_audit_schema, load_proposal_audit, record_proposal,
)
from test_proposals import make_case


def test_parallel_retries_preserve_single_audit_record(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'race.db'}", connect_args={"timeout": 10})
    create_audit_schema(engine)
    _, _, intent = make_case()
    created = datetime(2026, 10, 19, tzinfo=timezone.utc)

    def write(_index):
        return record_proposal(
            engine, intent, key="same-request", accepted=True,
            reason="proposal_only", created_at=created,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = list(executor.map(write, range(2)))
    assert ids[0] == ids[1]
    assert len(load_proposal_audit(engine, "tradingagents")) == 1
