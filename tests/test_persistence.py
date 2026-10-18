from datetime import datetime, timezone

from alembic import command
from alembic.config import Config

from sidedeck.application.foundation import initialise_two_portfolios
from sidedeck.domain.contracts import ExperimentManifest
from sidedeck.infrastructure.database import create_database, load_events, save_events


def test_sqlite_migration_and_save_reload_replay(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'sidedeck.sqlite3'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")

    engine = create_database(database_url)
    at = datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc)
    manifest = ExperimentManifest(
        experiment_id="EXP-001", configuration_revision="r1", created_at=at,
        instruments=("US:AAPL",), data_policy="fixture",
    )
    ledger = initialise_two_portfolios(manifest, at)
    save_events(engine, ledger.events)
    restored = load_events(engine)
    assert len(restored) == 2
    assert {event.portfolio_id for event in restored} == {"tradingagents", "ai-trading"}
