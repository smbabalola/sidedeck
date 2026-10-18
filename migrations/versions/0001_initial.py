"""initial journal schema"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "journal_events",
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("portfolio_id", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_journal_events_portfolio_id", "journal_events", ["portfolio_id"])
    op.create_index("ix_journal_events_idempotency_key", "journal_events", ["idempotency_key"])


def downgrade() -> None:
    op.drop_index("ix_journal_events_idempotency_key", table_name="journal_events")
    op.drop_index("ix_journal_events_portfolio_id", table_name="journal_events")
    op.drop_table("journal_events")
