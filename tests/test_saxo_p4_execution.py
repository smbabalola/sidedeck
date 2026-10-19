from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sidedeck.application.saxo_execution_history import fetch_history, order_history_path, parse_executions
from sidedeck.application.saxo_market_data import EvidenceOrigin, ExecutionEvidence, FxSnapshot
from sidedeck.infrastructure.saxo_precheck import PrecheckEvidence
from sidedeck.application.saxo_sim_submission import (
    ExecutionAuthorization, SaxoSimSubmitter, SubmissionBlocked, authorize_execution,
    prepare_sofi_request,
)
from sidedeck.domain.contracts import MarketSnapshot, PriceType, Session
from sidedeck.infrastructure.saxo_account_scope import SaxoAccountScope
from sidedeck.infrastructure.saxo_submit_transport import SaxoSimSubmitTransport

NOW = datetime(2026, 10, 19, 14, 0, tzinfo=timezone.utc)


def evidence() -> ExecutionEvidence:
    quote = MarketSnapshot(
        instrument_id="US:SOFI", ticker="SOFI", provider="licensed-feed",
        price_type=PriceType.QUOTE, price=Decimal("41"),
        market_timestamp=NOW, ingestion_timestamp=NOW,
        session=Session.REGULAR, quality="firm-but-not-broker-executable",
    )
    fx = FxSnapshot("licensed-fx", "EUR/USD", Decimal("1.10"), NOW, NOW, "firm")
    return ExecutionEvidence(quote, fx, NOW, timedelta(minutes=2),
                             Decimal("0.10"), Decimal("0.20"), Decimal("0"),
                             quote_origin=EvidenceOrigin.AUTHENTICATED_PROVIDER,
                             fx_origin=EvidenceOrigin.AUTHENTICATED_PROVIDER)


def precheck() -> PrecheckEvidence:
    return PrecheckEvidence("Ok", "broker_precheck_validated", Decimal("41.03"),
                            "EUR", Decimal("37.30"), "USD", Decimal("41.03"),
                            "EUR", Decimal("1.10"))


def test_market_and_fx_evidence_rejects_stale_or_wrong_direction():
    with pytest.raises(ValueError, match="stale"):
        ExecutionEvidence(evidence().quote, evidence().fx,
                          NOW + timedelta(minutes=3), timedelta(minutes=2),
                          Decimal("0"), Decimal("0"), Decimal("0"))
    with pytest.raises(ValueError, match="EUR/USD"):
        FxSnapshot("fx", "USD/EUR", Decimal("0.9"), NOW, NOW, "firm")


class Pages:
    def __init__(self):
        self.paths: list[str] = []

    def get(self, path: str):
        self.paths.append(path)
        if path == "/first":
            return {"Data": [{"ExecutionId": "a"}], "__next": "/second"}
        return {"Data": [{"ExecutionId": "b"}], "__count": 2}


def test_execution_history_paginates_and_parses_only_fill_evidence():
    pages = Pages()
    rows = fetch_history(pages, "/first")
    assert pages.paths == ["/first", "/second"]
    parsed = parse_executions((
        {"AccountId": "22866064", "OrderId": "o", "ExternalReference": "k",
         "ExecutionId": "fill-1", "Status": "FinalFill", "FillAmount": 1,
         "ExecutionPrice": "41", "Fees": "0.2",
         "ExecutionTime": "2026-10-19T14:00:00Z"},
        {"AccountId": "22866064", "OrderId": "o", "ExternalReference": "k",
         "Status": "Placed"},
    ), account_id="22866064", order_id="o", external_reference="k",
        instrument_currency="USD", account_currency="EUR",
        price_currency="USD", fees_currency="EUR")
    assert len(rows) == 2 and parsed[0].execution_id == "fill-1"
    assert parsed[0].fees == Decimal("0.2")


def test_history_rejects_loop_duplicate_and_cross_account():
    class Loop:
        def get(self, path: str):
            return {"Data": [], "__next": path}
    with pytest.raises(ValueError, match="loop"):
        fetch_history(Loop(), "/same")
    with pytest.raises(ValueError, match="mismatch"):
        parse_executions(({"AccountId": "wrong"},), account_id="22866064",
                         order_id="o", external_reference="k",
                         instrument_currency="USD", account_currency="EUR",
                         price_currency="USD", fees_currency="EUR")


def test_official_history_path_and_sim_payload_boundary():
    scope = SaxoAccountScope("approved", "opaque-account-key", "client-key")
    path = order_history_path(scope, "broker-1")
    assert "EntryType=All" in path and "OrderId=broker-1" in path
    payload = {
        "AccountKey": "opaque-account-key", "Uic": 23241352, "AssetType": "Stock",
        "BuySell": "Buy", "Amount": 1, "OrderType": "Market",
        "OrderDuration": {"DurationType": "DayOrder"}, "ExternalReference": "sofi-1",
    }
    SaxoSimSubmitTransport.validate_payload(payload)
    with pytest.raises(RuntimeError, match="disabled"):
        SaxoSimSubmitTransport().submit(payload)


def test_submission_is_disabled_and_approval_is_exactly_bound(tmp_path):
    request = prepare_sofi_request(order_key="sofi-1", portfolio_id="tradingagents",
                                   evidence=evidence(), precheck=precheck(),
                                   account_scope=SaxoAccountScope("approved", "opaque-account-key", "client"),
                                   expected_account_id="approved",
                                   portfolio_cash_usd=Decimal("1000"), now=NOW)
    submitter = SaxoSimSubmitter(str(tmp_path / "orders.sqlite"))
    approval = authorize_execution(request, authorization_id="approval-1",
                                   issued_by="operator", expires_at=NOW + timedelta(minutes=1))
    with pytest.raises(SubmissionBlocked, match="disabled"):
        submitter.submit(request, approval, now=NOW)
    class Acknowledged:
        def submit(self, payload):
            return {"OrderId": "broker-1"}

    with pytest.raises(SubmissionBlocked, match="authorization"):
        SaxoSimSubmitter(str(tmp_path / "enabled.sqlite"), network_enabled=True,
                         transport=Acknowledged()).submit(
                             request, ExecutionAuthorization("x", "operator", "wrong",
                             "tradingagents", "SOFI", 23241352, "Buy", 1, "Market",
                             "wrong", "wrong", "wrong", NOW), now=NOW)


def test_injected_sim_transport_is_single_attempt_and_uncertain(tmp_path):
    class Timeout:
        calls = 0

        def submit(self, payload):
            self.calls += 1
            raise TimeoutError("simulated")

    request = prepare_sofi_request(order_key="sofi-2", portfolio_id="ai-trading",
                                   evidence=evidence(), precheck=precheck(),
                                   account_scope=SaxoAccountScope("approved", "opaque-account-key", "client"),
                                   expected_account_id="approved",
                                   portfolio_cash_usd=Decimal("1000"), now=NOW)
    transport = Timeout()
    submitter = SaxoSimSubmitter(str(tmp_path / "orders.sqlite"), transport=transport,
                                 network_enabled=True)
    approval = authorize_execution(request, authorization_id="approval-2",
                                   issued_by="operator", expires_at=NOW + timedelta(minutes=1))
    with pytest.raises(SubmissionBlocked, match="uncertain"):
        submitter.submit(request, approval, now=NOW)
    with pytest.raises(SubmissionBlocked, match="already claimed"):
        submitter.submit(request, approval, now=NOW)
    assert transport.calls == 1
