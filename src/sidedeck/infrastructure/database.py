from __future__ import annotations

from datetime import datetime
from typing import Iterable

from sqlalchemy import DateTime, Engine, Integer, String, Text, UniqueConstraint, create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

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


def create_database(url: str) -> Engine:
    return create_engine(url, future=True)


def create_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def save_events(engine: Engine, events: Iterable[LedgerEvent]) -> None:
    pending = list(events)
    try:
        with Session(engine) as session, session.begin():
            for event in pending:
                payload = event.canonical()
                existing = session.scalar(
                    select(JournalEventRecord).where(
                        JournalEventRecord.portfolio_id == event.portfolio_id,
                        JournalEventRecord.idempotency_key == event.idempotency_key,
                    )
                )
                if existing is not None:
                    if existing.payload != payload:
                        raise IdempotencyConflict(
                            f"idempotency key conflict: {event.portfolio_id}/{event.idempotency_key}"
                        )
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
    except IntegrityError as exc:
        with Session(engine) as session:
            for event in pending:
                existing = session.scalar(
                    select(JournalEventRecord).where(
                        JournalEventRecord.portfolio_id == event.portfolio_id,
                        JournalEventRecord.idempotency_key == event.idempotency_key,
                    )
                )
                if existing is not None:
                    if existing.payload != event.canonical():
                        raise IdempotencyConflict(
                            f"idempotency key conflict: {event.portfolio_id}/{event.idempotency_key}"
                        ) from exc
                    return
        raise


def load_events(engine: Engine) -> list[LedgerEvent]:
    with Session(engine) as session:
        rows = session.scalars(select(JournalEventRecord).order_by(JournalEventRecord.journal_sequence)).all()
        return [LedgerEvent.model_validate_json(row.payload) for row in rows]
