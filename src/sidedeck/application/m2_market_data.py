"""Offline normalized daily market data and valuation admission primitives.

The module accepts only caller-supplied evidence. It never downloads prices or
contacts a broker. A normalized bar is not considered usable until its
provenance, currency, session, adjustment basis and point-in-time cutoff pass.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any


class MarketDataError(ValueError):
    pass


@dataclass(frozen=True)
class NormalizedBar:
    instrument_id: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    source: str
    source_id: str
    exchange: str
    session: str
    currency: str
    adjustment: str

    @property
    def trading_date(self) -> date:
        return self.timestamp.date()


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool):
        raise MarketDataError(f"invalid {field}")
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise MarketDataError(f"invalid {field}") from exc
    if not result.is_finite() or result <= 0:
        raise MarketDataError(f"invalid {field}")
    return result


def normalize_daily_bars(payload: dict[str, Any], *, cutoff: datetime) -> tuple[list[NormalizedBar], dict[str, Any]]:
    """Normalize and validate daily OHLCV evidence without filling gaps."""
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise MarketDataError("cutoff must be timezone-aware")
    required = ("instrument_id", "source", "exchange", "session", "currency", "adjustment")
    if any(not isinstance(payload.get(key), str) or not payload[key].strip() for key in required):
        raise MarketDataError("market-data provenance is incomplete")
    raw = payload.get("records")
    if not isinstance(raw, list) or not raw:
        raise MarketDataError("market-data records are required")
    bars: list[NormalizedBar] = []
    seen: set[date] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise MarketDataError("invalid market-data record")
        try:
            timestamp = datetime.fromisoformat(str(item["timestamp"]).replace("Z", "+00:00"))
            source_id = str(item["source_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise MarketDataError("invalid market timestamp or source ID") from exc
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise MarketDataError("market timestamp must be timezone-aware")
        timestamp = timestamp.astimezone(timezone.utc)
        if timestamp > cutoff.astimezone(timezone.utc) or timestamp.date() in seen:
            raise MarketDataError("future or duplicate market bar")
        values = {name: _decimal(item.get(name), name) for name in ("open", "high", "low", "close", "volume")}
        if values["high"] < max(values["open"], values["close"]) or values["low"] > min(values["open"], values["close"]):
            raise MarketDataError("OHLC range is inconsistent")
        if not source_id:
            raise MarketDataError("source ID is required")
        seen.add(timestamp.date())
        bars.append(NormalizedBar(payload["instrument_id"], timestamp, **values,
                                  source=payload["source"], source_id=source_id,
                                  exchange=payload["exchange"], session=payload["session"],
                                  currency=payload["currency"], adjustment=payload["adjustment"]))
    bars.sort(key=lambda bar: bar.timestamp)
    dates = [bar.trading_date for bar in bars]
    gaps = [day.isoformat() for left, right in zip(dates, dates[1:])
            for day in (left + timedelta(days=1),)
            if (right - left).days > 1 and day.weekday() < 5]
    issues = ([] if payload["currency"] == "USD" else ["NON_USD"])
    if payload["session"] != "REGULAR":
        issues.append("NON_REGULAR_SESSION")
    if payload["adjustment"] != "split_adjusted":
        issues.append("UNSUPPORTED_ADJUSTMENT")
    if gaps:
        issues.append("TRADING_DAY_GAPS")
    report = {"instrument_id": payload["instrument_id"], "source": payload["source"],
              "bar_count": len(bars), "earliest": dates[0].isoformat(), "latest": dates[-1].isoformat(),
              "gaps": gaps, "conflicts": [], "issues": issues,
              "status": "READY" if not issues else "BLOCKED"}
    return bars, report


def admit_valuation(*, eps: Decimal, shares: Decimal, bar: NormalizedBar,
                    market_report: dict[str, Any], shares_filed: date, cutoff: date,
                    independent_close_verified: bool = False,
                    corporate_actions_verified: bool = False,
                    share_price_basis_verified: bool = False) -> dict[str, Any]:
    """Admit one market-cap/P-E observation only after all evidence gates pass."""
    if not (independent_close_verified and corporate_actions_verified
            and share_price_basis_verified):
        raise MarketDataError("independent closing-price, corporate-action and share-basis proof required")
    if market_report.get("status") != "READY" or market_report.get("conflicts") or market_report.get("gaps"):
        raise MarketDataError("market evidence is not ready for valuation")
    if bar.currency != "USD" or bar.adjustment != "split_adjusted" or bar.session != "REGULAR":
        raise MarketDataError("valuation requires USD regular split-adjusted evidence")
    if (not eps.is_finite() or not shares.is_finite() or shares_filed > bar.trading_date
            or bar.trading_date > cutoff or eps <= 0 or shares <= 0):
        raise MarketDataError("valuation evidence is not point-in-time valid")
    market_cap = bar.close * shares
    return {"price_date": bar.trading_date.isoformat(), "close_usd": str(bar.close),
            "shares": str(shares), "market_cap_usd": str(market_cap),
            "eps": str(eps), "pe": str(market_cap / (eps * shares)),
            "source_id": bar.source_id, "status": "VALIDATED"}
