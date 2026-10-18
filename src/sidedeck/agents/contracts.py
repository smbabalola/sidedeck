from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from sidedeck.domain.contracts import (
    AUTHORIZED_PORTFOLIOS,
    Contract,
    MarketSnapshot,
    TradeIntent,
    require_utc,
)
from sidedeck.domain.market import validate_snapshot


class EvidenceReference(Contract):
    reference: str = Field(min_length=1, max_length=500)
    as_of: datetime
    kind: Literal["fixture", "source_url", "local"]

    @field_validator("as_of")
    @classmethod
    def evidence_time(cls, value: datetime) -> datetime:
        return require_utc(value)


class MarketBundle(Contract):
    bundle_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    decision_cutoff_utc: datetime
    snapshots: tuple[MarketSnapshot, ...] = Field(min_length=1)
    allowed_instruments: tuple[str, ...] = Field(min_length=1)
    max_snapshot_age_seconds: int = Field(gt=0, le=604800)
    provenance: str = Field(min_length=1, max_length=500)

    @field_validator("decision_cutoff_utc")
    @classmethod
    def cutoff_time(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validated_point_in_time_bundle(self) -> Self:
        if len(set(self.allowed_instruments)) != len(self.allowed_instruments):
            raise ValueError("bundle instruments must be unique")
        if any(not instrument.startswith("US:") for instrument in self.allowed_instruments):
            raise ValueError("bundle instruments must be canonical IDs")
        seen: set[str] = set()
        for snapshot in self.snapshots:
            validate_snapshot(
                snapshot,
                self.decision_cutoff_utc,
                timedelta(seconds=self.max_snapshot_age_seconds),
            )
            if snapshot.instrument_id not in self.allowed_instruments:
                raise ValueError("snapshot is outside the bundle universe")
            if snapshot.instrument_id in seen:
                raise ValueError("bundle cannot contain duplicate instrument snapshots")
            seen.add(snapshot.instrument_id)
        if set(self.allowed_instruments) != seen:
            raise ValueError("bundle requires one eligible snapshot per allowed instrument")
        return self


class AgentRunRequest(Contract):
    run_id: UUID = Field(default_factory=uuid4)
    experiment_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    portfolio_id: str
    strategy_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    adapter_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    adapter_revision: str = Field(min_length=1, max_length=200)
    upstream_repository: str | None = Field(default=None, max_length=500)
    upstream_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    decision_cutoff_utc: datetime
    market_bundle_id: str
    allowed_instruments: tuple[str, ...] = Field(min_length=1)
    configuration_ref: str = Field(min_length=1, max_length=200)
    resource_budget: dict[str, int] = Field(default_factory=dict)
    cash_usd: Decimal
    holdings: dict[str, Decimal] = Field(default_factory=dict)
    deterministic_fixture: bool = True

    @field_validator("portfolio_id")
    @classmethod
    def authorized_portfolio(cls, value: str) -> str:
        if value not in AUTHORIZED_PORTFOLIOS:
            raise ValueError("run portfolio is not authorized")
        return value

    @field_validator("decision_cutoff_utc")
    @classmethod
    def request_time(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("cash_usd")
    @classmethod
    def cash_value(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < 0:
            raise ValueError("cash snapshot must be finite and nonnegative")
        return value

    @model_validator(mode="after")
    def safe_read_only_snapshot(self) -> Self:
        if not self.deterministic_fixture and self.adapter_id != "tradingagents.upstream":
            raise ValueError("only the approved TradingAgents smoke adapter may use a real model")
        if self.upstream_repository and not self.upstream_sha:
            raise ValueError("upstream repository requires a pinned SHA")
        if any(not key.startswith("US:") or value < 0 or not value.is_finite() for key, value in self.holdings.items()):
            raise ValueError("holdings must be finite, nonnegative canonical instrument quantities")
        if any(not key.startswith("US:") for key in self.allowed_instruments):
            raise ValueError("request instruments must be canonical IDs")
        return self


class AgentProposalEnvelope(Contract):
    schema_version: Literal["p2a.v1"] = "p2a.v1"
    run_id: UUID
    portfolio_id: str
    adapter_id: str
    generated_at: datetime
    data_as_of: datetime
    model_revision: str = Field(min_length=1, max_length=200)
    upstream_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    decision_inputs_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_version: str = Field(min_length=1, max_length=100)
    proposals: tuple[TradeIntent, ...] = ()
    evidence: tuple[EvidenceReference, ...] = ()
    result: Literal["PROPOSE", "HOLD", "FAILED"] = "PROPOSE"
    explanation: str = Field(min_length=1, max_length=2000)
    uncertainty: Decimal = Decimal("0")
    estimated_model_cost_usd: Decimal = Decimal("0")
    token_usage: int = Field(default=0, ge=0)
    runtime_ms: int = Field(default=0, ge=0)
    errors: tuple[str, ...] = ()

    @field_validator("generated_at", "data_as_of")
    @classmethod
    def envelope_times(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("uncertainty", "estimated_model_cost_usd")
    @classmethod
    def finite_nonnegative(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < 0:
            raise ValueError("numeric envelope values must be finite and nonnegative")
        return value

    @model_validator(mode="after")
    def result_shape(self) -> Self:
        if self.result == "HOLD" and self.proposals:
            raise ValueError("HOLD cannot contain proposals")
        if self.result == "FAILED" and not self.errors:
            raise ValueError("FAILED envelopes must explain errors")
        if self.result == "PROPOSE" and not self.proposals:
            raise ValueError("PROPOSE requires at least one proposal")
        return self


class ValidationResult(Contract):
    accepted: bool
    reason_codes: tuple[str, ...] = ()
    invalid_fields: tuple[str, ...] = ()
    provenance_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class AgentRunRecord(Contract):
    run_id: UUID
    experiment_id: str
    portfolio_id: str
    adapter_id: str
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation: ValidationResult
    decision_ids: tuple[UUID, ...] = ()
    started_at: datetime
    finished_at: datetime
    sanitized_output: str = Field(max_length=20000)

    @field_validator("started_at", "finished_at")
    @classmethod
    def record_times(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def finished_after_started(self) -> Self:
        if self.finished_at < self.started_at:
            raise ValueError("run finished before it started")
        return self
