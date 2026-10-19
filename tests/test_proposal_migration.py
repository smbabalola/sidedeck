from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from sidedeck.infrastructure.proposal_audit import record_proposal, load_proposal_audit
from test_proposals import make_case
from datetime import datetime, timezone


def test_migration_roundtrip_and_persistent_proposal(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_engine(url)
    assert "proposal_audit" in inspect(engine).get_table_names()
    _, _, intent = make_case()
    record_proposal(engine, intent, key="case-1", accepted=True,
                    reason="proposal_only", created_at=datetime.now(timezone.utc))
    engine.dispose()
    reopened = create_engine(url)
    assert len(load_proposal_audit(reopened, "tradingagents")) == 1
    reopened.dispose()
    command.downgrade(config, "0003_finalize_persistence_gate")
    assert "proposal_audit" not in inspect(create_engine(url)).get_table_names()
    command.upgrade(config, "head")
    assert "proposal_audit" in inspect(create_engine(url)).get_table_names()
