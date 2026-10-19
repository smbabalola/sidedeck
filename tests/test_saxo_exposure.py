import pytest

from sidedeck.application.saxo_exposure import inspect_exposure
from sidedeck.infrastructure.saxo_sim import SaxoSimClient


def test_client_wide_empty_snapshot():
    result = inspect_exposure(
        {"Currency": "EUR", "OpenPositionsCount": 0, "OrdersCount": 0},
        {"Data": []}, {"Data": []},
    )
    assert result.complete
    assert result.reason == "client_wide_snapshot_only"


def test_mismatch_blocks():
    result = inspect_exposure(
        {"Currency": "EUR", "OpenPositionsCount": 1, "OrdersCount": 0},
        {"Data": []}, {"Data": []},
    )
    assert not result.complete
    assert result.reason == "broker_counts_disagree"


@pytest.mark.parametrize("positions,orders", [
    ({"Data": [], "__next": "/port/v1/positions?skip=1"}, {"Data": []}),
    ({"Data": [], "__count": 1}, {"Data": []}),
    ({"Data": []}, {"Data": [], "__next": "next"}),
    ({}, {"Data": []}),
])
def test_paging_or_missing_data_blocks(positions, orders):
    with pytest.raises(ValueError):
        inspect_exposure({"Currency": "EUR", "OpenPositionsCount": 0, "OrdersCount": 0},
                         positions, orders)


def test_bad_broker_counts_block():
    with pytest.raises(ValueError):
        inspect_exposure({"Currency": "EUR", "OpenPositionsCount": True, "OrdersCount": 0},
                         {"Data": []}, {"Data": []})


def test_saxo_read_only_allowlist_rejects_trade(monkeypatch):
    monkeypatch.delenv("SAXO_SIM_ACCESS_TOKEN", raising=False)
    with pytest.raises(PermissionError):
        SaxoSimClient().get("/trade/v2/orders")
