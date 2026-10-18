from datetime import datetime, timezone

import pytest

from sidedeck.agents.synthetic_data import (
    FIXTURE_CUTOFF,
    FIXTURE_SOURCE,
    OfflineTradingAgentsGraph,
    SyntheticDataBoundaryViolation,
    SyntheticResearchBoundary,
)


def test_fixture_tools_are_deterministic_and_provenanced() -> None:
    boundary = SyntheticResearchBoundary()
    assert boundary.identity("AAPL")["source"] == FIXTURE_SOURCE
    assert boundary.stock_data("AAPL", "2026-01-05", "2026-01-05") == boundary.stock_data("AAPL", "2026-01-05", "2026-01-05")
    assert boundary.market_snapshot("AAPL", "2026-01-05")["notice"] == "FIXTURE / NOT LIVE MARKET DATA"
    assert boundary.cutoff == FIXTURE_CUTOFF


@pytest.mark.parametrize("call", [
    lambda b: b.identity("MSFT"),
    lambda b: b.stock_data("AAPL", "2026-01-06", "2026-01-06"),
    lambda b: b.market_snapshot("AAPL", "2026-01-06"),
    lambda b: b.indicators("AAPL", ("rsi",), "2026-01-05", 0),
])
def test_fixture_boundary_fails_closed(call) -> None:
    with pytest.raises(SyntheticDataBoundaryViolation):
        call(SyntheticResearchBoundary())


def test_compiled_tool_binding_rejects_remote_or_unknown_tools() -> None:
    boundary = SyntheticResearchBoundary()
    boundary.validate_compiled_tool_names(tuple(boundary.tool_bindings()))
    with pytest.raises(SyntheticDataBoundaryViolation):
        boundary.validate_compiled_tool_names(("get_stock_data", "get_indicators", "yahoo_quote"))


def test_offline_graph_is_replayable_and_never_mutates_trading_state() -> None:
    graph = OfflineTradingAgentsGraph(SyntheticResearchBoundary())
    first = graph.propagate("AAPL", "2026-01-05")
    second = graph.propagate("AAPL", "2026-01-05")
    assert first == second
    assert first[0]["data_source"] == FIXTURE_SOURCE
    assert first[1] == "Hold"


def test_fixture_cutoff_is_utc() -> None:
    assert FIXTURE_CUTOFF.tzinfo == timezone.utc
    assert datetime.fromisoformat(FIXTURE_CUTOFF.isoformat()).utcoffset() is not None
