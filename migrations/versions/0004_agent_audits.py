"""Add append-only proposal run and decision audit records."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_agent_audits"
down_revision: Union[str, Sequence[str], None] = "0003_finalize_persistence_gate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_run_audits",
        sa.Column("run_id", sa.String(length=36), primary_key=True),
        sa.Column("experiment_id", sa.String(length=200), nullable=False),
        sa.Column("portfolio_id", sa.String(length=100), nullable=False),
        sa.Column("adapter_id", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("output_hash", sa.String(length=64), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("validation_payload", sa.Text(), nullable=False),
        sa.Column("decision_ids", sa.Text(), nullable=False),
        sa.Column("sanitized_output", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "decision_audits",
        sa.Column("decision_id", sa.String(length=36), primary_key=True),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("portfolio_id", sa.String(length=100), nullable=False),
        sa.Column("adapter_id", sa.String(length=200), nullable=False),
        sa.Column("intent_payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_decision_audits_run_id", "decision_audits", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_decision_audits_run_id", table_name="decision_audits")
    op.drop_table("decision_audits")
    op.drop_table("agent_run_audits")
