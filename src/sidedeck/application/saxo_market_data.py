"""Provider-neutral, fail-closed market and FX evidence for Saxo SIM.

The provider is injected by the caller. This module never discovers a provider,
scrapes Yahoo, or assumes a historical price is executable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

from sidedeck.domain.contracts import MarketSnapshot, PriceType, Session, require_utc


@dataclass(frozen=True)
class FxSnapshot:
    """USD per EUR, with an explicit point-in-time and provenance."""

    provider: str
    pair: str
    usd_per_eur: Decimal
    observed_at: datetime
    ingestion_at: datetime
    quality: str

    def __post_init__(self) -> None:
        if self.pair != "EUR/USD" or not self.provider or not self.quality:
            raise ValueError("FX snapshot must be the EUR/USD pair with provenance")
        if not self.usd_per_eur.is_finite() or self.usd_per_eur <= 0:
            raise ValueError("EUR/USD rate must be finite and positive")
        observed = require_utc(self.observed_at)
        ingested = require_utc(self.ingestion_at)
        if observed > ingested:
            raise ValueError("FX observation cannot follow ingestion")
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "ingestion_at", ingested)


class MarketDataProvider(Protocol):
    def quote(self, ticker: str, *, as_of: datetime) -> MarketSnapshot: ...

    def fx(self, pair: str, *, as_of: datetime) -> FxSnapshot: ...


@dataclass(frozen=True)
class ExecutionEvidence:
    quote: MarketSnapshot
    fx: FxSnapshot
    observed_at: datetime
    max_age: timedelta
    spread_usd: Decimal
    fees_usd: Decimal
    fx_fee_usd: Decimal

    def __post_init__(self) -> None:
        now = require_utc(self.observed_at)
        if self.max_age <= timedelta(0):
            raise ValueError("market evidence max_age must be positive")
        for value in (self.spread_usd, self.fees_usd, self.fx_fee_usd):
            if not value.is_finite() or value < 0:
                raise ValueError("execution costs must be finite and nonnegative")
        if self.quote.currency != "USD" or self.quote.price_type is not PriceType.QUOTE:
            raise ValueError("execution requires a USD quote")
        if self.quote.session is not Session.REGULAR:
            raise ValueError("execution requires a regular-session quote")
        quote_time = require_utc(self.quote.market_timestamp)
        quote_ingest = require_utc(self.quote.ingestion_timestamp)
        fx_time = require_utc(self.fx.observed_at)
        fx_ingest = require_utc(self.fx.ingestion_at)
        if any(timestamp > now for timestamp in (quote_time, quote_ingest, fx_time, fx_ingest)):
            raise ValueError("market or FX evidence is future-dated")
        if any(now - timestamp > self.max_age for timestamp in (quote_time, quote_ingest, fx_time, fx_ingest)):
            raise ValueError("market or FX evidence is stale")
        object.__setattr__(self, "observed_at", now)

    @property
    def total_cost_usd(self) -> Decimal:
        return self.spread_usd + self.fees_usd + self.fx_fee_usd


def collect_execution_evidence(
    provider: MarketDataProvider,
    *,
    ticker: str,
    pair: str = "EUR/USD",
    as_of: datetime,
    max_age: timedelta = timedelta(minutes=2),
    spread_usd: Decimal = Decimal("0"),
    fees_usd: Decimal = Decimal("0"),
    fx_fee_usd: Decimal = Decimal("0"),
) -> ExecutionEvidence:
    """Collect both legs at one cutoff; provider failures propagate closed."""
    cutoff = require_utc(as_of)
    quote = provider.quote(ticker, as_of=cutoff)
    fx = provider.fx(pair, as_of=cutoff)
    if quote.ticker != ticker or quote.instrument_id != f"US:{ticker}":
        raise ValueError("provider returned the wrong instrument")
    return ExecutionEvidence(
        quote=quote, fx=fx, observed_at=cutoff, max_age=max_age,
        spread_usd=spread_usd, fees_usd=fees_usd, fx_fee_usd=fx_fee_usd,
    )
