"""Add durable sequence ordering and idempotency uniqueness safely."""
import json
import uuid
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_harden_journal"
down_revision: Union[str, Sequence[str], None] = "0001_initial"
branch_labels = None
depends_on = None


def _legacy_rows() -> list[dict[str, Any]]:
    bind = op.get_bind()
    return list(bind.execute(sa.text(
        "SELECT event_id, portfolio_id, idempotency_key, occurred_at, payload "
        "FROM journal_events ORDER BY occurred_at, portfolio_id"
    )).mappings())


def _ensure_unambiguous(rows: list[dict[str, Any]]) -> None:
    seen: set[tuple[str, Any]] = set()
    for row in rows:
        key = (row["portfolio_id"], row["occurred_at"])
        if key in seen:
            raise RuntimeError(
                "0002 cannot migrate legacy events with ambiguous identical occurred_at in one portfolio: "
                f"{row['portfolio_id']} at {row['occurred_at']}; reconstruct a validated order first"
            )
        seen.add(key)


def _normalized_payload(row: dict[str, Any]) -> str:
    payload = json.loads(row["payload"])
    payload.pop("event_id", None)
    payload.setdefault("operation_id", str(uuid.uuid5(uuid.NAMESPACE_URL, f"sidedeck:event:{row['event_id']}")))
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _copy_table(rows: list[dict[str, Any]], target: str, include_sequence: bool) -> None:
    bind = op.get_bind()
    for sequence, row in enumerate(rows, start=1):
        values: dict[str, Any] = {
            "event_id": row["event_id"],
            "portfolio_id": row["portfolio_id"],
            "idempotency_key": row["idempotency_key"],
            "occurred_at": row["occurred_at"],
            "payload": _normalized_payload(row),
        }
        if include_sequence:
            values["journal_sequence"] = sequence
        bind.execute(sa.text(
            f"INSERT INTO {target} ({', '.join(values)}) "
            f"VALUES ({', '.join(':' + key for key in values)})"
        ), values)


def _reset_postgres_sequence() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text(
            "SELECT setval(pg_get_serial_sequence('journal_events', 'journal_sequence'), "
            "COALESCE((SELECT MAX(journal_sequence) FROM journal_events), 0) + 1, false)"
        ))


def upgrade() -> None:
    rows = _legacy_rows()
    _ensure_unambiguous(rows)
    op.create_table(
        "journal_events_v2",
        sa.Column("journal_sequence", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("portfolio_id", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
    )
    _copy_table(rows, "journal_events_v2", include_sequence=True)
    op.drop_table("journal_events")
    op.rename_table("journal_events_v2", "journal_events")
    op.create_index("ix_journal_events_event_id", "journal_events", ["event_id"], unique=True)
    op.create_index("ix_journal_events_portfolio_id", "journal_events", ["portfolio_id"])
    op.create_index("ix_journal_events_idempotency_key", "journal_events", ["idempotency_key"])
    op.create_index(
        "uq_journal_portfolio_idempotency",
        "journal_events",
        ["portfolio_id", "idempotency_key"],
        unique=True,
    )
    _reset_postgres_sequence()


def downgrade() -> None:
    op.create_table(
        "journal_events_v1",
        sa.Column("event_id", sa.String(length=36), primary_key=True),
        sa.Column("portfolio_id", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
    )
    bind = op.get_bind()
    rows = list(bind.execute(sa.text(
        "SELECT event_id, portfolio_id, idempotency_key, occurred_at, payload "
        "FROM journal_events ORDER BY journal_sequence"
    )).mappings())
    _copy_table(rows, "journal_events_v1", include_sequence=False)
    op.drop_table("journal_events")
    op.rename_table("journal_events_v1", "journal_events")
    op.create_index("ix_journal_events_portfolio_id", "journal_events", ["portfolio_id"])
    op.create_index("ix_journal_events_idempotency_key", "journal_events", ["idempotency_key"])
