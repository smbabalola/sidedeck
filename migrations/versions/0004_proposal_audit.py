"""Add durable proposal audit storage.

Revision ID: 0004_proposal_audit
Revises: 0003_finalize_persistence_gate
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0004_proposal_audit"
down_revision: Union[str, Sequence[str], None] = "0003_finalize_persistence_gate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "proposal_audit",
        sa.Column("audit_id", sa.String(36), primary_key=True),
        sa.Column("portfolio_id", sa.String(100), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.UniqueConstraint("portfolio_id", "idempotency_key", name="uq_proposal_audit_key"),
    )
    op.create_index("ix_proposal_audit_portfolio_id", "proposal_audit", ["portfolio_id"])


def downgrade() -> None:
    op.drop_index("ix_proposal_audit_portfolio_id", table_name="proposal_audit")
    op.drop_table("proposal_audit")
