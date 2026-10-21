import json
import urllib.parse
from datetime import date

import pytest

from sidedeck.application.p5_alpaca_history import (
    MarketDataUnavailable, PersistentRequestBudget, fetch_alpaca_iex, fetch_alpaca_sip,
    parse_bars,
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
            {"t": "2025-02-03T05:00:00Z", "o": 12, "h": 13, "l": 11,
             "c": 12.5, "v": 100},
        ], "next_page_token": None})

    output = fetch_alpaca_iex("SOFI", "2025-02-01", "2025-02-05",
                              key_id="fake", secret="fake", open_url=opener)
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(calls[0].full_url).query)
    assert calls[0].full_url.startswith("https://data.alpaca.markets/v2/stocks/SOFI/bars?")
    assert query["feed"] == ["iex"]
    assert query["adjustment"] == ["split"]
    assert output["corporate_actions_verified"] is False
    assert output["research_only"] is True
    assert output["records"][0]["close"] == "12.5"


def test_alpaca_retrieves_all_pages():
    pages = [
        {"bars": [{"t": "2025-02-03T05:00:00Z", "o": 12, "h": 13, "l": 11, "c": 12.5, "v": 100}], "next_page_token": "NEXT"},
        {"bars": [{"t": "2025-02-04T05:00:00Z", "o": 12, "h": 13, "l": 11, "c": 12.7, "v": 100}], "next_page_token": None},
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
        parse_bars({"bars": [{"t": "2025-02-06T05:00:00Z", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}]},
                   cutoff=date(2025, 2, 5))


def test_duplicate_dates_rejected():
    bar = {"t": "2025-02-03T05:00:00Z", "o": 12, "h": 13, "l": 11, "c": 12.5, "v": 100}
    with pytest.raises(MarketDataUnavailable, match="duplicate"):
        fetch_alpaca_iex("SOFI", "2025-02-01", "2025-02-05",
                         key_id="fake", secret="fake",
                         open_url=lambda req, timeout: FakeResponse({
                             "bars": [bar, bar], "next_page_token": None,
                         }))


def test_sip_is_explicit_and_never_substituted_for_iex():
    seen = []
    def opener(req, timeout):
        seen.append(urllib.parse.parse_qs(urllib.parse.urlsplit(req.full_url).query))
        return FakeResponse({"bars": [{"t": "2025-02-03T05:00:00Z", "o": 12, "h": 13,
                                        "l": 11, "c": 12.5, "v": 100}], "next_page_token": None})
    result = fetch_alpaca_sip("MSFT", "2025-02-01", "2025-02-05", key_id="x", secret="y", open_url=opener)
    assert seen[0]["feed"] == ["sip"]
    assert result["feed"] == "sip" and result["instrument_id"] == "US:MSFT"


def test_spy_uses_approved_exchange_identity():
    result = fetch_alpaca_sip(
        "SPY", "2025-02-01", "2025-02-05", key_id="x", secret="y",
        open_url=lambda req, timeout: FakeResponse({"bars": [{"t": "2025-02-03T05:00:00Z",
            "o": 12, "h": 13, "l": 11, "c": 12.5, "v": 100}], "next_page_token": None}),
    )
    assert result["exchange"] == "NYSE_ARCA"


def test_missing_ohlcv_is_rejected():
    with pytest.raises(MarketDataUnavailable, match="invalid open"):
        parse_bars({"bars": [{"t": "2025-02-03T05:00:00Z", "c": 1}]}, cutoff=date(2025, 2, 5))


def test_persistent_budget_is_consumed_before_request_and_survives_restart(tmp_path):
    budget_path = tmp_path / "request-budget.json"
    budget = PersistentRequestBudget(budget_path, scope="MSFT|scope", maximum=1)
    result = fetch_alpaca_sip(
        "MSFT", "2025-02-01", "2025-02-05", key_id="x", secret="y", budget=budget,
        open_url=lambda req, timeout: FakeResponse({"bars": [{"t": "2025-02-03T05:00:00Z",
            "o": 12, "h": 13, "l": 11, "c": 12.5, "v": 100}], "next_page_token": None}),
    )
    assert result["feed"] == "sip"
    with pytest.raises(MarketDataUnavailable, match="exhausted"):
        PersistentRequestBudget(budget_path, scope="MSFT|scope", maximum=1).reserve()


def test_global_budget_is_consumed_with_per_ticker_budget(tmp_path):
    local = PersistentRequestBudget(tmp_path / "msft.json", scope="MSFT|scope", maximum=2)
    global_budget = PersistentRequestBudget(tmp_path / "global.json", scope="global", maximum=1)
    output = fetch_alpaca_sip(
        "MSFT", "2025-02-01", "2025-02-05", key_id="x", secret="y", budget=local,
        global_budget=global_budget,
        open_url=lambda req, timeout: FakeResponse({"bars": [{"t": "2025-02-03T05:00:00Z",
            "o": 12, "h": 13, "l": 11, "c": 12.5, "v": 100}], "next_page_token": None}),
    )
    assert output["global_request_count"] == 1
    assert global_budget.requests_used == 1


def test_global_budget_blocks_before_second_transmission(tmp_path):
    calls = []
    local = PersistentRequestBudget(tmp_path / "msft.json", scope="MSFT|scope", maximum=2)
    global_budget = PersistentRequestBudget(tmp_path / "global.json", scope="global", maximum=1)
    def opener(req, timeout):
        calls.append(req)
        return FakeResponse({
            "bars": [{"t": "2025-02-03T05:00:00Z", "o": 12, "h": 13, "l": 11, "c": 12.5, "v": 100}],
            "next_page_token": "NEXT",
        })
    with pytest.raises(MarketDataUnavailable, match="exhausted"):
        fetch_alpaca_sip("MSFT", "2025-02-01", "2025-02-05", key_id="x", secret="y",
                          budget=local, global_budget=global_budget, open_url=opener)
    assert len(calls) == 1
    assert local.requests_used == 1
    assert global_budget.requests_used == 1


def test_default_transport_rejects_redirects(monkeypatch):
    from sidedeck.application import p5_alpaca_history as module

    class RedirectingOpener:
        def open(self, request, timeout):
            raise AssertionError("redirect opener must be replaced by the allowlisted opener")

    monkeypatch.setattr(module.urllib.request, "build_opener", lambda handler: RedirectingOpener())
    with pytest.raises(AssertionError, match="redirect opener"):
        module._safe_urlopen(urllib.request.Request("https://data.alpaca.markets/v2/stocks/MSFT/bars"), timeout=1)
