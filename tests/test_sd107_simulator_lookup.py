"""SD-107 simulator lookup must never fabricate/reopen a closed position."""
from decimal import Decimal
from pathlib import Path

import pytest

from sidedeck.application.sd107_demo_gateway import GatewayRefused, OfflineDemoSimulator
from sidedeck.domain.etoro_demo_orders import (
    DemoCloseRequest, DemoOpenRequest, parse_order_lookup,
)

_OPEN = "11111111-1111-4111-8111-111111111111"
_CLOSE = "22222222-2222-4222-8222-222222222222"


def _open() -> DemoOpenRequest:
    return DemoOpenRequest(_OPEN, 1004, Decimal("0.09"), Decimal("110"))


def _close(position_id: int) -> DemoCloseRequest:
    return DemoCloseRequest(_CLOSE, position_id, 1004, Decimal("0.09"))


def test_lookup_reports_closed_after_restart_without_database_writes(tmp_path: Path) -> None:
    storage = tmp_path / "orders.sqlite3"
    sim = OfflineDemoSimulator(fill_price=Decimal("100"), close_price=Decimal("95"),
                               storage_path=storage)
    request = _open()
    accepted = sim.open(request)
    order_id = accepted["orderId"]
    assert isinstance(order_id, int)
    position_id = order_id + 100_000
    first_changes = sim._db.total_changes
    opened = sim.lookup(order_id)
    assert sim._db.total_changes == first_changes  # genuinely read-only lookup
    assert opened["positionExecutions"][0]["state"] == "open"
    assert opened["positionExecutions"][0]["remainingUnits"] == 0.09
    assert parse_order_lookup(opened, request=request, order_id=order_id).filled_units == Decimal("0.09")

    sim.close(_close(position_id))
    sim.close_store()

    restarted = OfflineDemoSimulator(fill_price=Decimal("100"), close_price=Decimal("95"),
                                     storage_path=storage)
    changes_before = restarted._db.total_changes
    result = restarted.lookup_reference(request.reference_id)
    assert restarted._db.total_changes == changes_before
    execution = result["positionExecutions"][0]
    assert execution["state"] == "closed"
    assert execution["remainingUnits"] == 0.0
    assert execution["openingData"]["units"] == 0.09
    assert parse_order_lookup(result, request=request, order_id=order_id).filled_units == Decimal("0.09")
    assert restarted.submitted_orders == 1

    # Replaying the same accepted reference is not a new order or a reopen.
    assert restarted.open(request)["orderId"] == order_id
    closed_again = restarted.lookup(order_id)["positionExecutions"][0]
    assert closed_again["state"] == "closed"
    assert closed_again["remainingUnits"] == 0.0
    assert restarted.submitted_orders == 1
    restarted.close_store()


def test_crash_after_durable_open_recovers_with_read_only_lookup(tmp_path: Path) -> None:
    storage = tmp_path / "orders.sqlite3"
    sim = OfflineDemoSimulator(fill_price=Decimal("100"), storage_path=storage,
                               crash_after_open=True)
    with pytest.raises(GatewayRefused, match="process interruption"):
        sim.open(_open())
    sim.close_store()

    restarted = OfflineDemoSimulator(fill_price=Decimal("100"), storage_path=storage)
    changes_before = restarted._db.total_changes
    outcome = restarted.lookup_reference(_OPEN)
    assert restarted._db.total_changes == changes_before
    assert outcome["positionExecutions"][0]["state"] == "open"
    assert restarted.submitted_orders == 1
    restarted.close_store()


def test_missing_durable_position_refuses_lookup_without_creating_one(tmp_path: Path) -> None:
    storage = tmp_path / "orders.sqlite3"
    sim = OfflineDemoSimulator(fill_price=Decimal("100"), storage_path=storage)
    accepted = sim.open(_open())
    sim._db.execute("DELETE FROM sim_positions")
    count_before = sim._db.total_changes
    with pytest.raises(GatewayRefused, match="lineage is missing"):
        sim.lookup(accepted["orderId"])
    assert sim._db.total_changes == count_before
    sim.close_store()
