import pytest

from sidedeck.bridges.hedge_fund_bridge import classify_signal
from sidedeck.bridges.tradingagents_bridge import extract_action


@pytest.mark.parametrize(("conviction", "action"), [
    (0.75, "BUY"), (-0.5, "SELL"), (0.0, "HOLD"),
])
def test_real_upstream_conviction_normalization(conviction, action):
    assert classify_signal(conviction) == action


@pytest.mark.parametrize("conviction", [float("nan"), float("inf"), -1.01, 1.01, True, "0.5"])
def test_invalid_upstream_conviction_fails_closed(conviction):
    with pytest.raises(ValueError):
        classify_signal(conviction)


def test_abstention_cannot_be_reported_as_hold():
    with pytest.raises(ValueError, match="abstained"):
        classify_signal(0.0, abstained=True)


@pytest.mark.parametrize("rating", ["Overweight", "Underweight", "Review", "BUY / HOLD"])
def test_current_tradingagents_non_order_ratings_not_reinterpreted(rating):
    with pytest.raises(ValueError):
        extract_action(rating)
