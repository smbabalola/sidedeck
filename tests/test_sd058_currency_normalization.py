"""SD-058 root cause: the live eligibility `currency` was a case/whitespace variant of USD.

Friday pilot b0be3fe2 audit: the rejected payload's `currency` was a string that the forensic
sanitizer normalized to "USD", while `parse_eligibility` compared it exactly to "USD".
One shared, strict normalizer now serves the parser, row labels and the audit sanitizer.
"""
from decimal import Decimal

import pytest

from sidedeck.application.sd058_forensic_audit import summarize_schema
from sidedeck.domain.etoro_demo_orders import (
    EtoroDemoOrderError, identity_conflicts, normalize_currency_code, parse_eligibility,
)

KWARGS = {"instrument_id": 1004, "units": Decimal("0.09"), "notional_usd": Decimal("49.73")}


def live_shape(currency):
    """Same top-level shape the Friday audit recorded (field names only, synthetic values)."""
    row = {"instrumentId": 1004, "minPositionExposure": 10, "allowOpenPosition": True,
           "allowClosePosition": True, "unitsQuantityType": "fractional",
           "allowedOrderQuantityType": "all", "tradeUnitType": "units",
           "leverageConfigs": [{"direction": "long", "leverageValues": [1],
                                "settlementType": "real", "minPositionAmount": 10}]}
    payload = {"eligibilities": [row], "notFoundInstrumentIds": [], "notFoundSymbols": []}
    if currency is not _MISSING:
        payload["currency"] = currency
    return payload


_MISSING = object()


@pytest.mark.parametrize("value", ["USD", "usd", "Usd", " USD", "USD ", "\tusd\n",
                                   " USD "])
def test_benign_usd_variants_are_accepted(value):
    assert normalize_currency_code(value) == "USD"
    assert parse_eligibility(live_shape(value), **KWARGS).instrument_id == 1004


@pytest.mark.parametrize("value", ["GBP", "gbp", "EUR", "US D", "USDX", "US", "",
                                   "U​SD", "ＵＳＤ", "uſd", "УSD",
                                   None, 1, 1.0,
                                   True, ["USD"], {"code": "USD"}, b"USD", _MISSING])
def test_non_usd_missing_or_invalid_currency_is_still_rejected(value):
    with pytest.raises(EtoroDemoOrderError, match="not USD"):
        parse_eligibility(live_shape(value), **KWARGS)


@pytest.mark.parametrize("value,expected", [
    ("gbp", "GBP"), (" eur ", "EUR"), ("US D", None), ("USDX", None), ("", None),
    ("ＵＳＤ", None), ("U​SD", None), (None, None), (1, None), (b"USD", None),
])
def test_normalizer_is_strict_ascii_three_letters(value, expected):
    assert normalize_currency_code(value) == expected


def test_parser_and_audit_sanitizer_agree_on_the_same_payload():
    payload = live_shape(" usd ")
    recorded = [f for f in summarize_schema(payload)["fields"] if f["path"] == "currency"]
    assert recorded == [{"path": "currency", "type": "string", "currency_code": "USD",
                         "currency_exact": False}]
    parse_eligibility(payload, **KWARGS)                     # no longer disagrees
    exact = [f for f in summarize_schema(live_shape("USD"))["fields"] if f["path"] == "currency"]
    assert exact[0]["currency_exact"] is True


def test_row_currency_labels_use_the_same_normalizer():
    assert identity_conflicts({"currency": " usd "})[1] is not None
    with pytest.raises(EtoroDemoOrderError, match="non-USD"):
        identity_conflicts({"currency": "gbp"})
    with pytest.raises(EtoroDemoOrderError, match="non-USD"):
        identity_conflicts({"currency": "US D"})


def test_other_eligibility_gates_are_unchanged():
    bad = live_shape("usd")
    bad["eligibilities"][0]["allowOpenPosition"] = False
    with pytest.raises(EtoroDemoOrderError, match="does not allow"):
        parse_eligibility(bad, **KWARGS)
    with pytest.raises(EtoroDemoOrderError, match="minimum"):
        parse_eligibility(live_shape("usd"), instrument_id=1004, units=Decimal("0.09"),
                          notional_usd=Decimal("5"))
