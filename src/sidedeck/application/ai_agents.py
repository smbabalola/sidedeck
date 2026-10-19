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
from datetime import datetime
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

    def run(self, ticker: str, cutoff: datetime) -> AgentResult:
        if self.portfolio_id not in ("tradingagents", "ai-trading"):
            raise ValueError("unknown portfolio")
        if not re.fullmatch(r"[A-Z][A-Z0-9.-]*", ticker):
            raise ValueError("invalid ticker")
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError("cutoff must include timezone")
        data = _run([*self.command, "--ticker", ticker, "--as-of",
                     cutoff.date().isoformat()], cwd=self.cwd)
        if data.get("ticker") != ticker:
            raise AgentUnavailable("upstream ticker mismatch")
        decision = data.get("decision")
        rationale = data.get("rationale")
        if not isinstance(decision, str) or not isinstance(rationale, str):
            raise AgentUnavailable("upstream decision fields missing")
        return AgentResult(
            upstream=self.upstream, revision=self.revision,
            portfolio_id=self.portfolio_id, ticker=ticker,
            decision=parse_decision(decision), rationale=rationale[:2000],
            raw_summary="external research returned a parsed decision",
        )
