"""SD-050 one-shot MSFT lookup: offline, fake opener, synthetic IDs only."""
import io
import json
from datetime import datetime, timezone
from email.message import Message
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

from sidedeck.application import sd050_msft_instrument_lookup as lookup
from sidedeck.application.sd050_msft_instrument_lookup import (
    LookupRefused, attempts_consumed, budget_path_for, run_once, select_exact_match,
)

from sidedeck.infrastructure.etoro_demo_store import EtoroDemoStore

TEST_ID = "SD-099"
OPEN = frozenset({TEST_ID})

ENV = {"ETORO_DEMO_TRADE_API_KEY": "app-key-111", "ETORO_DEMO_TRADE_USER_KEY": "user-key-222"}


def item(**changes):
    data = {"instrumentId": 7001, "internalSymbolFull": "MSFT", "internalExchangeName": "Nasdaq",
            "instrumentType": "Stocks", "displayname": "Microsoft", "isDelisted": False,
            "isHiddenFromClient": False, "isCurrentlyTradable": True, "isBuyEnabled": True,
            "currentRate": 530.1}
    data.update(changes)
    return data


class Response:
    def __init__(self, payload, status=200):
        self.status, self._raw = status, json.dumps(payload).encode()

    def read(self, n):
        return self._raw[:n]


class Opener:
    def __init__(self, result):
        self.result, self.requests = result, []

    def open(self, request, timeout):
        self.requests.append(request)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def paths(tmp_path):
    rows = [{"positionID": n, "instrumentID": 1000 + n, "orderID": 9000 + n, "isBuy": True,
             "units": 1, "amount": 100, "leverage": 1, "openDateTime": "2026-09-01T14:30:00Z",
             "unrealizedPnL": {"pnL": 0}} for n in (1, 2, 3, 4)]
    payload = {"clientPortfolio": {"positions": rows, "credit": 1, "bonusCredit": 0,
                                   "accountCurrencyId": 1, "mirrors": [], "orders": [],
                                   "ordersForOpen": [], "ordersForClose": [],
                                   "ordersForCloseMultiple": [], "entryOrders": [],
                                   "exitOrders": [], "stockOrders": []}}
    db = tmp_path / "etoro_demo.sqlite3"
    EtoroDemoStore(str(db)).capture_baseline(payload, observed_at=datetime.now(timezone.utc),
                                             expected_positions=4)
    return {"db": str(db), "budget": str(tmp_path / "b.sqlite3"),
            "evidence": str(tmp_path / "e.json")}


def go(paths, opener, env=ENV):
    return run_once(env=env, db_path=paths["db"], budget_path=paths["budget"],
                    evidence_path=paths["evidence"], opener_factory=lambda: opener,
                    authorization_id=TEST_ID, authorized_ids=OPEN)


def test_exact_match_resolves_and_request_is_bounded(paths):
    opener = Opener(Response({"items": [item(), item(instrumentId=7002,
                                                       internalSymbolFull="MSFT.RTH")]}))
    result = go(paths, opener)
    assert result["status"] == "RESOLVED" and result["instrument_id"] == 7001
    assert result["conflicts_with_protected_baseline"] is False
    assert len(opener.requests) == 1
    url = urlsplit(opener.requests[0].full_url)
    assert url.netloc == "public-api.etoro.com" and url.path == "/api/v1/market-data/search"
    query = parse_qs(url.query)
    assert query["internalSymbolFull"] == ["MSFT"] and "instrumentId" in query["fields"][0]
    headers = {k.lower(): v for k, v in opener.requests[0].header_items()}
    assert headers["x-user-key"] == "user-key-222" and opener.requests[0].get_method() == "GET"
    assert "user-key-222" not in json.dumps(result)
    with open(paths["evidence"], encoding="utf-8") as handle:
        assert json.load(handle)["instrument_id"] == 7001


def test_baseline_conflict_rejected(paths):
    result = go(paths, Opener(Response({"items": [item(instrumentId=1003)]})))
    assert result["status"] == "BASELINE_CONFLICT_REJECTED"


@pytest.mark.parametrize("items", [
    [], [item(), item(instrumentId=7002)], [item(internalExchangeName="LSE")],
    [item(isDelisted=True)], [item(instrumentType="CFD Index")], [item(instrumentId="7001")],
])
def test_ambiguous_or_wrong_matches_fail_closed(items):
    with pytest.raises(LookupRefused):
        select_exact_match({"items": items})


def test_single_attempt_even_after_failure(paths):
    first = Opener(HTTPError("u", 403, "denied", Message(), io.BytesIO(b"")))
    assert go(paths, first)["status"] == "FAILED_UNVERIFIED"
    second = Opener(Response({"items": [item()]}))
    with pytest.raises(LookupRefused, match="exhausted"):
        go(paths, second)
    assert second.requests == [] and attempts_consumed(paths["budget"]) == 1


def test_preflight_refusals_send_nothing(paths, tmp_path):
    opener = Opener(Response({"items": [item()]}))
    with pytest.raises(PermissionError):
        go(paths, opener, env={**ENV, "ETORO_API_KEY": "legacy"})
    with pytest.raises(LookupRefused, match="baseline"):
        run_once(env=ENV, db_path=str(tmp_path / "missing.db"), budget_path=paths["budget"],
                 evidence_path=paths["evidence"], opener_factory=lambda: opener,
                 authorization_id=TEST_ID, authorized_ids=OPEN)
    assert opener.requests == [] and attempts_consumed(paths["budget"]) == 0


def test_missing_type_accepted_but_wrong_type_rejected():
    assert select_exact_match({"items": [item(instrumentType=None)]})["instrumentId"] == 7001
    with pytest.raises(LookupRefused, match="not a stock"):
        select_exact_match({"items": [item(instrumentType="Crypto")]})


def test_rejection_records_sanitized_diagnostics(paths):
    result = go(paths, Opener(Response({"items": [item(internalExchangeName="LSE")]})))
    assert result["status"] == "FAILED_UNVERIFIED"
    diag = result["diagnostics"]
    assert diag["exact_symbol_matches"] == 1
    assert diag["candidates"][0]["fields"]["instrumentId"] == "int"
    assert "7001" not in json.dumps(diag) and "530.1" not in json.dumps(diag)



def test_review2_consumed_or_unlisted_ids_never_send(paths):
    opener = Opener(Response({"items": [item()]}))
    for auth, allowed in (("SD-050", frozenset({"SD-050"})), ("SD-051", frozenset()),
                          (" SD-050", frozenset({" SD-050"})), ("SD_050", frozenset({"SD_050"}))):
        with pytest.raises(LookupRefused):
            run_once(env=ENV, db_path=paths["db"], budget_path=paths["budget"],
                     evidence_path=paths["evidence"], opener_factory=lambda: opener,
                     authorization_id=auth, authorized_ids=allowed)
    assert opener.requests == [] and lookup.AUTHORIZED_LOOKUP_IDS == frozenset()


def test_review2_network_lock_and_budget_paths(paths):
    assert lookup.LOOKUP_NETWORK_ENABLED is False
    with pytest.raises(LookupRefused, match="locked"):
        run_once(env=ENV, db_path=paths["db"], budget_path=paths["budget"],
                 evidence_path=paths["evidence"], authorization_id=TEST_ID, authorized_ids=OPEN)
    for bad in (" SD-050", "../x/SD-050", "SD_050", "SD-050\t", "sd-050"):
        with pytest.raises(LookupRefused):
            budget_path_for(bad)
    assert budget_path_for("SD-050").endswith("sd050-auth-budget.sqlite3")
    assert str(lookup.DATA_DIR) in budget_path_for("SD-050")


def test_review2_listing_status_must_be_explicit():
    with pytest.raises(LookupRefused, match="listing status"):
        select_exact_match({"items": [item(isDelisted=None)]})
    with pytest.raises(LookupRefused, match="Nasdaq"):
        select_exact_match({"items": [item(internalExchangeName="Nasdaq Dubai")]})
