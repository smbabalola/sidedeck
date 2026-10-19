"""Add versioned Saxo recovery and authorization storage."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_execution_integrity"
down_revision: Union[str, Sequence[str], None] = "0004_proposal_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saxo_execution_recovery",
        sa.Column("execution_id", sa.String(200), primary_key=True),
        sa.Column("order_key", sa.String(100), nullable=False),
        sa.Column("portfolio_id", sa.String(100), nullable=False),
        sa.Column("event_payload", sa.Text(), nullable=False),
        sa.Column("event_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("broker_order_id", sa.String(128), nullable=False),
        sa.Column("fill_status", sa.String(20), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('PENDING','RECOVERING','POSTED')", name="ck_saxo_recovery_status"),
    )
    op.create_index("ix_saxo_recovery_order_key", "saxo_execution_recovery", ["order_key"])
    op.create_table(
        "saxo_execution_authorization",
        sa.Column("authorization_id", sa.String(200), primary_key=True),
        sa.Column("order_key", sa.String(100), nullable=False, unique=True),
        sa.Column("account_id", sa.String(100), nullable=False),
        sa.Column("portfolio_id", sa.String(100), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("broker_payload_sha256", sa.String(64), nullable=False),
        sa.Column("risk_evidence_sha256", sa.String(64), nullable=False),
        sa.Column("attestation", sa.String(128), nullable=False),
        sa.Column("issued_by", sa.String(200), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("broker_order_id", sa.String(128), nullable=True),
        sa.CheckConstraint("status IN ('ISSUED','CONSUMED','REJECTED','UNKNOWN')", name="ck_saxo_auth_status"),
    )


def downgrade() -> None:
    op.drop_table("saxo_execution_authorization")
    op.drop_index("ix_saxo_recovery_order_key", table_name="saxo_execution_recovery")
    op.drop_table("saxo_execution_recovery")
