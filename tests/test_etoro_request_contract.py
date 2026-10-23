"""Offline request-contract check against legacy SignalDeck's source-verified v2 search.

All credentials are synthetic, no network access, orders or portfolio calls.
Actual endpoint success is not implied by an offline request shape match.
"""

from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest

from sidedeck import data_probe
from sidedeck.domain.etoro import (
    EtoroDataError,
    EtoroHistoricalDataClient,
    MarketDataReadCapability,
    _validate_path,
)


class ContractTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str], UUID]] = []

    def get(self, path: str, params: dict[str, str], request_id: UUID) -> tuple[int, dict[str, str], bytes]:
        self.calls.append((path, dict(params), request_id))
        return 200, {}, (
            b'{"results":[{"instrumentId":1001,"symbol":"AAPL",'
            b'"type":"stock","exchangeId":"NASDAQ","currency":"USD",'
            b'"isLeveraged":false,"isInverse":false}]}'
        )


def test_v2_search_matches_working_signaldeck_request_shape() -> None:
    transport = ContractTransport()
    client = EtoroHistoricalDataClient(transport, capability=MarketDataReadCapability())
    assert client.resolve_instrument("AAPL").instrument_id == 1001
    assert len(transport.calls) == 1
    path, params, req_id = transport.calls[0]
    UUID(str(req_id))
    assert path == "/api/v2/market-data/instruments/search"
    assert params == {"query": "AAPL", "limit": "5"}


def test_legacy_signaldeck_v2_search_reference_is_enabled_but_other_routes_blocked() -> None:
    legacy = urlsplit(
        "https://public-api.etoro.com/api/v2/market-data/instruments/search?query=AAPL&limit=5"
    )
    assert legacy.scheme == "https"
    assert legacy.hostname == "public-api.etoro.com"
    assert legacy.path == "/api/v2/market-data/instruments/search"
    assert parse_qs(legacy.query) == {"query": ["AAPL"], "limit": ["5"]}
    _validate_path("/api/v2/market-data/instruments/search")
    with pytest.raises(EtoroDataError):
        _validate_path("/api/v1/market-data/search")
    with pytest.raises(EtoroDataError):
        _validate_path("/api/v2/market-data/rates")


def test_side_deck_http_request_contains_only_expected_auth_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[object] = []

    class FakeResponse:
        status = 200
        headers: dict[str, str] = {}

        def read(self, count: int) -> bytes:
            return b'{"items":[]}'

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    class FakeOpener:
        def open(self, request: object, timeout: int) -> FakeResponse:
            assert timeout == 10
            requests.append(request)
            return FakeResponse()

    monkeypatch.setattr(data_probe, "build_opener", lambda *args: FakeOpener())
    uuid = uuid4()
    transport = data_probe.UrllibReadOnlyTransport({
        "x-api-key": "ONLY_DUMMY_API_KEY", "x-user-key": "ONLY_DUMMY_USER_KEY"
    })
    status, _, _ = transport.get("/api/v2/market-data/instruments/search", {"query": "AAPL", "limit": "5"}, uuid)
    assert status == 200
    assert len(requests) == 1
    request = requests[0]
    assert request.get_method() == "GET"  # type: ignore[attr-defined]
    endpoint = urlsplit(request.full_url)  # type: ignore[attr-defined]
    assert endpoint.hostname == "public-api.etoro.com"
    assert endpoint.path == "/api/v2/market-data/instruments/search"
    assert parse_qs(endpoint.query) == {"query": ["AAPL"], "limit": ["5"]}
    keys = set(request.headers)  # type: ignore[attr-defined]
    assert keys == {"X-api-key", "X-user-key", "X-request-id", "Accept"}
    assert request.headers["X-api-key"] == "ONLY_DUMMY_API_KEY"  # type: ignore[attr-defined]
    assert request.headers["X-user-key"] == "ONLY_DUMMY_USER_KEY"  # type: ignore[attr-defined]
    assert UUID(request.headers["X-request-id"]) == uuid  # type: ignore[attr-defined]


def test_history_route_requires_desc_not_backward() -> None:
    _validate_path("/api/v1/market-data/instruments/1001/history/candles/desc/OneDay/1000")
    with pytest.raises(EtoroDataError):
        _validate_path("/api/v1/market-data/instruments/1001/history/candles/backward/OneDay/1000")
    with pytest.raises(EtoroDataError):
        _validate_path("/api/v1/market-data/instruments/1001/history/candles/asc/OneDay/1000")
