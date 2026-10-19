"""Bind Saxo authorizations to quantity/requester and track broker lifecycle.

The attestation becomes Text because an OpenSSH signature is longer than the
previous 128-character column (PostgreSQL would reject it).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008_operator_approval_binding"
down_revision: Union[str, Sequence[str], None] = "0007_execution_account_binding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("saxo_execution_authorization") as batch:
        batch.alter_column("attestation", existing_type=sa.String(128), type_=sa.Text(),
                           existing_nullable=False)
        batch.add_column(sa.Column("quantity", sa.String(50), nullable=False,
                                   server_default="1"))
        batch.add_column(sa.Column("requested_by", sa.String(64), nullable=False,
                                   server_default=""))
    op.create_table(
        "broker_lifecycle",
        sa.Column("order_key", sa.String(100), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("broker_order_id", sa.String(128), nullable=True, unique=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('STAGED','SUBMITTING','UNKNOWN','ACKNOWLEDGED','PARTIAL',"
            "'FILLED','CANCELLED','REJECTED')", name="ck_broker_lifecycle_status"),
    )


def downgrade() -> None:
    op.drop_table("broker_lifecycle")
    with op.batch_alter_table("saxo_execution_authorization") as batch:
        batch.drop_column("requested_by")
        batch.drop_column("quantity")
        batch.alter_column("attestation", existing_type=sa.Text(), type_=sa.String(128),
                           existing_nullable=False)
