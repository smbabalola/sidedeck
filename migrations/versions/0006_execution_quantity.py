"""Add authorized quantity to Saxo recovery records."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_execution_quantity"
down_revision: Union[str, Sequence[str], None] = "0005_execution_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("saxo_execution_recovery", sa.Column(
        "authorized_quantity", sa.String(50), nullable=False, server_default="1"))


def downgrade() -> None:
    op.drop_column("saxo_execution_recovery", "authorized_quantity")
