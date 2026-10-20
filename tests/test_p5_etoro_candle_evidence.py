import pytest

from sidedeck.application.p5_etoro_candle_evidence import parse_candle_history


def fixture():
    return {"interval": "OneDay", "candles": [
        {"instrumentId": 1001, "candles": [
            {"instrumentID": 1001, "fromDate": "2026-10-16T00:00:00Z",
             "open": 100, "high": 102, "low": 99, "close": 101, "volume": 0},
            {"instrumentID": 1001, "fromDate": "2026-10-19T00:00:00Z",
             "open": 101, "high": 104, "low": 100, "close": 103, "volume": 12345},
        ]}]}


def test_documented_nested_ohlcv_and_status():
    result = parse_candle_history(fixture(), instrument_id=1001, interval="OneDay")
    assert len(result) == 2
    assert str(result[-1].close) == "103"
    assert result[0].volume == 0
    assert all(x.validation == "BROKER_REPORTED_UNCORROBORATED" for x in result)


@pytest.mark.parametrize("change", [
    lambda x: x.update({"interval": "OneWeek"}),
    lambda x: x["candles"][0].update({"instrumentId": 999}),
    lambda x: x["candles"][0]["candles"][0].update({"instrumentID": 999}),
    lambda x: x["candles"][0]["candles"][0].update({"high": 98}),
    lambda x: x["candles"][0]["candles"][0].update({"volume": -1}),
    lambda x: x["candles"][0]["candles"][1].update({"fromDate": "2026-10-16T00:00:00Z"}),
    lambda x: x["candles"][0]["candles"][0].update({"open": True}),
])
def test_invalid_candles_rejected(change):
    x = fixture()
    change(x)
    with pytest.raises(ValueError):
        parse_candle_history(x, instrument_id=1001, interval="OneDay")


def test_count_and_direction_are_strict():
    with pytest.raises(ValueError):
        parse_candle_history(fixture(), instrument_id=1001, interval="OneDay", max_count=1)
    with pytest.raises(ValueError):
        parse_candle_history(fixture(), instrument_id=1001, interval="Bad")
