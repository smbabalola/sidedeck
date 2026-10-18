from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from sidedeck.agents.contracts import AgentProposalEnvelope, AgentRunRecord
from sidedeck.infrastructure.database import AgentRunAuditRecord, DecisionAuditRecord


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class AuditStore(Protocol):
    def append(self, record: AgentRunRecord, envelope: AgentProposalEnvelope) -> None: ...


class InMemoryAuditStore:
    def __init__(self) -> None:
        self.records: list[AgentRunRecord] = []
        self.envelopes: dict[UUID, AgentProposalEnvelope] = {}

    def append(self, record: AgentRunRecord, envelope: AgentProposalEnvelope) -> None:
        if any(existing.run_id == record.run_id for existing in self.records):
            raise ValueError("run_id is immutable and cannot be reused")
        self.records.append(record)
        self.envelopes[record.run_id] = envelope


class SqlAuditStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def append(self, record: AgentRunRecord, envelope: AgentProposalEnvelope) -> None:
        with Session(self.engine) as session, session.begin():
            if session.get(AgentRunAuditRecord, str(record.run_id)) is not None:
                raise ValueError("run_id is immutable and cannot be reused")
            session.add(
                AgentRunAuditRecord(
                    run_id=str(record.run_id),
                    experiment_id=record.experiment_id,
                    portfolio_id=record.portfolio_id,
                    adapter_id=record.adapter_id,
                    request_hash=record.request_hash,
                    output_hash=record.output_hash,
                    accepted=record.validation.accepted,
                    validation_payload=record.validation.model_dump_json(),
                    decision_ids=json.dumps([str(value) for value in record.decision_ids]),
                    sanitized_output=record.sanitized_output,
                    started_at=record.started_at,
                    finished_at=record.finished_at,
                )
            )
            for decision_id, intent in zip(record.decision_ids, envelope.proposals, strict=True):
                session.add(
                    DecisionAuditRecord(
                        decision_id=str(decision_id),
                        run_id=str(record.run_id),
                        portfolio_id=record.portfolio_id,
                        adapter_id=record.adapter_id,
                        intent_payload=intent.model_dump_json(),
                        created_at=record.finished_at,
                    )
                )

    def load_runs(self) -> list[AgentRunRecord]:
        with Session(self.engine) as session:
            rows = session.scalars(select(AgentRunAuditRecord).order_by(AgentRunAuditRecord.started_at)).all()
            return [
                AgentRunRecord(
                    run_id=UUID(row.run_id),
                    experiment_id=row.experiment_id,
                    portfolio_id=row.portfolio_id,
                    adapter_id=row.adapter_id,
                    request_hash=row.request_hash,
                    output_hash=row.output_hash,
                    validation=json.loads(row.validation_payload),
                    decision_ids=tuple(UUID(value) for value in json.loads(row.decision_ids)),
                    started_at=_utc(row.started_at),
                    finished_at=_utc(row.finished_at),
                    sanitized_output=row.sanitized_output,
                )
                for row in rows
            ]
