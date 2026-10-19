import io
import json
import urllib.parse

import pytest

from sidedeck.application.p5_alpaca_history import (
    MarketDataUnavailable, fetch_alpaca_iex, parse_bars,
)


class FakeResponse:
    def __init__(self, value):
        self.data = json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, limit):
        return self.data


def test_alpaca_iex_fetch_uses_data_endpoint_and_keeps_adjustment_unverified():
    calls = []

    def opener(req, timeout):
        calls.append(req)
        return FakeResponse({"bars": [
            {"t": "2025-02-03T05:00:00Z", "c": 12.5},
        ], "next_page_token": None})

    output = fetch_alpaca_iex("SOFI", "2025-02-01", "2025-02-05",
                              key_id="fake", secret="fake", open_url=opener)
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(calls[0].full_url).query)
    assert calls[0].full_url.startswith("https://data.alpaca.markets/v2/stocks/SOFI/bars?")
    assert query["feed"] == ["iex"]
    assert query["adjustment"] == ["split"]
    assert output["corporate_actions_verified"] is False
    assert output["research_only"] is True
    assert output["records"][0]["close"] == 12.5


def test_alpaca_retrieves_all_pages():
    pages = [
        {"bars": [{"t": "2025-02-03T05:00:00Z", "c": 12.5}], "next_page_token": "NEXT"},
        {"bars": [{"t": "2025-02-04T05:00:00Z", "c": 12.7}], "next_page_token": None},
    ]

    def opener(req, timeout):
        return FakeResponse(pages.pop(0))

    output = fetch_alpaca_iex("SOFI", "2025-02-01", "2025-02-05",
                              key_id="fake", secret="fake", open_url=opener)
    assert len(output["records"]) == 2


def test_no_data_is_blocked():
    with pytest.raises(MarketDataUnavailable, match="no historical"):
        fetch_alpaca_iex("SOFI", "2025-02-01", "2025-02-05",
                         key_id="fake", secret="fake",
                         open_url=lambda req, timeout: FakeResponse({"bars": [], "next_page_token": None}))


def test_future_bar_rejected():
    from datetime import date
    with pytest.raises(MarketDataUnavailable, match="future"):
        parse_bars({"bars": [{"t": "2025-02-06T05:00:00Z", "c": 1}]},
                   cutoff=date(2025, 2, 5))


def test_duplicate_dates_rejected():
    bar = {"t": "2025-02-03T05:00:00Z", "c": 12.5}
    with pytest.raises(MarketDataUnavailable, match="duplicate"):
        fetch_alpaca_iex("SOFI", "2025-02-01", "2025-02-05",
                         key_id="fake", secret="fake",
                         open_url=lambda req, timeout: FakeResponse({
                             "bars": [bar, bar], "next_page_token": None,
                         }))
