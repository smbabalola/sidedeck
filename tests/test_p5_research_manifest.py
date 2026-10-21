from datetime import date

import pytest

from sidedeck.application.p5_research_manifest import build_input_manifest


def test_manifest_hashes_sources_and_withholds_content():
    result = build_input_manifest(
        ticker="MSFT", as_of=date(2026, 6, 30),
        sources=[{"source": "sec:companyfacts", "content": {"periods": 8}},
                 {"source": "market:unavailable", "content": "none"}],
    )
    assert result["valuation"] == "BLOCKED_UNTIL_INDEPENDENT_PRICE_EVIDENCE"
    assert all(set(item) == {"source", "sha256"} for item in result["sources"])
    assert "periods" not in str(result)


def test_manifest_requires_nonempty_labeled_sources():
    with pytest.raises(ValueError):
        build_input_manifest(ticker="MSFT", as_of=date(2026, 6, 30), sources=[])
