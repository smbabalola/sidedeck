"""Offline SD-108 broker adapter coverage."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from sidedeck.application.sd074_trusted_inputs import (
    InputVerifier, NonceStore, SourceRegistry, SourceSigner, TrustedSource,
)
from sidedeck.application.sd108_broker_adapters import (
    BrokerAdapterError, EtoroDemoQuoteAdapter, EtoroDemoReconciliationAdapter,
    response_sha256,
)
from sidedeck.domain.etoro_demo_orders import (
    CloseAcceptance, DemoCloseRequest, DemoOpenRequest,
)

NOW = datetime(2026, 10, 26, 15, 0, tzinfo=timezone.utc)
REQUEST = DemoOpenRequest("12345678-1234-4567-8123-123456789012", 1004,
                          Decimal("0.1"), Decimal("500.00"))
QUOTE_SOURCE = TrustedSource("quotes", "broker_quotes", b"q" * 40)
RECON_SOURCE = TrustedSource("recon", "broker_reconciliation", b"r" * 40)


def lookup(*, status: int = 3, executions: list[dict] | None = None) -> dict:
    return {"orderId": 77, "action": "open", "transaction": "buy",
            "status": {"id": status, "errorCode": 0},
            "asset": {"instrumentId": 1004, "leverage": 1, "side": "long"},
            "positionExecutions": executions if executions is not None else [{
                "positionId": 88, "state": "open", "remainingUnits": 0.1,
                "openingData": {"orderId": 77, "units": 0.1, "avgPrice": 499.5,
                                 "fees": 0.01}}]}


def test_quote_adapter_seals_strict_normalized_payload():
    signer = SourceSigner(QUOTE_SOURCE, lambda: NOW)
    raw = {"results": [{"instrumentId": 1004, "bid": 499.4, "ask": 499.5,
                         "date": NOW.isoformat(), "quoteType": "realtime"}]}
    envelope = EtoroDemoQuoteAdapter(signer, canonical_id="US:XNAS:MSFT").seal(
        raw, instrument_id=1004, now=NOW)
    nonces = NonceStore(Path(":memory:"))
    quote = InputVerifier(SourceRegistry([QUOTE_SOURCE]), nonces, clock=lambda: NOW).quote(envelope)
    assert quote.canonical_id == "US:XNAS:MSFT"
    assert quote.bid == Decimal("499.4") and quote.ask == Decimal("499.5")


def test_quote_adapter_rejects_stale_and_wrong_instrument():
    signer = SourceSigner(QUOTE_SOURCE, lambda: NOW)
    raw = {"results": [{"instrumentId": 1004, "bid": 499.4, "ask": 499.5,
                         "date": NOW.isoformat(), "quoteType": "realtime"}]}
    adapter = EtoroDemoQuoteAdapter(signer, canonical_id="US:XNAS:MSFT")
    with pytest.raises(BrokerAdapterError, match="pilot instrument"):
        adapter.seal(raw, instrument_id=1005, now=NOW)
    with pytest.raises(BrokerAdapterError, match="stale"):
        adapter.seal(raw, instrument_id=1004, now=NOW + timedelta(seconds=61))


def test_reconciliation_binds_reference_and_lookup_digest():
    signer = SourceSigner(RECON_SOURCE, lambda: NOW)
    raw = lookup()
    envelope = EtoroDemoReconciliationAdapter(signer).seal_open_lookup(
        raw, request=REQUEST, observed_at=NOW)
    nonces = NonceStore(Path(":memory:"))
    evidence = InputVerifier(SourceRegistry([RECON_SOURCE]), nonces,
                             clock=lambda: NOW).fill(envelope)
    assert evidence.reference == REQUEST.reference_id.replace("-", "")
    assert evidence.broker_order_id == "77"
    assert evidence.units == Decimal("0.1")
    assert evidence.price == Decimal("499.5")
    assert evidence.lookup_sha256 == response_sha256(raw)


def test_partial_fill_is_bound_to_one_position_and_multiple_positions_halt():
    signer = SourceSigner(RECON_SOURCE, lambda: NOW)
    adapter = EtoroDemoReconciliationAdapter(signer)
    partial = lookup(status=5, executions=[
        {"positionId": 88, "state": "open", "remainingUnits": 0.04,
         "openingData": {"orderId": 77, "units": 0.06, "avgPrice": 499,
                          "fees": 0}},
    ])
    verifier = InputVerifier(SourceRegistry([RECON_SOURCE]), NonceStore(Path(":memory:")),
                             clock=lambda: NOW)
    evidence = verifier.fill(adapter.seal_order_lookup(
        partial, request=REQUEST, observed_at=NOW))
    assert evidence.outcome == "PARTIALLY_FILLED"
    assert evidence.units == Decimal("0.06")
    assert evidence.price == Decimal("499")
    assert evidence.broker_position_id == "88"

    multiple = lookup(status=5, executions=[
        {"positionId": 88, "state": "open", "remainingUnits": 0.04,
         "openingData": {"orderId": 77, "units": 0.06, "avgPrice": 499,
                          "fees": 0}},
        {"positionId": 89, "state": "open", "remainingUnits": 0.02,
         "openingData": {"orderId": 77, "units": 0.04, "avgPrice": 500,
                          "fees": 0}},
    ])
    bound = adapter.seal_order_lookup(multiple, request=REQUEST, observed_at=NOW)
    assert verifier.fill(bound).outcome == "UNRESOLVED"

    unresolved = lookup(status=2, executions=[])
    envelope = adapter.seal_order_lookup(unresolved, request=DemoOpenRequest(
        "22345678-1234-4567-8123-123456789012", 1004, Decimal("0.1"), Decimal("500")),
        observed_at=NOW)
    assert verifier.fill(envelope).outcome == "UNRESOLVED"


def test_open_acceptance_is_validated_but_is_not_a_fill():
    adapter = EtoroDemoReconciliationAdapter(SourceSigner(RECON_SOURCE, lambda: NOW))
    acceptance = adapter.parse_open_acceptance(
        {"orderId": 77, "referenceId": REQUEST.reference_id}, request=REQUEST)
    assert acceptance.order_id == 77
    with pytest.raises(BrokerAdapterError, match="does not echo"):
        adapter.parse_open_acceptance(
            {"orderId": 77, "referenceId": "22345678-1234-4567-8123-123456789012"},
            request=REQUEST)


def test_malformed_lookup_is_sealed_unresolved_with_accepted_order_binding():
    adapter = EtoroDemoReconciliationAdapter(SourceSigner(RECON_SOURCE, lambda: NOW))
    raw = {"orderId": 999, "status": "unexpected"}
    envelope = adapter.seal_open_lookup_or_unresolved(
        raw, request=REQUEST, observed_at=NOW, accepted_order_id=77)
    evidence = InputVerifier(SourceRegistry([RECON_SOURCE]), NonceStore(Path(":memory:")),
                             clock=lambda: NOW).fill(envelope)
    assert evidence.outcome == "UNRESOLVED"
    assert evidence.broker_order_id == "77"
    assert evidence.lookup_sha256 == response_sha256(raw)


def test_close_info_never_invents_fill_price():
    adapter = EtoroDemoReconciliationAdapter(SourceSigner(RECON_SOURCE, lambda: NOW))
    request = DemoCloseRequest(REQUEST.reference_id, 88, 1004)
    acceptance = CloseAcceptance(order_id=91, position_id=88)
    raw = {"orderID": 91, "statusID": 3, "positions": [{"positionID": 88,
                                                              "units": 0.1}]}
    envelope = adapter.seal_close_info(raw, request=request, acceptance=acceptance,
                                       observed_at=NOW, planned_bid=Decimal("499.4"))
    evidence = InputVerifier(SourceRegistry([RECON_SOURCE]), NonceStore(Path(":memory:")),
                             clock=lambda: NOW).fill(envelope)
    assert evidence.outcome == "UNRESOLVED"
    assert evidence.units == Decimal("0") and evidence.price == Decimal("0")
    assert evidence.broker_position_id == "88"


def test_terminal_close_rejection_can_be_reconciled_as_no_fill():
    adapter = EtoroDemoReconciliationAdapter(SourceSigner(RECON_SOURCE, lambda: NOW))
    request = DemoCloseRequest(REQUEST.reference_id, 88, 1004)
    acceptance = CloseAcceptance(order_id=91, position_id=88)
    envelope = adapter.seal_close_info(
        {"orderID": 91, "statusID": 4, "positions": []}, request=request,
        acceptance=acceptance, observed_at=NOW, planned_bid=Decimal("499.4"))
    evidence = InputVerifier(SourceRegistry([RECON_SOURCE]), NonceStore(Path(":memory:")),
                             clock=lambda: NOW).fill(envelope)
    assert evidence.outcome == "NOT_FILLED"
