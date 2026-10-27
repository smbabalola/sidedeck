"""SD-136: fail-closed boundary regression, entirely offline and credential-free."""
from __future__ import annotations

import ast
from pathlib import Path
from decimal import Decimal

import pytest

from sidedeck.application.sd036_etoro_demo_desk import BrokerExecutionDisabled
from sidedeck.application.sd103_trading_pipeline import (
    ExecutionNotReleased, require_route,
)
from sidedeck.application.sd107_demo_gateway import (
    BROKER_ROUTES, GatewayRefused, OfflineDemoGateway, OfflineDemoSimulator,
)
from sidedeck.domain.etoro_demo_orders import (
    DEMO_OPEN_PATH, RealExecutionExcluded, require_demo_route,
)
from sidedeck.infrastructure.etoro_demo_write_transport import (
    production_transport_factory,
)

APPLICATION = Path(__file__).resolve().parents[1] / "src" / "sidedeck" / "application"
NETWORK_ROOTS = {"urllib", "http", "requests", "httpx", "aiohttp", "socket", "websockets"}


def test_only_offline_simulator_is_admissible_to_the_existing_policy_gateway() -> None:
    # The exact-type refusal must happen before dereferencing the other dependencies;
    # passing a fake HTTP-shaped object must never turn simulation into a broker send.
    with pytest.raises(GatewayRefused, match="only the offline simulator"):
        OfflineDemoGateway(
            policy=None, runtime=None, authority=None,
            grant_document={}, grant_signature="", simulator=object(),
            reconciliation_signer=None, anchor_keeper=None,
        )
    with pytest.raises(GatewayRefused, match="externally anchored audit journal is required"):
        OfflineDemoGateway(
            policy=None, runtime=None, authority=None, grant_document={}, grant_signature="",
            simulator=OfflineDemoSimulator(fill_price=Decimal("1")),
            reconciliation_signer=None, anchor_keeper=None,
        )


def test_current_demo_and_real_execution_are_not_released() -> None:
    assert BROKER_ROUTES == {"ETORO_DEMO": "NOT_RELEASED"}
    for route in ("ETORO_DEMO", "ETORO_REAL"):
        with pytest.raises(ExecutionNotReleased):
            require_route(route)
    require_demo_route("POST", DEMO_OPEN_PATH)  # Route shape, not authorisation.
    for method, path in (
        ("POST", "/api/v2/trading/execution/real/orders"),
        ("POST", "/api/v1/trading/execution/real/market-close-orders/positions/1"),
        ("GET", "/api/v1/trading/info/real/pnl"),
    ):
        with pytest.raises(RealExecutionExcluded):
            require_demo_route(method, path)


def test_supervised_network_factory_refuses_before_reading_credentials() -> None:
    # A past pilot does not keep its old release alive; no .env, opener or API call.
    factory = production_transport_factory({}, "0" * 64)
    with pytest.raises(BrokerExecutionDisabled, match="locked"):
        factory.validate()


@pytest.mark.parametrize("name", [
    "sd107_demo_gateway",
    "sd129_etoro_demo_order_port",
    "sd126_offline_day_controller",
])
def test_unreleased_policy_and_port_modules_cannot_open_network(name: str) -> None:
    tree = ast.parse((APPLICATION / f"{name}.py").read_text(encoding="utf-8"))
    roots = {
        alias.name.split(".")[0]
        for node in ast.walk(tree) if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not roots.intersection(NETWORK_ROOTS), name
