from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sidedeck.application.saxo_sofi_costs import SofiCostEvidence, validate_costs


def evidence(**changes):
    now = datetime(2026, 10, 19, 14, 0, tzinfo=timezone.utc)
    fields = {"quote_usd": Decimal("45"), "quote_time_utc": now,
              "observed_at_utc": now, "eur_to_usd": Decimal("1.15"),
              "fees_usd": Decimal("1"), "broker_cash_eur": Decimal("41.03")}
    fields.update(changes)
    return SofiCostEvidence(**fields)


def test_synthetic_evidence_never_auto_authorizes_order():
    ok, reason, total = validate_costs(evidence(), portfolio_cash_usd=Decimal("1000"))
    assert not ok
    assert reason == "external_provenance_and_order_lifecycle_not_verified"
    assert total == Decimal("46")


def test_stale_quote_blocked():
    now = datetime(2026, 10, 19, 14, 0, tzinfo=timezone.utc)
    ok, reason, _ = validate_costs(
        evidence(quote_time_utc=now - timedelta(minutes=3)),
        portfolio_cash_usd=Decimal("1000"))
    assert not ok and reason == "stale_or_future_quote"


def test_notional_cap_blocked():
    ok, reason, _ = validate_costs(
        evidence(quote_usd=Decimal("205"), broker_cash_eur=Decimal("300")),
        portfolio_cash_usd=Decimal("1000"))
    assert not ok and reason == "usd_risk_limit"


def test_broker_cash_mismatch_blocked():
    ok, reason, _ = validate_costs(
        evidence(quote_usd=Decimal("180")), portfolio_cash_usd=Decimal("1000"))
    assert not ok and reason == "broker_cash_does_not_cover_quote_and_fees"
