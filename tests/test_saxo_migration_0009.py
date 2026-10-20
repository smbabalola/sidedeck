"""Disposable SQLite checks for 0009: refusals, rollback protection, runtime parity."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from sidedeck.application.saxo_execution_pipeline import SaxoExecutionPipeline
from sidedeck.infrastructure.saxo_sim_journal import SimJournalStore

AT = datetime(2026, 10, 20, 9, tzinfo=timezone.utc)


def _config(url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    return config


def _tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_0009_round_trip_and_runtime_parity(tmp_path: Path) -> None:
    path = tmp_path / "sim.db"
    url = f"sqlite:///{path}"
    config = _config(url)
    command.upgrade(config, "head")
    assert {"saxo_sim_books", "saxo_sim_journal", "saxo_sim_reconciliation_runs"} <= _tables(url)
    command.downgrade(config, "0008_operator_approval_binding")
    assert "saxo_sim_journal" not in _tables(url)
    command.upgrade(config, "head")
    # Runtime code works on the Alembic-managed schema.
    SimJournalStore(str(path)).open_books(account_id="acct", opened_at=AT, approval_ref="owner")
    assert SaxoExecutionPipeline(str(path)).ledger.replay("saxo-sim:tradingagents").cash_eur == 1000


def test_0009_downgrade_refuses_while_sim_history_exists(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    url = f"sqlite:///{path}"
    config = _config(url)
    command.upgrade(config, "head")
    SimJournalStore(str(path)).open_books(account_id="acct", opened_at=AT, approval_ref="owner")
    with pytest.raises(Exception, match="refusing to drop history"):
        command.downgrade(config, "0008_operator_approval_binding")
    assert "saxo_sim_journal" in _tables(url)


@pytest.mark.parametrize("seed, message", [
    ("INSERT INTO saxo_execution_recovery (execution_id, order_key, portfolio_id, event_payload, "
     "event_sha256, status, broker_order_id, fill_status) VALUES "
     "('x', 'sofi-1', 'tradingagents', '{}', 'h', 'POSTED', 'b', 'FinalFill')",
     "legacy Saxo fill"),
    ("INSERT INTO journal_events (event_id, portfolio_id, idempotency_key, occurred_at, payload) "
     "VALUES ('00000000-0000-0000-0000-000000000001', 'tradingagents', 'saxo:fill-1', "
     "'2026-10-19 14:00:00', '{}')",
     "research journal_events"),
])
def test_0009_refuses_when_sim_fills_reached_research_ledgers(tmp_path: Path, seed, message) -> None:
    path = tmp_path / "legacy.db"
    url = f"sqlite:///{path}"
    config = _config(url)
    command.upgrade(config, "0008_operator_approval_binding")
    with sqlite3.connect(path) as db:
        db.execute(seed)
    with pytest.raises(Exception, match=message):
        command.upgrade(config, "head")
    assert "saxo_sim_journal" not in _tables(url)
