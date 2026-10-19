"""SOFI SIM risk accounting from independently verified inputs.

This is a pure gate: it never obtains a quote, assumes an exchange rate,
approves a broker order or places a trade.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal


@dataclass(frozen=True)
class SofiCostEvidence:
    quote_usd: Decimal
    quote_time_utc: datetime
    observed_at_utc: datetime
    eur_to_usd: Decimal
    fees_usd: Decimal
    broker_cash_eur: Decimal


def validate_costs(evidence: "SofiCostEvidence", *, portfolio_cash_usd: Decimal,
                   open_exposure_usd: Decimal = Decimal("0")) -> tuple[bool, str, Decimal]:
    q = evidence.quote_usd
    fx = evidence.eur_to_usd
    fee = evidence.fees_usd
    cash = evidence.broker_cash_eur
    values = (q, fx, fee, cash, portfolio_cash_usd, open_exposure_usd)
    if any(not item.is_finite() for item in values):
        return False, "nonfinite_value", Decimal("0")
    if q <= 0 or fx <= 0 or fee < 0 or cash <= 0 or portfolio_cash_usd < 0 or open_exposure_usd < 0:
        return False, "invalid_financial_inputs", Decimal("0")
    observed = evidence.observed_at_utc
    timestamp = evidence.quote_time_utc
    if (observed.tzinfo is None or timestamp.tzinfo is None
            or observed.utcoffset() is None or timestamp.utcoffset() is None):
        return False, "naive_quote_timestamp", Decimal("0")
    delta = observed.astimezone(timezone.utc) - timestamp.astimezone(timezone.utc)
    if delta < timedelta(0) or delta > timedelta(minutes=2):
        return False, "stale_or_future_quote", Decimal("0")
    broker_usd = cash * fx
    total_usd = q + fee
    if broker_usd < total_usd:
        return False, "broker_cash_does_not_cover_quote_and_fees", total_usd
    if total_usd > Decimal("200") or total_usd > portfolio_cash_usd:
        return False, "usd_risk_limit", total_usd
    if open_exposure_usd + total_usd > Decimal("1000"):
        return False, "portfolio_limit", total_usd
    # External source provenance and broker EUR/USD conversion still need verification.
    return False, "external_provenance_and_order_lifecycle_not_verified", total_usd
