"""Separate Saxo SIM books, journal and reconciliation runs (ADR-003).

Upgrade refuses if a SIM fill may already have been booked into a research
portfolio (legacy ``saxo_execution_recovery`` rows or ``saxo:`` keys in
``journal_events``): that needs owner review, not a silent move.
Downgrade refuses while any SIM journal entry (allocation or fill) exists.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009_saxo_sim_books"
down_revision: Union[str, Sequence[str], None] = "0008_operator_approval_binding"
branch_labels = None
depends_on = None


class SimMigrationRefused(RuntimeError):
    pass


def upgrade() -> None:
    bind = op.get_bind()
    legacy = bind.execute(sa.text(
        "SELECT COUNT(*) FROM saxo_execution_recovery "
        "WHERE status IN ('PENDING','RECOVERING','POSTED')")).scalar_one()
    if legacy:
        raise SimMigrationRefused(
            f"{legacy} legacy Saxo fill row(s) posted to research ledgers; owner review required")
    research = bind.execute(sa.text(
        "SELECT COUNT(*) FROM journal_events WHERE idempotency_key LIKE 'saxo:%'")).scalar_one()
    if research:
        raise SimMigrationRefused(
            f"{research} Saxo event(s) found in research journal_events; owner review required")
    op.create_table(
        "saxo_sim_books",
        sa.Column("book_id", sa.String(64), primary_key=True),
        sa.Column("strategy_id", sa.String(64), nullable=True),
        sa.Column("account_id", sa.String(100), nullable=False),
        sa.Column("account_currency", sa.String(3), nullable=False),
        sa.Column("opened_at", sa.String(40), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("freeze_scope", sa.String(16), nullable=True),
        sa.Column("freeze_reason", sa.Text(), nullable=True),
        sa.Column("frozen_at", sa.String(40), nullable=True),
        sa.Column("released_by", sa.String(64), nullable=True),
        sa.UniqueConstraint("account_id", "strategy_id", name="uq_saxo_sim_book_strategy"),
        sa.CheckConstraint("status IN ('OPEN','FROZEN','CLOSED')", name="ck_saxo_sim_book_status"),
        sa.CheckConstraint("freeze_scope IS NULL OR freeze_scope IN ('BOOK','ACCOUNT')",
                           name="ck_saxo_sim_freeze_scope"),
    )
    op.create_table(
        "saxo_sim_journal",
        sa.Column("journal_sequence", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(36), nullable=False, unique=True),
        sa.Column("book_id", sa.String(64), sa.ForeignKey("saxo_sim_books.book_id"), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("order_key", sa.String(50), nullable=True),
        sa.Column("broker_execution_id", sa.String(200), nullable=True, unique=True),
        sa.Column("fill_status", sa.String(20), nullable=True),
        sa.Column("occurred_at", sa.String(40), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.UniqueConstraint("book_id", "idempotency_key", name="uq_saxo_sim_journal_book_key"),
        sa.CheckConstraint("event_type IN ('SIM_ALLOCATION','SIM_BUY_FILL','SIM_BASELINE')",
                           name="ck_saxo_sim_event_type"),
    )
    op.create_table(
        "saxo_sim_reconciliation_runs",
        sa.Column("run_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("checked_at", sa.String(40), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("freeze_scope", sa.String(16), nullable=False),
        sa.Column("frozen_books", sa.Text(), nullable=False),
        sa.Column("discrepancies", sa.Text(), nullable=False),
    )
    with op.batch_alter_table("saxo_execution_authorization") as batch:
        batch.add_column(sa.Column("book_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("fx_usd_per_eur", sa.String(50), nullable=True))
        batch.add_column(sa.Column("fx_provider", sa.String(100), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    entries = bind.execute(sa.text("SELECT COUNT(*) FROM saxo_sim_journal")).scalar_one()
    if entries:
        raise SimMigrationRefused(f"{entries} SIM journal entr(ies) exist; refusing to drop history")
    with op.batch_alter_table("saxo_execution_authorization") as batch:
        batch.drop_column("fx_provider")
        batch.drop_column("fx_usd_per_eur")
        batch.drop_column("book_id")
    op.drop_table("saxo_sim_reconciliation_runs")
    op.drop_table("saxo_sim_journal")
    op.drop_table("saxo_sim_books")
