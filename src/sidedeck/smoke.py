"""Explicitly opt-in, redacted local model smoke tests.

The default path is offline. A real provider call requires the explicit
``--allow-network-model-test`` flag and is limited to one synthetic-context
request. Provider inference and an actual upstream TradingAgents graph run are
recorded as separate facts; neither path can submit an order.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from sidedeck.agents import (
    AgentProposalEnvelope,
    AgentRunRequest,
    MarketBundle,
    ProposalSchemaValidator,
    TradingAgentsProposalAdapter,
)
from sidedeck.domain.accounting import PortfolioState
from sidedeck.domain.contracts import MarketSnapshot, PriceType, Session
from sidedeck.domain.risk import RiskGate

PINNED_SHA = TradingAgentsProposalAdapter.upstream_sha
DEFAULT_CUTOFF = datetime(2026, 1, 5, 21, tzinfo=timezone.utc)
OLLAMA_DEFAULT = "http://127.0.0.1:11434"
OLLAMA_DEFAULT_MODEL = "llama3.2:3b"


def _load_approved_env() -> None:
    """Load only provider configuration from the ignored local .env file."""
    env_path = Path(".env")
    if not env_path.is_file():
        return
    approved = {
        "OLLAMA_HOST", "OLLAMA_BASE_URL", "OLLAMA_MODEL", "NVIDIA_API_KEY",
        "NVIDIA_MODEL", "NVIDIA_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL",
        "OPENAI_BASE_URL",
    }
    for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name in approved and name not in os.environ:
            os.environ[name] = value.strip().strip('"').strip("'")


def _safe_model_name(provider: str) -> str:
    if provider == "ollama":
        return os.getenv("OLLAMA_MODEL") or OLLAMA_DEFAULT_MODEL
    if provider == "nvidia":
        return os.getenv("NVIDIA_MODEL") or "meta/llama-3.1-8b-instruct"
    return os.getenv("OPENAI_MODEL") or "gpt-4o-mini"


def _ollama_base() -> str:
    configured = os.getenv("OLLAMA_BASE_URL") or os.getenv("OLLAMA_HOST") or OLLAMA_DEFAULT
    return configured.rstrip("/").removesuffix("/v1")


def _provider_status(provider: str) -> dict[str, Any]:
    if provider == "ollama":
        try:
            request = Request(_ollama_base() + "/api/tags", method="GET")
            with urlopen(request, timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))
            models = tuple(str(item.get("name", "")) for item in payload.get("models", ()))
            return {"provider": provider, "reachable": True, "model": _safe_model_name(provider), "models": models}
        except (OSError, ValueError, HTTPError, URLError) as exc:
            return {"provider": provider, "reachable": False, "model": _safe_model_name(provider), "error_type": type(exc).__name__}
    key_name = "NVIDIA_API_KEY" if provider == "nvidia" else "OPENAI_API_KEY"
    return {
        "provider": provider,
        "configured": bool(os.getenv(key_name)),
        "model": _safe_model_name(provider),
        "key_name": key_name,
    }


def _chat(provider: str, prompt: str) -> tuple[str, int | None]:
    model = _safe_model_name(provider)
    if provider == "ollama":
        endpoint = _ollama_base() + "/api/chat"
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0, "num_predict": 120},
        }
        headers = {"Content-Type": "application/json"}
    else:
        if provider == "nvidia":
            endpoint = os.getenv("NVIDIA_BASE_URL") or "https://integrate.api.nvidia.com/v1/chat/completions"
            key = os.getenv("NVIDIA_API_KEY")
        else:
            endpoint = os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1/chat/completions"
            key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(f"{provider} key is not configured")
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 120,
        }
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    request = Request(endpoint, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    with urlopen(request, timeout=45) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if provider == "ollama":
        content = str(payload.get("message", {}).get("content", ""))
        usage = payload.get("eval_count")
    else:
        content = str(payload.get("choices", [{}])[0].get("message", {}).get("content", ""))
        usage = payload.get("usage", {}).get("completion_tokens")
    return content, int(usage) if isinstance(usage, int) else None


def _bundle() -> MarketBundle:
    return MarketBundle(
        bundle_id="real-smoke-synthetic-aapl",
        decision_cutoff_utc=DEFAULT_CUTOFF,
        snapshots=(MarketSnapshot(
            instrument_id="US:AAPL", ticker="AAPL", provider="synthetic-smoke",
            price_type=PriceType.EOD_CLOSE, price=Decimal("100"),
            market_timestamp=DEFAULT_CUTOFF, ingestion_timestamp=DEFAULT_CUTOFF,
            session=Session.CLOSED, quality="FIXTURE / NOT LIVE MARKET DATA",
        ),),
        allowed_instruments=("US:AAPL",), max_snapshot_age_seconds=3600,
        provenance="fixture://real-agent-smoke/synthetic-context",
    )


def _request() -> AgentRunRequest:
    return AgentRunRequest(
        run_id=uuid4(), experiment_id="real-agent-smoke", portfolio_id="tradingagents",
        strategy_id="tradingagents-real-smoke", adapter_id="tradingagents.upstream",
        adapter_revision="tradingagents-smoke-1", upstream_repository="TauricResearch/TradingAgents",
        upstream_sha=PINNED_SHA, decision_cutoff_utc=DEFAULT_CUTOFF,
        market_bundle_id="real-smoke-synthetic-aapl", allowed_instruments=("US:AAPL",),
        configuration_ref="local-ollama-or-approved-provider", resource_budget={"provider_calls": 1},
        cash_usd=Decimal("1000"), deterministic_fixture=False,
    )


def _prompt() -> str:
    return (
        "Return ONLY a JSON object with keys action, ticker, quantity, stop_price, "
        "invalidation, rationale. Use HOLD with quantity null and stop_price null if "
        "you cannot justify a fully specified trade. This is a synthetic offline "
        "research context, not a market quote and not an order. Instrument AAPL, "
        "synthetic price 100 USD, cutoff 2026-01-05T21:00:00Z, cash 1000 USD. "
        "A BUY or SELL must include positive numeric quantity, stop_price and a "
        "nonempty invalidation. Do not include broker or credential fields."
    )


def _parse_json(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            parsed = json.loads(content[start:end + 1])
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _provider_worker(envelope: AgentProposalEnvelope) -> Any:
    class Worker:
        adapter_id = "tradingagents.upstream"
        revision = "tradingagents-smoke-1"

        def propose(self, request: AgentRunRequest, bundle: MarketBundle) -> AgentProposalEnvelope:
            return envelope

    return Worker()


def run_provider(provider: str, *, allow_network: bool, output_dir: Path) -> int:
    if not allow_network:
        raise SystemExit("refusing provider call without --allow-network-model-test")
    if provider not in {"ollama", "nvidia", "openai"}:
        raise SystemExit("provider must be ollama, nvidia, or openai")
    _load_approved_env()
    status = _provider_status(provider)
    if provider == "ollama" and not status.get("reachable"):
        raise SystemExit("Ollama is not reachable; no fallback was attempted automatically")
    started = time.monotonic()
    content, tokens = _chat(provider, _prompt())
    decision = _parse_json(content)
    request, bundle = _request(), _bundle()
    adapter = TradingAgentsProposalAdapter(enabled=True)
    envelope = adapter.normalize_decision(request, bundle, decision)
    validation = ProposalSchemaValidator().validate(request, bundle, envelope)
    risk: dict[str, Any] | None = None
    if validation.accepted and envelope.proposals:
        state = PortfolioState(portfolio_id="tradingagents", cash=Decimal("1000"))
        decision_result = RiskGate().evaluate(
            envelope.proposals[0], state, bundle.snapshots[0], portfolio_value=Decimal("1000"),
            marks={"US:AAPL": bundle.snapshots[0]},
        )
        risk = {"accepted": decision_result.accepted, "reason": decision_result.reason.value}
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence = {
        "provider": provider, "model": status.get("model"), "provider_reachable": status.get("reachable", status.get("configured")),
        "provider_inference_verified": True, "tradingagents_graph_run_verified": False,
        "upstream_import_verified": False, "upstream_sha": PINNED_SHA,
        "response_shape": "structured_json" if decision else "unparseable",
        "normalized_result": envelope.result,
        "proposal_count": len(envelope.proposals),
        "side_deck_validation_accepted": validation.accepted,
        "validation_reasons": validation.reason_codes, "risk": risk, "token_usage": tokens,
        "runtime_ms": int((time.monotonic() - started) * 1000),
        "simulation_only": True, "broker_calls": False, "raw_response_persisted": False,
    }
    (output_dir / "real_agent_smoke.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Controlled local SideDeck model smoke test")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check-providers")
    run = sub.add_parser("run")
    run.add_argument("--provider", choices=("ollama", "nvidia", "openai"), required=True)
    run.add_argument("--allow-network-model-test", action="store_true")
    run.add_argument("--output-dir", type=Path, default=Path("results"))
    args = parser.parse_args(argv)
    _load_approved_env()
    if args.command == "check-providers":
        print(json.dumps({name: _provider_status(name) for name in ("ollama", "nvidia", "openai")}, indent=2, sort_keys=True))
        return 0
    return run_provider(args.provider, allow_network=args.allow_network_model_test, output_dir=args.output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
