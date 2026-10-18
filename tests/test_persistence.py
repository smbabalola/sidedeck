from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config

from sidedeck.application.foundation import initialise_two_portfolios
from sidedeck.domain.accounting import Ledger, fill_event
from sidedeck.domain.contracts import EventType, ExperimentManifest
from sidedeck.infrastructure.database import IdempotencyConflict, create_database, load_events, save_events


def configured_database(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'sidedeck.sqlite3'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    return database_url, create_database(database_url)


def manifest(at: datetime) -> ExperimentManifest:
    return ExperimentManifest(
        experiment_id="EXP-001", configuration_revision="r1", created_at=at,
        instruments=("US:AAPL",), data_policy="fixture",
    )


def test_sqlite_migration_and_save_reload_replay(tmp_path) -> None:
    _, engine = configured_database(tmp_path)
    at = datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc)
    ledger = initialise_two_portfolios(manifest(at), at)
    save_events(engine, ledger.events)
    restored = load_events(engine)
    assert len(restored) == 2
    assert {event.portfolio_id for event in restored} == {"tradingagents", "ai-trading"}
    replayed = Ledger()
    for event in restored:
        replayed.append(event)
    assert replayed.rebuild()["tradingagents"].cash == ledger.replay("tradingagents").cash


def test_alembic_upgrade_and_downgrade_round_trip(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'roundtrip.sqlite3'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")


def test_idempotent_retry_conflict_and_batch_rollback(tmp_path) -> None:
    _, engine = configured_database(tmp_path)
    at = datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc)
    ledger = initialise_two_portfolios(manifest(at), at)
    opening = ledger.events[0]
    save_events(engine, [opening])
    save_events(engine, [opening])
    conflicting = opening.model_copy(update={"event_id": opening.event_id, "metadata": {"changed": True}})
    with pytest.raises(IdempotencyConflict):
        save_events(engine, [conflicting])
    with pytest.raises(IdempotencyConflict):
        save_events(engine, [ledger.events[1], conflicting])
    assert len(load_events(engine)) == 1


def test_concurrent_same_key_is_single_effect(tmp_path) -> None:
    database_url, engine = configured_database(tmp_path)
    at = datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc)
    opening = initialise_two_portfolios(manifest(at), at).events[0]

    def write_once() -> None:
        save_events(create_database(database_url), [opening])

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: write_once(), range(2)))
    assert len(load_events(engine)) == 1


def test_identical_timestamps_use_durable_insert_sequence(tmp_path) -> None:
    _, engine = configured_database(tmp_path)
    at = datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc)
    ledger = initialise_two_portfolios(manifest(at), at)
    ledger.append(fill_event("tradingagents", "buy", EventType.BUY_FILL, "US:AAPL", Decimal("1"), Decimal("100"), at))
    save_events(engine, ledger.events)
    restored = load_events(engine)
    assert [event.idempotency_key for event in restored] == ["opening-capital", "opening-capital", "buy"]
