"""Add durable sequence ordering and idempotency uniqueness."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_harden_journal"
down_revision: Union[str, Sequence[str], None] = "0001_initial"
branch_labels = None
depends_on = None


def _copy_table(source: str, target: str, include_sequence: bool) -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            f"SELECT event_id, portfolio_id, idempotency_key, occurred_at, payload "
            f"FROM {source} ORDER BY occurred_at, event_id"
        )
    ).mappings().all()
    for sequence, row in enumerate(rows, start=1):
        values = {
            "event_id": row["event_id"],
            "portfolio_id": row["portfolio_id"],
            "idempotency_key": row["idempotency_key"],
            "occurred_at": row["occurred_at"],
            "payload": row["payload"],
        }
        if include_sequence:
            values["journal_sequence"] = sequence
        bind.execute(sa.text(
            f"INSERT INTO {target} ({', '.join(values)}) "
            f"VALUES ({', '.join(':' + key for key in values)})"
        ), values)


def upgrade() -> None:
    op.create_table(
        "journal_events_v2",
        sa.Column("journal_sequence", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("portfolio_id", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
    )
    _copy_table("journal_events", "journal_events_v2", include_sequence=True)
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


def downgrade() -> None:
    op.create_table(
        "journal_events_v1",
        sa.Column("event_id", sa.String(length=36), primary_key=True),
        sa.Column("portfolio_id", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
    )
    _copy_table("journal_events", "journal_events_v1", include_sequence=False)
    op.drop_table("journal_events")
    op.rename_table("journal_events_v1", "journal_events")
    op.create_index("ix_journal_events_portfolio_id", "journal_events", ["portfolio_id"])
    op.create_index("ix_journal_events_idempotency_key", "journal_events", ["idempotency_key"])
