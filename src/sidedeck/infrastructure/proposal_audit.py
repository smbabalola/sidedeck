"""Append-only proposal audit store, isolated from journal and broker execution."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Engine, String, Text, UniqueConstraint, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from sidedeck.domain.contracts import TradeIntent


class AuditBase(DeclarativeBase):
    pass


class ProposalAuditRecord(AuditBase):
    __tablename__ = "proposal_audit"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "idempotency_key", name="uq_proposal_audit_key"),
    )

    audit_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)


class AuditConflict(ValueError):
    pass


def create_audit_schema(engine: Engine) -> None:
    """Test/early-stage schema setup; production requires an Alembic migration."""
    AuditBase.metadata.create_all(engine)


def record_proposal(
    engine: Engine, intent: TradeIntent, *, key: str, accepted: bool, reason: str,
    created_at: datetime,
) -> UUID:
    if not key.strip() or not reason.strip():
        raise ValueError("audit key and decision reason are required")
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("audit time must be timezone-aware")
    from sidedeck.domain.contracts import AUTHORIZED_PORTFOLIOS
    if intent.portfolio_id not in AUTHORIZED_PORTFOLIOS:
        raise ValueError("unknown portfolio")
    payload = json.dumps(
        {"intent": intent.model_dump(mode="json"), "accepted": accepted, "reason": reason},
        sort_keys=True, separators=(",", ":"),
    )
    digest = sha256(payload.encode("utf-8")).hexdigest()
    with Session(engine) as session, session.begin():
        existing = session.scalar(select(ProposalAuditRecord).where(
            ProposalAuditRecord.portfolio_id == intent.portfolio_id,
            ProposalAuditRecord.idempotency_key == key,
        ))
        if existing is not None:
            if existing.digest != digest or existing.payload != payload:
                raise AuditConflict("proposal audit idempotency conflict")
            return UUID(existing.audit_id)
        audit_id = uuid4()
        session.add(ProposalAuditRecord(
            audit_id=str(audit_id), portfolio_id=intent.portfolio_id,
            idempotency_key=key, created_at=created_at.astimezone(timezone.utc),
            payload=payload, digest=digest,
        ))
        return audit_id


def load_proposal_audit(engine: Engine, portfolio_id: str) -> list[dict[str, object]]:
    from sidedeck.domain.contracts import AUTHORIZED_PORTFOLIOS
    if portfolio_id not in AUTHORIZED_PORTFOLIOS:
        raise ValueError("unknown portfolio")
    with Session(engine) as session:
        rows = session.scalars(select(ProposalAuditRecord).where(
            ProposalAuditRecord.portfolio_id == portfolio_id
        ).order_by(ProposalAuditRecord.created_at, ProposalAuditRecord.audit_id)).all()
        results: list[dict[str, object]] = []
        for record in rows:
            if sha256(record.payload.encode("utf-8")).hexdigest() != record.digest:
                raise AuditConflict("proposal audit payload integrity mismatch")
            results.append({
                "audit_id": record.audit_id, "idempotency_key": record.idempotency_key,
                "created_at": record.created_at.isoformat(),
                **json.loads(record.payload),
            })
        return results
