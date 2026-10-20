"""Disposable SQLite round trip for 0008 and runtime/schema compatibility."""
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from sidedeck.application.saxo_order_lifecycle import advance_lifecycle, create_lifecycle, lifecycle_state


def _config(url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    return config


def _columns(url: str, table: str) -> set[str]:
    engine = create_engine(url)
    try:
        return {column["name"] for column in inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


def test_0008_upgrade_downgrade_and_runtime_compatibility(tmp_path: Path) -> None:
    path = tmp_path / "p4.db"
    url = f"sqlite:///{path}"
    config = _config(url)
    command.upgrade(config, "head")
    assert {"quantity", "requested_by"} <= _columns(url, "saxo_execution_authorization")
    assert {"order_key", "status", "broker_order_id", "revision"} == _columns(url, "broker_lifecycle")
    long_signature = "-----BEGIN SSH SIGNATURE-----\n" + "A" * 400 + "\n-----END SSH SIGNATURE-----"
    expires = (datetime(2026, 10, 19, 14, tzinfo=timezone.utc) + timedelta(minutes=5)).isoformat()
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO saxo_execution_authorization (authorization_id, order_key, "
                   "account_id, portfolio_id, request_sha256, broker_payload_sha256, "
                   "risk_evidence_sha256, attestation, issued_by, expires_at, status, "
                   "broker_order_id, quantity, requested_by) VALUES "
                   "('a1','sofi-1','acct','tradingagents','r','b','k',?, 'operator', ?, "
                   "'ISSUED', NULL, '1', 'sidedeck-automation')", (long_signature, expires))
    # The runtime lifecycle code works on the Alembic-managed table.
    assert create_lifecycle(path, "sofi-1")
    advance_lifecycle(path, "sofi-1", "SUBMITTING")
    assert lifecycle_state(path, "sofi-1") == ("SUBMITTING", None, 1)
    command.downgrade(config, "0007_execution_account_binding")
    assert "broker_lifecycle" not in inspect(create_engine(url)).get_table_names()
    assert "requested_by" not in _columns(url, "saxo_execution_authorization")
    command.upgrade(config, "head")
    assert "broker_lifecycle" in inspect(create_engine(url)).get_table_names()
    command.downgrade(config, "base")
    command.upgrade(config, "head")
