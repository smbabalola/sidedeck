"""Bind Saxo recovery rows to the verified account identity."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_execution_account_binding"
down_revision: Union[str, Sequence[str], None] = "0006_execution_quantity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("saxo_execution_recovery", sa.Column(
        "account_id", sa.String(100), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("saxo_execution_recovery", "account_id")
