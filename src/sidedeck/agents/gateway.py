from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from .contracts import AgentProposalEnvelope, AgentRunRecord, AgentRunRequest, MarketBundle, ValidationResult
from .fixtures import FixtureWorker


class ProposalSchemaValidator:
    def validate(
        self,
        request: AgentRunRequest,
        bundle: MarketBundle,
        envelope: AgentProposalEnvelope,
    ) -> ValidationResult:
        failures: list[tuple[str, str]] = []
        if envelope.run_id != request.run_id:
            failures.append(("run_id", "RUN_MISMATCH"))
        if envelope.portfolio_id != request.portfolio_id:
            failures.append(("portfolio_id", "PORTFOLIO_MISMATCH"))
        if envelope.adapter_id != request.adapter_id:
            failures.append(("adapter_id", "ADAPTER_MISMATCH"))
        if envelope.model_revision != request.adapter_revision:
            failures.append(("model_revision", "REVISION_MISMATCH"))
        if bundle.bundle_id != request.market_bundle_id:
            failures.append(("market_bundle_id", "BUNDLE_MISMATCH"))
        if bundle.decision_cutoff_utc != request.decision_cutoff_utc:
            failures.append(("decision_cutoff_utc", "CUTOFF_MISMATCH"))
        if envelope.generated_at < request.decision_cutoff_utc:
            failures.append(("generated_at", "GENERATED_BEFORE_CUTOFF"))
        if envelope.data_as_of > request.decision_cutoff_utc:
            failures.append(("data_as_of", "LOOKAHEAD_DATA"))
        if envelope.result == "FAILED":
            failures.append(("result", "WORKER_FAILURE"))
        if envelope.upstream_sha != request.upstream_sha:
            failures.append(("upstream_sha", "PROVENANCE_MISMATCH"))
        if envelope.decision_inputs_hash != _hash_inputs(request, bundle):
            failures.append(("decision_inputs_hash", "INPUT_HASH_MISMATCH"))
        if not envelope.evidence and envelope.result != "HOLD":
            failures.append(("evidence", "MISSING_EVIDENCE"))
        if len({intent.instrument_id for intent in envelope.proposals}) != len(envelope.proposals):
            failures.append(("proposals", "DUPLICATE_INSTRUMENT"))
        allowed = set(request.allowed_instruments)
        bundle_instruments = {snapshot.instrument_id for snapshot in bundle.snapshots}
        if allowed != set(bundle.allowed_instruments) or allowed != bundle_instruments:
            failures.append(("allowed_instruments", "UNIVERSE_MISMATCH"))
        for index, intent in enumerate(envelope.proposals):
            if intent.experiment_id != request.experiment_id:
                failures.append((f"proposals[{index}].experiment_id", "EXPERIMENT_MISMATCH"))
            if intent.portfolio_id != request.portfolio_id:
                failures.append((f"proposals[{index}].portfolio_id", "PORTFOLIO_MISMATCH"))
            if intent.instrument_id not in allowed:
                failures.append((f"proposals[{index}].instrument_id", "UNKNOWN_INSTRUMENT"))
            if intent.decision_timestamp > request.decision_cutoff_utc:
                failures.append((f"proposals[{index}].decision_timestamp", "FUTURE_DECISION"))
            if intent.data_as_of > request.decision_cutoff_utc:
                failures.append((f"proposals[{index}].data_as_of", "LOOKAHEAD_DATA"))
        canonical = json.dumps(
            {"request": request.model_dump(mode="json"), "bundle": bundle.model_dump(mode="json")},
            sort_keys=True,
            separators=(",", ":"),
        )
        provenance_hash = hashlib.sha256(canonical.encode()).hexdigest()
        return ValidationResult(
            accepted=not failures,
            reason_codes=tuple(sorted({reason for _, reason in failures})),
            invalid_fields=tuple(field for field, _ in failures),
            provenance_hash=provenance_hash,
        )


def _hash_inputs(request: AgentRunRequest, bundle: MarketBundle) -> str:
    canonical = json.dumps(
        {"request": request.model_dump(mode="json"), "bundle": bundle.model_dump(mode="json")},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class AuditStore(Protocol):
    def append(self, record: AgentRunRecord, envelope: AgentProposalEnvelope) -> None: ...


class AgentRunCoordinator:
    def __init__(self, store: AuditStore, validator: ProposalSchemaValidator | None = None) -> None:
        self.store = store
        self.validator = validator or ProposalSchemaValidator()

    def run(self, request: AgentRunRequest, bundle: MarketBundle, worker: FixtureWorker) -> AgentRunRecord:
        record, _ = self.run_validated(request, bundle, worker)
        return record

    def run_validated(
        self, request: AgentRunRequest, bundle: MarketBundle, worker: FixtureWorker
    ) -> tuple[AgentRunRecord, AgentProposalEnvelope]:
        started = datetime.now(timezone.utc)
        envelope = worker.propose(request, bundle)
        result = self.validator.validate(request, bundle, envelope)
        output = json.dumps(envelope.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        request_json = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        decision_ids = tuple(uuid4() for _ in envelope.proposals) if result.accepted else ()
        record = AgentRunRecord(
            run_id=request.run_id,
            experiment_id=request.experiment_id,
            portfolio_id=request.portfolio_id,
            adapter_id=request.adapter_id,
            request_hash=hashlib.sha256(request_json.encode()).hexdigest(),
            output_hash=hashlib.sha256(output.encode()).hexdigest(),
            validation=result,
            decision_ids=decision_ids,
            started_at=started,
            finished_at=datetime.now(timezone.utc),
            sanitized_output=output,
        )
        self.store.append(record, envelope)
        return record, envelope
