from __future__ import annotations

from datetime import datetime
import json
from typing import Iterable

from sqlalchemy import DateTime, Engine, Integer, String, Text, UniqueConstraint, create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from sidedeck.domain.accounting import SIM_EVENT_PREFIX
from sidedeck.domain.contracts import IdempotencyConflict, LedgerEvent


class Base(DeclarativeBase):
    pass


class JournalEventRecord(Base):
    __tablename__ = "journal_events"
    __table_args__ = (UniqueConstraint("portfolio_id", "idempotency_key", name="uq_journal_portfolio_idempotency"),)
    journal_sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    portfolio_id: Mapped[str] = mapped_column(String(100), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)


class PersistenceConflict(RuntimeError):
    """A generated event UUID was reused for different immutable content."""


def create_database(url: str) -> Engine:
    return create_engine(url, future=True)


def create_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def _save_events_once(engine: Engine, pending: list[LedgerEvent]) -> None:
    with Session(engine) as session, session.begin():
        for event in pending:
            if event.idempotency_key.startswith(SIM_EVENT_PREFIX):
                raise ValueError("Saxo SIM executions belong to the SIM books, not research journals")
            payload = event.canonical()
            existing_by_key = session.scalar(
                select(JournalEventRecord).where(
                    JournalEventRecord.portfolio_id == event.portfolio_id,
                    JournalEventRecord.idempotency_key == event.idempotency_key,
                )
            )
            if existing_by_key is not None:
                if existing_by_key.payload != payload:
                    raise IdempotencyConflict(
                        f"idempotency key conflict: {event.portfolio_id}/{event.idempotency_key}"
                    )
                continue
            existing_by_id = session.scalar(
                select(JournalEventRecord).where(
                    JournalEventRecord.event_id == str(event.event_id)
                )
            )
            if existing_by_id is not None:
                if existing_by_id.payload != payload:
                    raise PersistenceConflict(f"event UUID conflict: {event.event_id}")
                continue
            session.add(
                JournalEventRecord(
                    event_id=str(event.event_id),
                    portfolio_id=event.portfolio_id,
                    idempotency_key=event.idempotency_key,
                    occurred_at=event.occurred_at,
                    payload=payload,
                )
            )
            session.flush()


def save_events(engine: Engine, events: Iterable[LedgerEvent]) -> None:
    pending = list(events)
    last_error: IntegrityError | None = None
    for _attempt in range(3):
        try:
            _save_events_once(engine, pending)
            return
        except IntegrityError as exc:
            # The entire batch transaction has rolled back. Retry the whole
            # batch so colliding retries are resolved while noncolliding events
            # are not silently dropped.
            last_error = exc
    assert last_error is not None
    raise last_error


def load_events(engine: Engine) -> list[LedgerEvent]:
    with Session(engine) as session:
        rows = session.scalars(select(JournalEventRecord).order_by(JournalEventRecord.journal_sequence)).all()
        events: list[LedgerEvent] = []
        for row in rows:
            payload = json.loads(row.payload)
            payload["event_id"] = row.event_id
            events.append(LedgerEvent.model_validate(payload))
        return events
