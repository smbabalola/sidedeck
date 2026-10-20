"""Stage 2 read-only verification infrastructure, exercised offline only.

The real ``SaxoSimClient`` runs against a synthetic gateway (no network, dummy
token). These tests prove provider authenticity, freshness and that quote,
FX and account evidence cannot be swapped between accounts, instruments or
orders. No live Saxo endpoint is contacted.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sidedeck.application import saxo_sim_submission as submission
from sidedeck.application.saxo_market_data import EvidenceOrigin, ExecutionEvidence
from sidedeck.application.saxo_sim_evidence import (
    SOFI_UIC, SaxoSimMarketEvidence, SimEvidenceError, collect_account_evidence,
)
from sidedeck.application.saxo_sim_submission import SubmissionBlocked, prepare_sofi_request
from sidedeck.infrastructure.saxo_account_scope import SaxoAccountScope
from sidedeck.infrastructure.saxo_sim import EURUSD_UIC, SaxoSimClient
from sim_gateway_fake import SyntheticGateway, authenticated, clock, synthetic_gateway
from test_saxo_p4_execution import NOW, sealed_precheck

T = NOW


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def stock_price(**changes):
    quote = {"Bid": 40.98, "Ask": 41.0, "PriceTypeAsk": "Tradable", "PriceTypeBid": "Tradable",
             "DelayedByMinutes": 0, "ErrorCode": "None", "MarketState": "Open"}
    quote.update(changes.pop("quote", {}))
    response = {"Uic": SOFI_UIC, "AssetType": "Stock", "LastUpdated": iso(T - timedelta(seconds=10)),
                "DisplayAndFormat": {"Currency": "USD"}, "Quote": quote}
    response.update(changes)
    return response


def fx_price(**changes):
    quote = {"Bid": 1.0999, "Ask": 1.1001, "PriceTypeAsk": "Tradable", "PriceTypeBid": "Tradable",
             "DelayedByMinutes": 0, "ErrorCode": "None"}
    quote.update(changes.pop("quote", {}))
    response = {"Uic": EURUSD_UIC, "AssetType": "FxSpot",
                "LastUpdated": iso(T - timedelta(seconds=5)), "Quote": quote}
    response.update(changes)
    return response


def gateway(account_id="approved", *, stock=None, fx=None, **keys):
    keys.setdefault("client_key", "client")
    keys.setdefault("account_key", "opaque-account-key")
    return SyntheticGateway(account_id, prices={"Stock": stock or stock_price(),
                                                "FxSpot": fx or fx_price()}, **keys)


def market(gw, at=T):
    """Build the provider inside the synthetic gateway; returns (provider, gateway)."""
    with synthetic_gateway(gw, at):
        client, scope = authenticated(gw)
        return SaxoSimMarketEvidence(client, scope)


def collect(gw, at=T):
    provider = market(gw, at)
    with synthetic_gateway(gw, at):
        return provider, provider.collect_sofi(fees_usd=Decimal("0.20"))


# --- provider authenticity ----------------------------------------------------

def test_quote_and_fx_come_from_sim_infoprices_and_verify_only_for_the_reader():
    gw = gateway()
    provider, evidence = collect(gw)
    assert evidence.quote.price == Decimal("41.0") and evidence.quote.provider == "saxo-sim-infoprices"
    assert evidence.fx.usd_per_eur == Decimal("1.1000")
    assert (evidence.quote_origin, evidence.fx_origin) == (EvidenceOrigin.AUTHENTICATED_PROVIDER,) * 2
    price_urls = [u for u in gw.urls if "/trade/v1/infoprices" in u]
    assert len(price_urls) == 2 and all(u.startswith("https://gateway.saxobank.com/sim/openapi/")
                                        for u in gw.urls)
    assert any("AssetType=Stock&Uic=23241352" in u for u in price_urls)
    assert any("AssetType=FxSpot&Uic=21" in u for u in price_urls)
    with clock(T):
        assert provider.verify(evidence)
        other_reader = market(gateway(), T)
        assert not other_reader.verify(evidence)                     # never read it itself


def test_altered_or_hand_built_market_evidence_is_rejected():
    provider, evidence = collect(gateway())
    altered_quote = evidence.quote.model_copy(update={"price": Decimal("30")})
    variants = [
        ExecutionEvidence(altered_quote, evidence.fx, evidence.observed_at, evidence.max_age,
                          evidence.spread_usd, evidence.fees_usd, evidence.fx_fee_usd,
                          EvidenceOrigin.AUTHENTICATED_PROVIDER, EvidenceOrigin.AUTHENTICATED_PROVIDER),
        ExecutionEvidence(evidence.quote, evidence.fx, evidence.observed_at, evidence.max_age,
                          evidence.spread_usd, evidence.fees_usd, evidence.fx_fee_usd),  # fixture origin
    ]
    with clock(T):
        assert all(not provider.verify(v) for v in variants)
    with clock(T + timedelta(minutes=3)):
        assert not provider.verify(evidence)                          # no longer fresh


@pytest.mark.parametrize("stock, fx, message", [
    (stock_price(Uic=211), None, "different instrument"),
    (stock_price(AssetType="CfdOnStock"), None, "different instrument"),
    (stock_price(quote={"DelayedByMinutes": 15}), None, "delayed"),
    (stock_price(quote={"PriceTypeAsk": "Indicative"}), None, "not tradable"),
    (stock_price(quote={"ErrorCode": "NoAccess"}), None, "unavailable"),
    (stock_price(quote={"Bid": 42}), None, "bid/ask"),
    (stock_price(quote={"MarketState": "Closed"}), None, "regular session"),
    (stock_price(DisplayAndFormat={"Currency": "EUR"}), None, "USD"),
    (stock_price(LastUpdated=iso(T - timedelta(minutes=3))), None, "stale"),
    (stock_price(LastUpdated=iso(T + timedelta(minutes=1))), None, "future"),
    (stock_price(LastUpdated="2026-10-19T13:59:50"), None, "timezone"),
    (None, fx_price(Uic=22), "different instrument"),
    (None, fx_price(quote={"PriceTypeBid": "OldIndicative"}), "not tradable"),
    (None, fx_price(LastUpdated=iso(T - timedelta(minutes=5))), "stale"),
])
def test_untradable_delayed_stale_or_swapped_prices_fail_closed(stock, fx, message):
    with pytest.raises(SimEvidenceError, match=message):
        collect(gateway(stock=stock, fx=fx))


def test_only_approved_instruments_and_pair_are_read():
    gw = gateway()
    provider = market(gw)
    with synthetic_gateway(gw, T):
        before = len(gw.urls)
        with pytest.raises(SimEvidenceError, match="not approved"):
            provider.quote("AAPL")
        with pytest.raises(SimEvidenceError, match="EUR/USD"):
            provider.fx("GBP/USD")
        assert len(gw.urls) == before                                 # refused before any read


class SubclassedClient(SaxoSimClient):
    def get(self, path):
        return {}


def test_market_and_account_evidence_need_the_real_client_and_a_verified_scope():
    gw = gateway()
    with synthetic_gateway(gw, T):
        client, scope = authenticated(gw)
        unsealed = SaxoAccountScope(scope.account_id, scope.account_key, scope.client_key)
        for bad_client, bad_scope in ((SubclassedClient(), scope), (client, unsealed),
                                      (object(), scope)):
            with pytest.raises(SimEvidenceError):
                SaxoSimMarketEvidence(bad_client, bad_scope)   # type: ignore[arg-type]
            with pytest.raises(SimEvidenceError):
                collect_account_evidence(bad_client, bad_scope)   # type: ignore[arg-type]


# --- evidence cannot be swapped into another account's order -------------------------

@pytest.fixture
def registered_saxo_verifier(monkeypatch):
    """Test-only registration; the shipped registry stays empty until Stage 2 is approved."""
    monkeypatch.setattr(submission, "TRUSTED_MARKET_VERIFIER_TYPES", (SaxoSimMarketEvidence,))


def prepare(monkeypatch, provider, evidence, **overrides):
    with synthetic_gateway(gateway(), T):
        scope = authenticated(gateway())[1]
    kwargs = dict(order_key="sofi-1", portfolio_id="tradingagents", evidence=evidence,
                  precheck=sealed_precheck(monkeypatch), account_scope=scope,
                  expected_account_id="approved", book_cash_eur=Decimal("1000"), now=T,
                  market_verifier=provider)
    kwargs.update(overrides)
    with clock(T):
        return prepare_sofi_request(**kwargs)


def test_sim_market_evidence_prepares_a_request_offline(monkeypatch, registered_saxo_verifier):
    provider, evidence = collect(gateway())
    request = prepare(monkeypatch, provider, evidence)
    assert request.is_prepared() and request.fx_provider == "saxo-sim-infoprices"
    assert request.expected_price_usd == Decimal("41.0")
    assert submission.SIM_SUBMISSION_RELEASED is False           # preparing is not submitting


def test_market_evidence_from_another_account_cannot_prepare_this_order(monkeypatch,
                                                                       registered_saxo_verifier):
    _, evidence = collect(gateway())
    other_provider, other_evidence = collect(gateway("another-account"))
    with pytest.raises(SubmissionBlocked, match="different Saxo account"):
        prepare(monkeypatch, other_provider, other_evidence)
    with pytest.raises(SubmissionBlocked, match="different Saxo account"):
        prepare(monkeypatch, other_provider, evidence)
    same_account_other_login, _ = collect(gateway(client_key="another-client"))
    with pytest.raises(SubmissionBlocked, match="different Saxo account"):
        prepare(monkeypatch, same_account_other_login, evidence)


def test_shipped_registry_still_refuses_the_sim_verifier(monkeypatch):
    provider, evidence = collect(gateway())
    assert submission.TRUSTED_MARKET_VERIFIER_TYPES == ()
    with pytest.raises(SubmissionBlocked, match="no registered market-data verifier"):
        prepare(monkeypatch, provider, evidence)


def test_evaluator_stage2_account_gate_needs_sealed_fresh_evidence():
    from dataclasses import replace

    from sidedeck.application.saxo_p4_acceptance import evaluate
    from sim_gateway_fake import read_evidence

    evidence = read_evidence(SyntheticGateway("approved"), T)
    gates, decision = evaluate(account_evidence=evidence, now=T + timedelta(minutes=1))
    status = {gate.name: gate.status for gate in gates}
    assert status["STAGE2_SIM_ACCOUNT_EVIDENCE"] == "PASS"
    assert status["SIM_RECONCILIATION_EVIDENCE_BOUND"] == "PASS" and decision == "NO-GO"
    for bad, when in ((replace(evidence, cash_balance_eur=Decimal("1")), T + timedelta(minutes=1)),
                      (evidence, T + timedelta(minutes=6))):
        gates, _ = evaluate(account_evidence=bad, now=when)
        assert {g.name: g.status for g in gates}["STAGE2_SIM_ACCOUNT_EVIDENCE"] == "MISSING"
