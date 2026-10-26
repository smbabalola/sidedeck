"""SD-107/108 contract: invariants that must hold until the Demo route is reviewed and released."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from sidedeck.application import sd103_trading_pipeline as p
from sidedeck.application.sd063_autonomous_demo_policy import SUBMISSION
from sidedeck.application.sd064_unlock_grant import MAX_REQUESTS, MAX_WINDOW, MAX_WRITES
from sidedeck.infrastructure import etoro_demo_write_transport as transport

SRC = Path(__file__).resolve().parents[1] / "src" / "sidedeck" / "application"
NETWORK = {"urllib", "http", "requests", "httpx", "aiohttp", "socket", "websockets"}


def test_demo_routes_are_not_released():
    assert p.BROKER_ROUTES["ETORO_DEMO"].startswith("NOT_RELEASED")
    assert p.BROKER_ROUTES["ETORO_REAL"] == "PERMANENTLY_EXCLUDED"
    for route in ("ETORO_DEMO", "ALPACA_PAPER", "ETORO_REAL"):
        with pytest.raises(p.ExecutionNotReleased):
            p.require_route(route)


def test_pipeline_modules_have_no_network_access():
    for name in ("sd103_trading_pipeline", "sd104_pipeline_api", "sd112_pooled_admission"):
        tree = ast.parse((SRC / f"{name}.py").read_text(encoding="utf-8"))
        imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)
                    for a in n.names} | {n.module.split(".")[0] for n in ast.walk(tree)
                                         if isinstance(n, ast.ImportFrom) and n.module}
        assert not imported & NETWORK, name


def test_scheduler_uses_only_the_hostname_from_socket():
    tree = ast.parse((SRC / "sd109_research_schedule.py").read_text(encoding="utf-8"))
    uses = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name) and n.value.id == "socket"}
    assert uses == {"gethostname"}


def test_msft_transport_lock_is_engaged():
    # Global lock never set. The only permitted release-bound unlock is the owner-approved
    # 2026-10-26 MSFT pilot digest; restore `is None` when re-locking after the run.
    assert transport.NETWORK_TRANSPORT_ENABLED is False
    assert transport.UNLOCKED_PILOT_DIGEST in (
        None, "1ab4d2c8f85c94ef6fca78164b3e1e593929cc6e3cf7c52c82eae135c3d7fd4a")
    assert not transport.network_transport_enabled("0" * 64)
    assert not transport.network_transport_enabled(None)


def test_grant_ceilings_are_the_reviewed_design_values():
    assert MAX_WINDOW["autonomous_policy"].days == 7
    assert MAX_REQUESTS == {"pilot_release": 12, "autonomous_policy": 2000}
    assert MAX_WRITES == {"pilot_release": 2, "autonomous_policy": 200}


def test_policy_proposals_are_never_submissions():
    assert SUBMISSION == "OFFLINE_PROPOSAL_NOT_SUBMITTED"


def test_pipeline_intents_are_never_submitted(tmp_path):
    report = p.acceptance(tmp_path)
    assert report["orders"]
    assert {o["status"] for o in report["orders"]} == {"PROPOSED_NOT_SUBMITTED"}
    assert report["execution"]["orders_submitted_to_a_broker"] == 0
