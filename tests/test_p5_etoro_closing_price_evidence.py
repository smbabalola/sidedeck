import pytest

from sidedeck.application.p5_etoro_closing_price_evidence import parse_closing_prices


def sample():
    return [{"instrumentId": 1002, "officialClosingPrice": 175.75,
             "closingPrices": {"daily": {"price": 175.75, "date": "2025-03-07 00:00:00Z"},
                               "weekly": {"price": 175.75, "date": "2025-03-07 00:00:00Z"},
                               "monthly": {"price": -1, "date": "0001-01-01 00:00:00Z"}}}]


def test_parses_broker_reports_but_never_approves_valuation():
    data = parse_closing_prices(sample(), instrument_id=1002)
    assert [x.interval for x in data] == ["daily", "weekly"]
    assert all(x.validation == "BROKER_REPORTED_UNCORROBORATED" for x in data)
    assert str(data[0].price) == "175.75"


@pytest.mark.parametrize("mutate", [
    lambda x: x.append(x[0]),
    lambda x: x[0].update({"instrumentId": 999}),
    lambda x: x[0].update({"closingPrices": []}),
    lambda x: x[0]["closingPrices"]["daily"].update({"price": -5}),
    lambda x: x[0]["closingPrices"]["daily"].update({"date": "2025-03-07"}),
    lambda x: x[0]["closingPrices"]["daily"].update({"price": True}),
])
def test_fails_closed(mutate):
    x = sample()
    mutate(x)
    with pytest.raises(ValueError):
        parse_closing_prices(x, instrument_id=1002)


def test_documented_sentinel_is_not_a_price():
    x = sample()
    x[0]["closingPrices"] = {"monthly": {"price": -1, "date": "0001-01-01 00:00:00Z"}}
    with pytest.raises(ValueError):
        parse_closing_prices(x, instrument_id=1002)
