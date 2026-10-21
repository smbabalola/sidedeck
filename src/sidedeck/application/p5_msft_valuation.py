"""Point-in-time MSFT valuation admission; no data transport or defaults."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal


class ValuationEvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class MsftValuationEvidence:
    valuation_date: date
    cutoff: datetime
    filing_published_at: datetime
    price_date: date
    close_source_a: Decimal
    close_source_b: Decimal
    source_a: str
    source_b: str
    adjustment_basis: str
    corporate_actions_status: str
    diluted_eps: Decimal
    eps_source: str
    shares_outstanding: Decimal
    shares_as_of: date
    price_tolerance_bps: Decimal = Decimal("1")


def admit_msft_valuation(evidence: MsftValuationEvidence) -> dict[str, str]:
    cutoff = evidence.cutoff.astimezone(timezone.utc) if evidence.cutoff.tzinfo else None
    published = (evidence.filing_published_at.astimezone(timezone.utc)
                 if evidence.filing_published_at.tzinfo else None)
    if cutoff is None or published is None or published > cutoff:
        raise ValuationEvidenceError("filing publication is after the valuation cutoff")
    if evidence.valuation_date != evidence.price_date or evidence.price_date > cutoff.date():
        raise ValuationEvidenceError("valuation date and price date are not point-in-time valid")
    if evidence.price_date < published.date():
        raise ValuationEvidenceError("price precedes public filing availability")
    if not evidence.source_a or not evidence.source_b or evidence.source_a == evidence.source_b:
        raise ValuationEvidenceError("independent price sources are required")
    if evidence.adjustment_basis != "split_adjusted_close":
        raise ValuationEvidenceError("split-adjusted closing basis is required")
    if evidence.corporate_actions_status != "VERIFIED":
        raise ValuationEvidenceError("corporate actions are not verified")
    if not evidence.eps_source or not evidence.shares_as_of <= cutoff.date():
        raise ValuationEvidenceError("filing-dated EPS/share evidence is incomplete")
    values = (evidence.close_source_a, evidence.close_source_b, evidence.diluted_eps,
              evidence.shares_outstanding, evidence.price_tolerance_bps)
    if any(not isinstance(value, Decimal) or not value.is_finite() for value in values):
        raise ValuationEvidenceError("valuation evidence must be finite Decimal values")
    if any(value <= 0 for value in values[:4]) or evidence.price_tolerance_bps < 0:
        raise ValuationEvidenceError("valuation evidence must be positive")
    tolerance = evidence.price_tolerance_bps / Decimal("10000")
    if abs(evidence.close_source_a - evidence.close_source_b) / evidence.close_source_a > tolerance:
        raise ValuationEvidenceError("independent closes conflict")
    close = (evidence.close_source_a + evidence.close_source_b) / Decimal("2")
    market_cap = close * evidence.shares_outstanding
    return {"ticker": "MSFT", "valuation_date": evidence.valuation_date.isoformat(),
            "close_usd": str(close), "shares_outstanding": str(evidence.shares_outstanding),
            "market_cap_usd": str(market_cap), "diluted_eps": str(evidence.diluted_eps),
            "pe": str(market_cap / (evidence.diluted_eps * evidence.shares_outstanding)),
            "status": "VALIDATED", "broker_execution": "DISABLED"}
