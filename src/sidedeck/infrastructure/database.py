from __future__ import annotations

from datetime import datetime
from typing import Iterable

from sqlalchemy import DateTime, Engine, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from sidedeck.domain.contracts import LedgerEvent


class Base(DeclarativeBase):
    pass


class JournalEventRecord(Base):
    __tablename__ = "journal_events"
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(String(100), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)


def create_database(url: str) -> Engine:
    return create_engine(url, future=True)


def create_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def save_events(engine: Engine, events: Iterable[LedgerEvent]) -> None:
    with Session(engine) as session:
        for event in events:
            if session.get(JournalEventRecord, str(event.event_id)) is None:
                session.add(
                    JournalEventRecord(
                        event_id=str(event.event_id),
                        portfolio_id=event.portfolio_id,
                        idempotency_key=event.idempotency_key,
                        occurred_at=event.occurred_at,
                        payload=event.canonical(),
                    )
                )
        session.commit()


def load_events(engine: Engine) -> list[LedgerEvent]:
    with Session(engine) as session:
        rows = session.scalars(select(JournalEventRecord).order_by(JournalEventRecord.occurred_at)).all()
        return [LedgerEvent.model_validate_json(row.payload) for row in rows]
