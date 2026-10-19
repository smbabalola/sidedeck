import pytest

from sidedeck.application.saxo_broker_reconcile import summarize_collection


def test_empty_and_finite_collections():
    assert summarize_collection({"Data": [], "__count": 0}, "orders") == 0
    assert summarize_collection({"Data": [{"OrderId": "abc"}]}, "orders") == 1


@pytest.mark.parametrize("data", [
    {}, {"Data": {}}, {"Data": [], "__next": "abc"},
    {"Data": [], "__count": 5}, {"Data": [None]},
])
def test_incomplete_or_bad_broker_state_blocks(data):
    with pytest.raises(ValueError):
        summarize_collection(data, "orders")
