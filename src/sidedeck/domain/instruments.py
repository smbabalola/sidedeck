from __future__ import annotations

from decimal import Decimal

from .contracts import Instrument

ALLOWED_INSTRUMENTS: dict[str, Instrument] = {
    "AAPL": Instrument(instrument_id="US:AAPL", ticker="AAPL", asset_type="EQUITY", venue="NASDAQ"),
    "MSFT": Instrument(instrument_id="US:MSFT", ticker="MSFT", asset_type="EQUITY", venue="NASDAQ"),
    "SPY": Instrument(instrument_id="US:SPY", ticker="SPY", asset_type="ETF", venue="NYSE_ARCA"),
    "QQQ": Instrument(instrument_id="US:QQQ", ticker="QQQ", asset_type="ETF", venue="NASDAQ"),
}


def get_instrument(ticker: str) -> Instrument:
    try:
        return ALLOWED_INSTRUMENTS[ticker.upper()]
    except KeyError as exc:
        raise ValueError(f"instrument is not in the approved US equity/ETF universe: {ticker}") from exc


def get_instrument_by_id(instrument_id: str) -> Instrument:
    if not instrument_id.startswith("US:"):
        raise ValueError(f"instrument ID is not canonical: {instrument_id}")
    return get_instrument(instrument_id[3:])


def validate_quantity(instrument: Instrument, quantity: Decimal) -> Decimal:
    if quantity <= 0 or not quantity.is_finite():
        raise ValueError("quantity must be finite and positive")
    if not instrument.fractional_allowed and quantity != quantity.to_integral_value():
        raise ValueError(f"fractional quantity is not allowed for {instrument.ticker}")
    quantum = Decimal(1).scaleb(-instrument.quantity_scale)
    if quantity.quantize(quantum) != quantity:
        raise ValueError(f"quantity precision exceeds {instrument.quantity_scale} places")
    return quantity
