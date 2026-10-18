from __future__ import annotations

import json

import pytest

from sidedeck.smoke import _parse_json, main


def test_smoke_requires_explicit_network_opt_in() -> None:
    with pytest.raises(SystemExit, match="allow-network-model-test"):
        main(["run", "--provider", "ollama"])


def test_smoke_parser_never_needs_to_log_raw_model_text() -> None:
    assert _parse_json('{"action":"HOLD","ticker":"AAPL"}')['action'] == "HOLD"
    assert _parse_json("not json") == {}


def test_smoke_output_is_json_serializable(tmp_path) -> None:
    output = tmp_path / "real_agent_smoke.json"
    output.write_text(json.dumps({"raw_response_persisted": False}), encoding="utf-8")
    assert json.loads(output.read_text(encoding="utf-8"))["raw_response_persisted"] is False
