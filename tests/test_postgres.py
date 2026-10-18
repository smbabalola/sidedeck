import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from sidedeck.domain.accounting import Ledger, fill_event, opening_event
from sidedeck.domain.contracts import EventType
from sidedeck.infrastructure.database import IdempotencyConflict, create_database, load_events, save_events


POSTGRES_URL = os.environ.get("SIDEDECK_TEST_POSTGRES_URL")


def config_for(url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


@pytest.mark.skipif(POSTGRES_URL is None, reason="disposable PostgreSQL URL not provisioned")
def test_populated_postgres_migration_persistence_and_rollback() -> None:
    assert POSTGRES_URL is not None
    at = datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc)
    later = at + timedelta(minutes=1)
    opening = Ledger()
    opening.append(opening_event("tradingagents", at))
    legacy = opening.events[0]
    engine = create_database(POSTGRES_URL)
    command.upgrade(config_for(POSTGRES_URL), "0001_initial")
    legacy_payload = json.loads(legacy.model_dump_json())
    legacy_payload.pop("operation_id")
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO journal_events (event_id, portfolio_id, idempotency_key, occurred_at, payload) "
            "VALUES (:event_id, :portfolio_id, :idempotency_key, :occurred_at, :payload)"
        ), {
            "event_id": str(legacy.event_id), "portfolio_id": legacy.portfolio_id,
            "idempotency_key": legacy.idempotency_key, "occurred_at": legacy.occurred_at,
            "payload": json.dumps(legacy_payload),
        })
    command.upgrade(config_for(POSTGRES_URL), "head")

    restored = load_events(engine)
    assert restored[0].event_id == legacy.event_id
    save_events(engine, [restored[0].model_copy(update={"event_id": uuid4()})])
    buy = fill_event("tradingagents", "buy-after-migration", EventType.BUY_FILL, "US:AAPL", Decimal("1"), Decimal("100"), later)
    save_events(engine, [buy])
    replay = Ledger()
    for event in load_events(engine):
        replay.append(event)
    assert replay.replay("tradingagents").cash == Decimal("900")

    conflicting = buy.model_copy(update={"event_id": uuid4(), "price": Decimal("101")})
    additional = fill_event("tradingagents", "rollback-check", EventType.BUY_FILL, "US:AAPL", Decimal("1"), Decimal("99"), later)
    with pytest.raises(IdempotencyConflict):
        save_events(engine, [conflicting, additional])
    assert {event.idempotency_key for event in load_events(engine)} == {"opening-capital", "buy-after-migration"}

    command.downgrade(config_for(POSTGRES_URL), "base")
    command.upgrade(config_for(POSTGRES_URL), "head")
    assert {event.idempotency_key for event in load_events(engine)} == {"opening-capital", "buy-after-migration"}
    engine.dispose()
