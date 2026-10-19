"""Versioned, credential-free P5 research model settings.

Model identifiers are free-form provider API identifiers: no hard-coded model
catalogue. Configuration does not imply a provider/upstream supports a model.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_PROVIDERS = frozenset({"openai", "anthropic", "google", "openrouter", "ollama"})
_PORTFOLIOS = frozenset({"tradingagents", "ai-trading"})
_ALLOWED_ROLES = frozenset({"default", "analyst", "researcher", "trader", "risk", "manager"})
_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:/+-]{0,127}$")


@dataclass(frozen=True)
class ModelChoice:
    provider: str
    model: str

    def __post_init__(self) -> None:
        if self.provider not in _PROVIDERS:
            raise ValueError("unrecognized AI provider")
        if not _ID.fullmatch(self.model):
            raise ValueError("invalid model identifier")


@dataclass(frozen=True)
class PortfolioModels:
    portfolio_id: str
    default: ModelChoice
    roles: dict[str, ModelChoice]

    def __post_init__(self) -> None:
        if self.portfolio_id not in _PORTFOLIOS:
            raise ValueError("unknown portfolio")
        if any(role not in _ALLOWED_ROLES - {"default"} for role in self.roles):
            raise ValueError("unknown agent role")

    def select(self, role: str) -> ModelChoice:
        if role not in _ALLOWED_ROLES:
            raise ValueError("unknown agent role")
        return self.roles.get(role, self.default)


@dataclass(frozen=True)
class AgentModelSettings:
    revision: str
    portfolios: dict[str, PortfolioModels]
    fingerprint: str


def load_model_settings(path: str | Path) -> AgentModelSettings:
    source = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(source, dict) or set(source) != {"revision", "portfolios"}:
        raise ValueError("invalid model settings root")
    revision = source["revision"]
    if not isinstance(revision, str) or not _ID.fullmatch(revision):
        raise ValueError("invalid configuration revision")
    portfolios = source["portfolios"]
    if not isinstance(portfolios, dict) or set(portfolios) != _PORTFOLIOS:
        raise ValueError("both portfolio model configurations required")
    parsed: dict[str, PortfolioModels] = {}
    for portfolio_id, definition in portfolios.items():
        if not isinstance(definition, dict) or set(definition) != {"default", "roles"}:
            raise ValueError("invalid portfolio configuration")
        default = _choice(definition["default"])
        roles = definition["roles"]
        if not isinstance(roles, dict):
            raise ValueError("invalid role overrides")
        parsed[portfolio_id] = PortfolioModels(
            portfolio_id, default, {role: _choice(choice) for role, choice in roles.items()},
        )
    canonical = json.dumps(source, sort_keys=True, separators=(",", ":"))
    return AgentModelSettings(
        revision=revision, portfolios=parsed,
        fingerprint=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


def _choice(raw: Any) -> ModelChoice:
    if not isinstance(raw, dict) or set(raw) != {"provider", "model"}:
        raise ValueError("invalid model configuration")
    if not isinstance(raw["provider"], str) or not isinstance(raw["model"], str):
        raise ValueError("model provider and ID must be strings")
    return ModelChoice(raw["provider"], raw["model"])


def model_environment(choice: ModelChoice) -> dict[str, str]:
    """Return non-secret research model routing parameters for an upstream bridge."""
    return {"SIDEDECK_AI_PROVIDER": choice.provider, "SIDEDECK_AI_MODEL": choice.model}
