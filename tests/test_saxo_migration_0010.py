"""Disposable SQLite checks for 0010: legacy-book refusal, rollback protection, runtime parity."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from sidedeck.domain.sim_accounting import SimAccountingError
from sidedeck.infrastructure.saxo_sim_journal import SimJournalStore
from sim_gateway_fake import SyntheticGateway, reconcile
from sim_gateway_fake import open_books as open_verified_books

AT = datetime(2026, 10, 20, 9, tzinfo=timezone.utc)
NEW_TABLES = {"saxo_sim_account_openings", "saxo_sim_freeze_releases"}


def _config(url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    return config


def _schema(url: str) -> tuple[set[str], set[str]]:
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        run_columns = {c["name"] for c in inspector.get_columns("saxo_sim_reconciliation_runs")}
        return set(inspector.get_table_names()), run_columns
    finally:
        engine.dispose()


def test_0010_round_trip_and_runtime_parity(tmp_path: Path) -> None:
    path = tmp_path / "evidence.db"
    url = f"sqlite:///{path}"
    config = _config(url)
    command.upgrade(config, "head")
    tables, columns = _schema(url)
    assert NEW_TABLES <= tables and {"evidence_id", "journal_sha256", "observed_at"} <= columns
    command.downgrade(config, "0009_saxo_sim_books")
    tables, columns = _schema(url)
    assert not NEW_TABLES & tables and "evidence_id" not in columns
    with pytest.raises(SimAccountingError, match="predates migration 0010"):
        SimJournalStore(str(path))                       # runtime refuses the older schema
    command.upgrade(config, "head")
    store = open_verified_books(str(path), AT)
    report = reconcile(store, SyntheticGateway(), AT.replace(minute=5))
    assert report.status == "MATCHED"
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM saxo_sim_reconciliation_runs "
                          "WHERE evidence_id IS NOT NULL").fetchone() == (1,)


def test_0010_downgrade_refuses_while_evidence_history_exists(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    config = _config(f"sqlite:///{path}")
    command.upgrade(config, "head")
    open_verified_books(str(path), AT)
    with pytest.raises(Exception, match="refusing to drop history"):
        command.downgrade(config, "0009_saxo_sim_books")
    assert NEW_TABLES <= _schema(f"sqlite:///{path}")[0]


def test_0010_refuses_books_opened_without_verified_evidence(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    url = f"sqlite:///{path}"
    config = _config(url)
    command.upgrade(config, "0009_saxo_sim_books")
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO saxo_sim_books (book_id, strategy_id, account_id, account_currency, "
                   "opened_at, status) VALUES ('saxo-sim:tradingagents', 'tradingagents', 'acct', "
                   "'EUR', '2026-10-20T09:00:00+00:00', 'OPEN')")
    with pytest.raises(Exception, match="without verified opening evidence"):
        command.upgrade(config, "head")
    assert not NEW_TABLES & _schema(url)[0]
