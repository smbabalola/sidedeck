"""SD-053 MSFT pilot intent and instrument identity evidence (offline)."""
import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from sidedeck.application import sd053_msft_pilot_intent as sd053
from sidedeck.application.sd048_pilot_release import PilotReleaseRefused
from sidedeck.domain.etoro_demo_orders import (
    BROKER_VERIFIED, DERIVED, EtoroDemoOrderError, identity_conflicts, parse_eligibility,
    parse_fresh_quote,
)

PROTECTED = frozenset({1001, 1002, 1003, 1005})


def test_intent_parameters_are_the_owner_configuration():
    intent = sd053.build_intent("0b6f3c1e-8a2d-4e5f-9a7b-1c2d3e4f5a6b")
    doc = json.loads(intent.canonical())
    assert doc["instrument_id"] == 1004 and doc["broker"] == "etoro-demo"
    assert doc["units"] == "0.09" and doc["max_limit_rate"] == "552.56"
    assert Decimal(doc["units"]) * Decimal(doc["max_limit_rate"]) <= Decimal("50")
    assert doc["max_notional_usd"] == "50" and doc["strategy"] == "tradingagents"
    assert doc["not_before"] == "2026-10-23T18:45:00+00:00"
    assert doc["expires_at"] == "2026-10-23T19:45:00+00:00"
    caps = doc["request_caps"]
    assert sum(caps.values()) == 12 and caps["open"] + caps["close"] == 2
    sd053.offline_checks(intent, PROTECTED)


def test_prepare_is_stable_and_never_overwrites(tmp_path):
    path = tmp_path / "intent.json"
    first = sd053.prepare(path, PROTECTED)
    assert (tmp_path / "intent.digest").read_bytes() == first["digest"].encode("ascii")
    assert sd053.prepare(path, PROTECTED) == first
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved["canonical"] = saved["canonical"].replace("0.09", "0.10")
    path.write_text(json.dumps(saved), encoding="utf-8")
    with pytest.raises(sd053.IntentRefused, match="does not match"):
        sd053.prepare(path, PROTECTED)


def test_baseline_instrument_and_window_are_refused(tmp_path):
    intent = sd053.build_intent("0b6f3c1e-8a2d-4e5f-9a7b-1c2d3e4f5a6b")
    with pytest.raises(sd053.IntentRefused, match="protected"):
        sd053.offline_checks(intent, PROTECTED | {1004})
    from sidedeck.application.sd048_pilot_release import _check_intent
    with pytest.raises(PilotReleaseRefused, match="window"):
        _check_intent(intent, datetime(2026, 10, 23, 15, 30, tzinfo=timezone.utc))


@pytest.mark.parametrize("row,expected", [
    ({}, (None, None)),
    ({"instrumentTypeID": 5, "currency": "USD"}, (BROKER_VERIFIED, BROKER_VERIFIED)),
    ({"instrumentType": "Stocks", "currencyId": 1}, (BROKER_VERIFIED, BROKER_VERIFIED)),
    ({"instrumentTypeID": None, "priceCurrency": None}, (None, None)),
])
def test_identity_labels_verify_when_present(row, expected):
    assert identity_conflicts(row) == expected


@pytest.mark.parametrize("row", [{"instrumentTypeID": 6}, {"instrumentType": "ETF"},
                                 {"instrumentTypeId": 10}, {"currency": "EUR"},
                                 {"currencyId": 2}, {"assetClass": "crypto"}])
def test_identity_conflicts_abort(row):
    with pytest.raises(EtoroDemoOrderError):
        identity_conflicts(row)


def _eligibility(**row_extra):
    row = {"instrumentId": 1004, "minPositionExposure": 10, "allowOpenPosition": True,
           "allowClosePosition": True, "unitsQuantityType": "fractional",
           "allowedOrderQuantityType": "all", "tradeUnitType": "units",
           "leverageConfigs": [{"direction": "long", "leverageValues": [1],
                                "settlementType": "real", "minPositionAmount": 10}], **row_extra}
    return {"currency": "USD", "eligibilities": [row]}


def test_eligibility_reports_derived_or_broker_verified_identity():
    kwargs = {"instrument_id": 1004, "units": Decimal("0.09"), "notional_usd": Decimal("47")}
    derived = parse_eligibility(_eligibility(), **kwargs)
    assert (derived.instrument_type_evidence, derived.currency_evidence) == (DERIVED, DERIVED)
    verified = parse_eligibility(_eligibility(instrumentTypeID=5, currency="USD"), **kwargs)
    assert verified.instrument_type_evidence == BROKER_VERIFIED
    assert verified.currency_evidence == BROKER_VERIFIED
    with pytest.raises(EtoroDemoOrderError, match="non-stock"):
        parse_eligibility(_eligibility(instrumentTypeID=6), **kwargs)


def test_rates_row_with_conflicting_currency_aborts():
    now = datetime.now(timezone.utc)
    row = {"instrumentId": 1004, "quoteType": "realtime", "bid": 526.0, "ask": 526.2,
           "date": now.isoformat(), "currency": "GBP"}
    with pytest.raises(EtoroDemoOrderError, match="non-USD"):
        parse_fresh_quote({"results": [row]}, instrument_id=1004, now=now)
