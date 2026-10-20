"""eToro DEMO baseline and strategy attribution tables (read-only adapter).

Downgrade refuses while a captured baseline or any attribution exists, so the
record of which Demo positions pre-date SideDeck is never silently dropped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_etoro_demo_books"
down_revision: Union[str, Sequence[str], None] = "0004_proposal_audit"
branch_labels = None
depends_on = None


class EtoroDemoMigrationRefused(RuntimeError):
    pass


def upgrade() -> None:
    op.create_table(
        "etoro_demo_baseline_capture",
        sa.Column("capture_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("captured_at", sa.String(40), nullable=False),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("position_count", sa.Integer(), nullable=False),
        sa.CheckConstraint("capture_id = 1", name="ck_etoro_demo_single_baseline"),
    )
    op.create_table(
        "etoro_demo_baseline",
        sa.Column("position_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=True),
        sa.Column("is_buy", sa.Integer(), nullable=False),
        sa.Column("units", sa.String(50), nullable=False),
        sa.Column("opened_at", sa.String(40), nullable=False),
    )
    op.create_table(
        "etoro_demo_order_attribution",
        sa.Column("order_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("book_id", sa.String(64), nullable=False),
        sa.Column("recorded_at", sa.String(40), nullable=False),
        sa.CheckConstraint("book_id IN ('etoro-demo:tradingagents','etoro-demo:ai-trading')",
                           name="ck_etoro_demo_attribution_book"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    rows = sum(bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
               for table in ("etoro_demo_baseline_capture", "etoro_demo_order_attribution"))
    if rows:
        raise EtoroDemoMigrationRefused(
            f"{rows} eToro Demo baseline/attribution record(s) exist; refusing to drop history")
    op.drop_table("etoro_demo_order_attribution")
    op.drop_table("etoro_demo_baseline")
    op.drop_table("etoro_demo_baseline_capture")
