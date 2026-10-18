from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
import json
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from sidedeck.application.foundation import initialise_two_portfolios
from sidedeck.domain.accounting import Ledger, fill_event
from sidedeck.domain.contracts import EventType, ExperimentManifest
from sidedeck.infrastructure.database import IdempotencyConflict, create_database, load_events, save_events


def alembic_config(database_url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def configured_database(tmp_path, revision="head"):
    database_url = f"sqlite:///{tmp_path / 'sidedeck.sqlite3'}"
    command.upgrade(alembic_config(database_url), revision)
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


def test_populated_legacy_migration_preserves_order_and_allows_immediate_append(tmp_path) -> None:
    database_url, engine = configured_database(tmp_path, "0001_initial")
    at = datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc)
    opening = initialise_two_portfolios(manifest(at), at).events[0]
    legacy_payload = json.loads(opening.model_dump_json())
    legacy_payload.pop("operation_id")
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO journal_events (event_id, portfolio_id, idempotency_key, occurred_at, payload) "
            "VALUES (:event_id, :portfolio_id, :idempotency_key, :occurred_at, :payload)"
        ), {
            "event_id": str(opening.event_id), "portfolio_id": opening.portfolio_id,
            "idempotency_key": opening.idempotency_key, "occurred_at": opening.occurred_at,
            "payload": json.dumps(legacy_payload),
        })
    command.upgrade(alembic_config(database_url), "head")
    restored = load_events(engine)
    assert restored[0].event_id == opening.event_id
    save_events(engine, [restored[0].model_copy(update={"event_id": uuid4()})])
    buy = fill_event("tradingagents", "buy-after-migration", EventType.BUY_FILL, "US:AAPL", Decimal("1"), Decimal("100"), at)
    save_events(engine, [buy])
    assert [event.idempotency_key for event in load_events(engine)] == ["opening-capital", "buy-after-migration"]


def test_legacy_identical_timestamp_order_fails_safely(tmp_path) -> None:
    database_url, engine = configured_database(tmp_path, "0001_initial")
    at = datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc)
    ledger = initialise_two_portfolios(manifest(at), at)
    first = ledger.events[0]
    second = fill_event("tradingagents", "same-time-buy", EventType.BUY_FILL, "US:AAPL", Decimal("1"), Decimal("100"), at)
    with engine.begin() as connection:
        for event in (first, second):
            connection.execute(text(
                "INSERT INTO journal_events (event_id, portfolio_id, idempotency_key, occurred_at, payload) "
                "VALUES (:event_id, :portfolio_id, :idempotency_key, :occurred_at, :payload)"
            ), {
                "event_id": str(event.event_id), "portfolio_id": event.portfolio_id,
                "idempotency_key": event.idempotency_key, "occurred_at": event.occurred_at,
                "payload": event.canonical(),
            })
    with pytest.raises(RuntimeError, match="ambiguous"):
        command.upgrade(alembic_config(database_url), "head")


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


def test_concurrent_colliding_and_noncolliding_batch_is_atomic(tmp_path) -> None:
    database_url, engine = configured_database(tmp_path)
    at = datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc)
    opening = initialise_two_portfolios(manifest(at), at).events[0]
    buy_a = fill_event("tradingagents", "buy-a", EventType.BUY_FILL, "US:AAPL", Decimal("1"), Decimal("100"), at)
    buy_b = fill_event("tradingagents", "buy-b", EventType.BUY_FILL, "US:AAPL", Decimal("1"), Decimal("101"), at)

    def write_batch(event):
        save_events(create_database(database_url), [opening, event])

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(write_batch, (buy_a, buy_b)))
    assert {event.idempotency_key for event in load_events(engine)} == {"opening-capital", "buy-a", "buy-b"}


def test_identical_timestamps_use_durable_insert_sequence(tmp_path) -> None:
    _, engine = configured_database(tmp_path)
    at = datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc)
    ledger = initialise_two_portfolios(manifest(at), at)
    ledger.append(fill_event("tradingagents", "buy", EventType.BUY_FILL, "US:AAPL", Decimal("1"), Decimal("100"), at))
    save_events(engine, ledger.events)
    restored = load_events(engine)
    assert [event.idempotency_key for event in restored] == ["opening-capital", "opening-capital", "buy"]
