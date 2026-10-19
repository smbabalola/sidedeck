from datetime import datetime, timezone
from decimal import Decimal

from hypothesis import HealthCheck, given, settings, strategies as st

from sidedeck.application.foundation import initialise_two_portfolios
from sidedeck.domain.accounting import fill_event
from sidedeck.domain.contracts import EventType, ExperimentManifest

AT = datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc)


@settings(max_examples=25, derandomize=True,
          suppress_health_check=[HealthCheck.too_slow])
@given(quantity=st.integers(min_value=1, max_value=5), fee_cents=st.integers(min_value=0, max_value=25))
def test_replay_conserves_cash_and_is_idempotent(quantity: int, fee_cents: int) -> None:
    manifest = ExperimentManifest(
        experiment_id="EXP-001", configuration_revision="r1", created_at=AT,
        instruments=("US:AAPL",), data_policy="fixture",
    )
    ledger = initialise_two_portfolios(manifest, AT)
    fee = Decimal(fee_cents) / Decimal("100")
    event = fill_event(
        "tradingagents", "buy", EventType.BUY_FILL, "US:AAPL",
        Decimal(quantity), Decimal("10"), AT, fee,
    )
    assert ledger.append(event) is True
    assert ledger.append(event) is False
    state = ledger.replay("tradingagents")
    assert state.cash == Decimal("1000") - Decimal(quantity * 10) - fee
    assert state.positions["US:AAPL"].quantity == Decimal(quantity)
