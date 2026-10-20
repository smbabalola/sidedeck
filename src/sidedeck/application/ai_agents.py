"""Research-only AI agent runtime boundary.

External runtimes are supplied and installed separately. No broker credentials or
portfolio write access is passed to an upstream framework.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Protocol

from sidedeck.domain.contracts import Side, TradeIntent


class AgentUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentResult:
    upstream: str
    revision: str
    portfolio_id: str
    ticker: str
    decision: str
    rationale: str
    raw_summary: str
    upstream_version: str = ""
    instrument_id: str = ""
    market_cutoff: datetime | None = None
    decision_timestamp: datetime | None = None
    model_provider: str = ""
    model_id: str = ""
    configuration_fingerprint: str = ""
    evidence_references: tuple[str, ...] = ()
    abstained: bool = False
    unavailable: bool = False
    status: str = "RESEARCH_ONLY"


class AgentRunner(Protocol):
    def run(self, ticker: str, cutoff: datetime) -> AgentResult: ...


_BROKER_FRAGMENTS = ("SAXO_", "ALPACA_", "ETORO_", "BROKER_", "TRADING_")
_RESEARCH_VARS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY",
                  "FINANCIAL_DATASETS_API_KEY", "ALPHA_VANTAGE_API_KEY",
                  "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY")


def research_environment(source: Mapping[str, str]) -> dict[str, str]:
    """Allowlist only provider keys and essential process locale/path settings."""
    allowed = ("PATH", "SYSTEMROOT", "WINDIR", "HOME", "USERPROFILE", "TMP",
               "TEMP", "VIRTUAL_ENV", "PYTHONIOENCODING", "LANG")
    return {key: value for key, value in source.items()
            if key in allowed or (key in _RESEARCH_VARS
                                  and not key.startswith(_BROKER_FRAGMENTS))}


def parse_decision(value: str) -> str:
    text = value.strip().upper()
    if text not in ("BUY", "SELL", "HOLD"):
        raise ValueError("agent decision must be explicitly BUY, SELL or HOLD")
    return text


def normalize_intent(
    result: AgentResult, *, experiment_id: str, strategy_id: str,
    market_timestamp: datetime, decision_timestamp: datetime,
    proposed_shares: Decimal | None = None,
) -> TradeIntent:
    if result.portfolio_id not in ("tradingagents", "ai-trading"):
        raise ValueError("unknown portfolio")
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]*", result.ticker):
        raise ValueError("unsupported ticker")
    decision = parse_decision(result.decision)
    if decision != "HOLD" and (proposed_shares is None
                               or not proposed_shares.is_finite()
                               or proposed_shares <= 0):
        raise ValueError("BUY/SELL needs explicit operator-approved sizing")
    return TradeIntent(
        experiment_id=experiment_id, portfolio_id=result.portfolio_id,
        strategy_id=strategy_id, instrument_id="US:" + result.ticker,
        side=Side(decision), quantity=proposed_shares if decision != "HOLD" else None,
        rationale=result.rationale[:2000] or "No rationale supplied by upstream",
        model_revision=result.revision,
        decision_timestamp=decision_timestamp, data_as_of=market_timestamp,
    )


def _run(command: list[str], *, cwd: str | Path | None,
         timeout_seconds: int = 180) -> dict[str, Any]:
    if not 1 <= timeout_seconds <= 600:
        raise ValueError("invalid agent timeout")
    if not command or any(not isinstance(arg, str) or not arg for arg in command):
        raise ValueError("invalid agent command")
    try:
        completed = subprocess.run(
            command, cwd=cwd, env=research_environment(os.environ), capture_output=True,
            text=True, timeout=timeout_seconds, check=False, encoding="utf-8",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AgentUnavailable("upstream research runtime unavailable") from exc
    if completed.returncode != 0 or len(completed.stdout) > 1_000_000:
        raise AgentUnavailable("upstream research failed; inspect upstream locally")
    try:
        result = json.loads(completed.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        raise AgentUnavailable("upstream did not provide a JSON decision") from exc
    if not isinstance(result, dict):
        raise AgentUnavailable("unexpected upstream decision format")
    return result


@dataclass(frozen=True)
class ExternalJsonAgent:
    """Adapter for a separately installed research bridge that returns JSON.

    The bridge is responsible for calling the REAL upstream research workflow.
    Nothing in SideDeck fabricates a research result or accesses trading APIs.
    """

    upstream: str
    portfolio_id: str
    revision: str
    command: tuple[str, ...]
    cwd: str | None = None
    model_provider: str | None = None
    model_id: str | None = None

    def run(self, ticker: str, cutoff: datetime) -> AgentResult:
        if self.portfolio_id not in ("tradingagents", "ai-trading"):
            raise ValueError("unknown portfolio")
        if not re.fullmatch(r"[A-Z][A-Z0-9.-]*", ticker):
            raise ValueError("invalid ticker")
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError("cutoff must include timezone")
        model_args: list[str] = []
        if (self.model_provider is None) != (self.model_id is None):
            raise ValueError("provider/model must be supplied together")
        if self.model_provider is not None and self.model_id is not None:
            from sidedeck.application.p5_model_config import ModelChoice
            choice = ModelChoice(self.model_provider, self.model_id)
            model_args = ["--provider", choice.provider, "--model", choice.model]
        data = _run([*self.command, "--ticker", ticker, "--as-of",
                     cutoff.date().isoformat(), *model_args], cwd=self.cwd)
        if data.get("ticker") != ticker:
            raise AgentUnavailable("upstream ticker mismatch")
        decision = data.get("decision")
        rationale = data.get("rationale")
        if not isinstance(decision, str) or not isinstance(rationale, str):
            raise AgentUnavailable("upstream decision fields missing")
        status = data.get("status", "RESEARCH_ONLY")
        if status != "RESEARCH_ONLY":
            raise AgentUnavailable("upstream result is not research-only")
        instrument_id = data.get("instrument_id", "US:" + ticker)
        if instrument_id != "US:" + ticker:
            raise AgentUnavailable("upstream instrument mismatch")
        upstream_version = data.get("upstream_version", "")
        if upstream_version is not None and not isinstance(upstream_version, str):
            raise AgentUnavailable("invalid upstream version")
        references = data.get("evidence_references", ())
        if not isinstance(references, (list, tuple)) or any(
            not isinstance(item, str) or not item.strip() for item in references
        ):
            raise AgentUnavailable("invalid research evidence references")
        market_cutoff = cutoff
        raw_cutoff = data.get("market_cutoff")
        if raw_cutoff is not None:
            if not isinstance(raw_cutoff, str):
                raise AgentUnavailable("invalid market cutoff")
            try:
                market_cutoff = datetime.fromisoformat(raw_cutoff.replace("Z", "+00:00"))
            except ValueError as exc:
                raise AgentUnavailable("invalid market cutoff") from exc
            if market_cutoff.tzinfo is None or market_cutoff.astimezone(timezone.utc) > cutoff:
                raise AgentUnavailable("market cutoff is incompatible with request")
        abstained = data.get("abstained", False)
        unavailable = data.get("unavailable", False)
        if not isinstance(abstained, bool) or not isinstance(unavailable, bool):
            raise AgentUnavailable("invalid research availability flags")
        return AgentResult(
            upstream=self.upstream, revision=self.revision,
            portfolio_id=self.portfolio_id, ticker=ticker,
            decision=parse_decision(decision), rationale=rationale[:2000],
            raw_summary="external research returned a parsed decision",
            upstream_version=upstream_version or self.revision,
            instrument_id=instrument_id,
            market_cutoff=market_cutoff.astimezone(timezone.utc),
            decision_timestamp=cutoff.astimezone(timezone.utc),
            model_provider=self.model_provider or "",
            model_id=self.model_id or "",
            configuration_fingerprint=str(data.get("configuration_fingerprint", "")),
            evidence_references=tuple(references), abstained=abstained,
            unavailable=unavailable, status=status,
        )
