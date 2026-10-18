"""Repair existing 0002 sequence state and refuse ambiguous legacy journals."""
import json
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_finalize_persistence_gate"
down_revision: Union[str, Sequence[str], None] = "0002_harden_journal"
branch_labels = None
depends_on = None


def _reset_postgres_sequence() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text(
            "SELECT setval(pg_get_serial_sequence('journal_events', 'journal_sequence'), "
            "COALESCE((SELECT MAX(journal_sequence) FROM journal_events), 0) + 1, false)"
        ))


def upgrade() -> None:
    bind = op.get_bind()
    rows = list(bind.execute(sa.text(
        "SELECT journal_sequence, event_id, portfolio_id, occurred_at, payload "
        "FROM journal_events ORDER BY journal_sequence"
    )).mappings())
    seen: set[tuple[str, object]] = set()
    for row in rows:
        key = (row["portfolio_id"], row["occurred_at"])
        if key in seen:
            raise RuntimeError(
                "0003 refuses a journal with ambiguous identical-timestamp events; "
                "validated reconstruction is required before retrying"
            )
        seen.add(key)
        payload = json.loads(row["payload"])
        changed = False
        if "event_id" in payload:
            payload.pop("event_id")
            changed = True
        if "operation_id" not in payload:
            payload["operation_id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"sidedeck:event:{row['event_id']}"))
            changed = True
        if changed:
            bind.execute(
                sa.text("UPDATE journal_events SET payload = :payload WHERE journal_sequence = :sequence"),
                {"payload": json.dumps(payload, separators=(",", ":"), sort_keys=True), "sequence": row["journal_sequence"]},
            )
    _reset_postgres_sequence()


def downgrade() -> None:
    pass
