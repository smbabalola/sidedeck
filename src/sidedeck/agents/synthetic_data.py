"""SideDeck-owned, deterministic research data for offline graph validation.

This module is deliberately independent of TradingAgents and all market-data
vendors.  It is a narrow seam for testing tool binding and graph plumbing; its
values are synthetic and must never be presented as live observations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable


class SyntheticDataBoundaryViolation(ValueError):
    """A graph requested data outside the approved synthetic fixture."""


FIXTURE_TICKER = "AAPL"
FIXTURE_DATE = date(2026, 1, 5)
FIXTURE_CUTOFF = datetime(2026, 1, 5, 21, 0, tzinfo=timezone.utc)
FIXTURE_SOURCE = "fixture://sidedeck/aapl-2026-01-05"
FIXTURE_NOTICE = "FIXTURE / NOT LIVE MARKET DATA"


@dataclass(frozen=True)
class SyntheticResearchBoundary:
    """Allow only the exact AAPL fixture used by the offline graph test."""

    ticker: str = FIXTURE_TICKER
    cutoff: datetime = FIXTURE_CUTOFF

    def __post_init__(self) -> None:
        if self.ticker != FIXTURE_TICKER or self.cutoff != FIXTURE_CUTOFF:
            raise SyntheticDataBoundaryViolation("only the canonical AAPL fixture is approved")

    def identity(self, ticker: str) -> dict[str, str]:
        self._ticker(ticker)
        return {
            "ticker": FIXTURE_TICKER,
            "company_name": "Synthetic Apple Fixture",
            "asset_type": "EQUITY",
            "venue": "SYNTHETIC",
            "currency": "USD",
            "source": FIXTURE_SOURCE,
            "notice": FIXTURE_NOTICE,
        }

    def stock_data(self, symbol: str, start_date: str, end_date: str) -> dict[str, Any]:
        self._ticker(symbol)
        self._date(start_date)
        self._date(end_date)
        if start_date > end_date or end_date != self.cutoff.date().isoformat():
            raise SyntheticDataBoundaryViolation("stock data must end at the fixture cutoff")
        return {
            "ticker": FIXTURE_TICKER,
            "currency": "USD",
            "as_of": self.cutoff.isoformat(),
            "source": FIXTURE_SOURCE,
            "notice": FIXTURE_NOTICE,
            "ohlcv": [{"date": "2026-01-05", "open": "100", "high": "103", "low": "99", "close": "102", "volume": 1000000}],
        }

    def indicators(self, symbol: str, names: tuple[str, ...], current_date: str, look_back_days: int) -> dict[str, Any]:
        self._ticker(symbol)
        self._date(current_date)
        if current_date != self.cutoff.date().isoformat() or look_back_days <= 0:
            raise SyntheticDataBoundaryViolation("indicators must use the approved fixture date and lookback")
        if not names or any(not name.isidentifier() for name in names):
            raise SyntheticDataBoundaryViolation("indicator names must be explicit identifiers")
        values = {name: "fixture-value" for name in names}
        return {"ticker": FIXTURE_TICKER, "as_of": self.cutoff.isoformat(), "source": FIXTURE_SOURCE, "notice": FIXTURE_NOTICE, "indicators": values}

    def market_snapshot(self, ticker: str, as_of: str) -> dict[str, Any]:
        self._ticker(ticker)
        if as_of != self.cutoff.date().isoformat():
            raise SyntheticDataBoundaryViolation("snapshot date is outside the approved fixture")
        return {
            "ticker": FIXTURE_TICKER,
            "price": "102",
            "currency": "USD",
            "market_timestamp": self.cutoff.isoformat(),
            "ingestion_timestamp": self.cutoff.isoformat(),
            "source": FIXTURE_SOURCE,
            "notice": FIXTURE_NOTICE,
        }

    def tool_bindings(self) -> dict[str, Callable[..., dict[str, Any]]]:
        """Return the complete approved market analyst tool set."""
        return {
            "get_stock_data": self.stock_data,
            "get_indicators": self.indicators,
            "get_verified_market_snapshot": self.market_snapshot,
        }

    def call_tool(self, name: str, *args: Any) -> dict[str, Any]:
        """Invoke only a named approved tool; there is intentionally no fallback."""
        try:
            tool = self.tool_bindings()[name]
        except KeyError as exc:
            raise SyntheticDataBoundaryViolation(f"unknown tool is denied: {name}") from exc
        return tool(*args)

    def validate_compiled_tool_names(self, names: tuple[str, ...]) -> None:
        expected = frozenset(self.tool_bindings())
        if frozenset(names) != expected or len(names) != len(expected):
            raise SyntheticDataBoundaryViolation("compiled graph contains an unapproved or duplicate tool")

    def _ticker(self, value: str) -> None:
        if value != self.ticker:
            raise SyntheticDataBoundaryViolation("unknown ticker is denied")

    @staticmethod
    def _date(value: str) -> None:
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise SyntheticDataBoundaryViolation("invalid or unparseable fixture date") from exc


@dataclass(frozen=True)
class OfflineTradingAgentsGraph:
    """A deterministic graph-shaped test double; it never calls a model/network."""

    boundary: SyntheticResearchBoundary

    def propagate(self, ticker: str, trade_date: str) -> tuple[dict[str, Any], str]:
        self.boundary.identity(ticker)
        self.boundary.stock_data(ticker, trade_date, trade_date)
        self.boundary.indicators(ticker, ("rsi",), trade_date, 14)
        self.boundary.market_snapshot(ticker, trade_date)
        return {
            "final_rating": "Hold",
            "final_trade_decision": "Hold",
            "data_source": FIXTURE_SOURCE,
            "data_notice": FIXTURE_NOTICE,
            "model": "deterministic-stub",
        }, "Hold"
