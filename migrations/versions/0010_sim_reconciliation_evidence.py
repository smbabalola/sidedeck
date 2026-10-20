"""Bind Saxo SIM opening, reconciliation and freeze release to verified evidence.

Adds the verified opening record (account, scope fingerprint, opening EUR
cash and baseline positions), evidence/journal binding on every
reconciliation run (one run per evidence ID), and an append-only audit of
signed freeze releases.

Upgrade refuses if SIM books already exist: books opened under 0009 have no
verified opening evidence and need owner review rather than a silent backfill.
Downgrade refuses while any evidence-backed history exists.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010_sim_reconciliation_evidence"
down_revision: Union[str, Sequence[str], None] = "0009_saxo_sim_books"
branch_labels = None
depends_on = None


class SimMigrationRefused(RuntimeError):
    pass


def upgrade() -> None:
    bind = op.get_bind()
    books = bind.execute(sa.text("SELECT COUNT(*) FROM saxo_sim_books")).scalar_one()
    if books:
        raise SimMigrationRefused(
            f"{books} SIM book(s) were opened without verified opening evidence; owner review required")
    with op.batch_alter_table("saxo_sim_reconciliation_runs") as batch:
        batch.add_column(sa.Column("account_id", sa.String(100), nullable=True))
        batch.add_column(sa.Column("evidence_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("source", sa.String(64), nullable=True))
        batch.add_column(sa.Column("observed_at", sa.String(40), nullable=True))
        batch.add_column(sa.Column("journal_sha256", sa.String(64), nullable=True))
        batch.add_column(sa.Column("evidence_sha256", sa.String(64), nullable=True))
        batch.create_unique_constraint("uq_saxo_sim_run_evidence", ["evidence_id"])
    op.create_table(
        "saxo_sim_account_openings",
        sa.Column("account_id", sa.String(100), primary_key=True),
        sa.Column("scope_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_id", sa.String(64), nullable=False, unique=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.String(40), nullable=False),
        sa.Column("cash_balance_eur", sa.String(50), nullable=False),
        sa.Column("positions", sa.Text(), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("approval_ref", sa.String(200), nullable=False),
    )
    op.create_table(
        "saxo_sim_freeze_releases",
        sa.Column("release_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("released_at", sa.String(40), nullable=False),
        sa.Column("released_by", sa.String(64), nullable=False),
        sa.Column("report_id", sa.String(64), nullable=False),
        sa.Column("books", sa.Text(), nullable=False),
        sa.Column("attestation_sha256", sa.String(64), nullable=False),
    )


def downgrade() -> None:
    bind = op.get_bind()
    history = sum(bind.execute(sa.text(query)).scalar_one() for query in (
        "SELECT COUNT(*) FROM saxo_sim_account_openings",
        "SELECT COUNT(*) FROM saxo_sim_freeze_releases",
        "SELECT COUNT(*) FROM saxo_sim_reconciliation_runs WHERE evidence_id IS NOT NULL",
    ))
    if history:
        raise SimMigrationRefused(
            f"{history} evidence-backed SIM record(s) exist; refusing to drop history")
    op.drop_table("saxo_sim_freeze_releases")
    op.drop_table("saxo_sim_account_openings")
    with op.batch_alter_table("saxo_sim_reconciliation_runs") as batch:
        batch.drop_constraint("uq_saxo_sim_run_evidence", type_="unique")
        batch.drop_column("evidence_sha256")
        batch.drop_column("journal_sha256")
        batch.drop_column("observed_at")
        batch.drop_column("source")
        batch.drop_column("evidence_id")
        batch.drop_column("account_id")
