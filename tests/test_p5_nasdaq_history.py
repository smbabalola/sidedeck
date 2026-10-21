from datetime import date

import pytest

from sidedeck.application.p5_nasdaq_history import NasdaqDataUnavailable, parse_nasdaq_daily


def payload():
    return {"symbol": "MSFT", "currency": "USD", "session": "REGULAR",
            "adjustment": "split_adjusted_close",
            "rows": [{"date": "2025-02-03", "close": "410", "source_id": "nasdaq:msft:2025-02-03"}]}


def test_nasdaq_parser_is_explicitly_provenance_pending():
    result = parse_nasdaq_daily(payload(), ticker="MSFT", cutoff=date(2025, 2, 5))
    assert result["provenance_verified"] is False
    assert result["records"][0]["close"] == "410"


@pytest.mark.parametrize("mutation", [
    lambda data: data.update({"symbol": "AAPL"}),
    lambda data: data.update({"adjustment": "all"}),
    lambda data: data["rows"][0].update({"date": "2025-02-08"}),
    lambda data: data["rows"][0].update({"source_id": ""}),
])
def test_nasdaq_parser_fails_closed(mutation):
    data = payload()
    mutation(data)
    with pytest.raises(NasdaqDataUnavailable):
        parse_nasdaq_daily(data, ticker="MSFT", cutoff=date(2025, 2, 5))
