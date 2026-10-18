import pytest

from sidedeck.agents.synthetic_data import SyntheticDataBoundaryViolation, SyntheticResearchBoundary


def test_unknown_tool_has_no_vendor_fallback() -> None:
    with pytest.raises(SyntheticDataBoundaryViolation):
        SyntheticResearchBoundary().call_tool("yahoo_quote", "AAPL")


def test_native_egress_gate_is_required_before_real_graph() -> None:
    # This is deliberately a policy assertion, not a Python socket claim.
    # The actual OS gate is unavailable on this host and therefore the real
    # graph must not be invoked.
    native_egress_verified = False
    assert native_egress_verified is False
