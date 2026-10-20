import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sidedeck.application.saxo_execution_history import fetch_history, order_history_path, parse_executions, read_order_history, validate_continuation
from sidedeck.application.saxo_market_data import EvidenceOrigin, ExecutionEvidence, FxSnapshot
import hashlib
import sqlite3

from sidedeck.application import saxo_sim_submission as submission_module
from sidedeck.application.saxo_order_lifecycle import lifecycle_state
from sidedeck.infrastructure.saxo_precheck import PrecheckEvidence, parse_precheck, precheck_payload, run_sim_precheck
from sidedeck.application.saxo_sim_submission import (
    ExecutionAuthorization, SaxoSimSubmitter, SubmissionBlocked, accept_operator_approval,
    approval_material, prepare_sofi_request, reconcile_uncertain_submission,
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


# Economically coherent synthetic broker precheck: $41 at 1.10 USD/EUR.
PRECHECK_BODY = {"PreCheckResult": "Ok", "EstimatedCashRequired": "37.55",
                 "EstimatedCashRequiredCurrency": "EUR", "EstimatedTotalCost": "0.30",
                 "EstimatedTotalCostCurrency": "USD", "EstimatedTotalCostInAccountCurrency": "0.27",
                 "EstimatedTotalCostInAccountCurrencyCurrency": "EUR",
                 "InstrumentToAccountConversionRate": "0.9091"}
SCOPE = SaxoAccountScope("approved", "opaque-account-key", "client")


class FakeReadOnlySimClient:
    """Synthetic /port/v1/users/me and /port/v1/accounts/me responses (no network)."""

    def user(self):
        return {"ClientKey": "client"}

    def accounts(self):
        return {"Data": [{"AccountId": "approved", "AccountKey": "opaque-account-key",
                          "Active": True}]}


def authenticated_scope() -> SaxoAccountScope:
    from sidedeck.infrastructure.saxo_account_scope import verified_scope
    return verified_scope(FakeReadOnlySimClient(), "approved")  # type: ignore[arg-type]


def precheck(body=None) -> PrecheckEvidence:
    """Unsealed parse of a synthetic body, as a fixture or hand-built object would be."""
    return parse_precheck(body or PRECHECK_BODY, instrument_currency="USD", account_currency="EUR",
                          request_payload=precheck_payload(SCOPE, uic=23241352),
                          account_id="approved", collected_at=NOW)


def sealed_precheck(monkeypatch, body=None) -> PrecheckEvidence:
    """Drive the real SIM precheck transport against a fake opener (no network)."""
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _limit):
            return json.dumps(body or PRECHECK_BODY).encode()

    class Opener:
        def open(self, request, timeout):
            assert request.full_url.endswith("/sim/openapi/trade/v2/orders/precheck")
            return Response()

    monkeypatch.setenv("SAXO_SIM_ACCESS_TOKEN", "fixture-token")
    monkeypatch.setattr("sidedeck.infrastructure.saxo_precheck.build_opener", lambda *_: Opener())
    return run_sim_precheck(SCOPE, uic=23241352, account_currency="EUR", clock=lambda: NOW)


def operator_signature(material: str, principal: str) -> str:
    """Stands in for the human's out-of-band signature; not reachable from SideDeck code."""
    return "fixture-sig:" + hashlib.sha256((principal + "|" + material).encode()).hexdigest()


class TrustedVerifier:
    """Verify-only fixture verifier; it has no way to create an approval."""

    def verify(self, attestation, material, principal):
        return attestation == operator_signature(material, principal)


class TrustedMarketVerifier:
    def verify(self, market_evidence):
        return market_evidence.quote_origin is EvidenceOrigin.AUTHENTICATED_PROVIDER


@pytest.fixture(autouse=True)
def registered_fixture_market_verifier(monkeypatch):
    """Test-only: registers the fixture verifier type. The shipped registry is empty."""
    monkeypatch.setattr(submission_module, "TRUSTED_MARKET_VERIFIER_TYPES", (TrustedMarketVerifier,))


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
         "Uic": 23241352, "BuySell": "Buy",
         "ExecutionPrice": "41", "Fees": "0.2",
         "ExecutionTime": "2026-10-19T14:00:00Z"},
        {"AccountId": "22866064", "OrderId": "o", "ExternalReference": "k",
         "Status": "Placed"},
    ), account_id="22866064", order_id="o", external_reference="k",
        instrument_currency="USD", account_currency="EUR",
        price_currency="USD", fees_currency="EUR", authorized_quantity=Decimal("1"),
        expected_uic=23241352)
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
                         price_currency="USD", fees_currency="EUR", authorized_quantity=Decimal("1"),
        expected_uic=23241352)


def test_history_cursor_cannot_change_scope():
    scope = SaxoAccountScope("approved", "opaque-account-key", "client")
    good = order_history_path(scope, "broker-1")
    assert validate_continuation(good, scope, "broker-1") == good
    with pytest.raises(ValueError, match="scope"):
        validate_continuation(good.replace("broker-1", "broker-2"), scope, "broker-1")
    with pytest.raises(ValueError, match="boundary"):
        validate_continuation("https://evil.example/cs/v1/audit/orderactivities", scope, "broker-1")


def test_actual_allowlisted_sim_client_retrieves_two_pages(monkeypatch):
    scope = SaxoAccountScope("approved", "acct-key", "client-key")
    first = order_history_path(scope, "broker-1")
    second = first + "&%24skip=100"
    responses = {
        first: {"Data": [{"OrderId": "broker-1"}], "__next": second},
        second: {"Data": [{"OrderId": "broker-1"}], "__count": 2},
    }

    class Response:
        status = 200
        def __init__(self, body):
            self.body = body
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, _limit):
            return json.dumps(self.body).encode()

    class Opener:
        def open(self, request, timeout):
            return Response(responses[request.full_url.removeprefix(
                "https://gateway.saxobank.com/sim/openapi")])

    monkeypatch.setenv("SAXO_SIM_ACCESS_TOKEN", "fixture-token")
    monkeypatch.setattr("sidedeck.infrastructure.saxo_sim.build_opener", lambda *_: Opener())
    from sidedeck.infrastructure.saxo_sim import SaxoSimClient
    assert len(read_order_history(SaxoSimClient(), scope, "broker-1")) == 2


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


def prepared(monkeypatch, *, order_key="sofi-1", portfolio_id="tradingagents", now=NOW,
             **overrides):
    kwargs = dict(order_key=order_key, portfolio_id=portfolio_id, evidence=evidence(),
                  precheck=sealed_precheck(monkeypatch), account_scope=authenticated_scope(),
                  expected_account_id="approved", portfolio_cash_usd=Decimal("1000"), now=now,
                  market_verifier=TrustedMarketVerifier())
    kwargs.update(overrides)
    return prepare_sofi_request(**kwargs)


def approve(request, *, authorization_id="approval-1", approver="operator",
            expires_at=NOW + timedelta(minutes=5), now=NOW, verifier=None, signature=None):
    material = approval_material(request, authorization_id=authorization_id,
                                 approver=approver, expires_at=expires_at)
    return accept_operator_approval(
        request, authorization_id=authorization_id, approver=approver, expires_at=expires_at,
        attestation=signature or operator_signature(material, approver),
        verifier=verifier or TrustedVerifier(), now=now)


@pytest.fixture
def released(monkeypatch):
    """Simulates a future approved release inside a test only."""
    monkeypatch.setattr(submission_module, "SIM_SUBMISSION_RELEASED", True)


class Acknowledged:
    def __init__(self, response=None):
        self.calls = 0
        self.response = response or {"OrderId": "broker-1"}

    def submit(self, payload):
        self.calls += 1
        return self.response


class Timeout:
    def __init__(self):
        self.calls = 0

    def submit(self, payload):
        self.calls += 1
        raise TimeoutError("simulated")


def auth_row(db, order_key="sofi-1"):
    with sqlite3.connect(db) as connection:
        return connection.execute("SELECT status, broker_order_id FROM saxo_execution_authorization "
                                  "WHERE order_key=?", (order_key,)).fetchone()


def test_submission_is_disabled_by_release_gate_even_when_everything_else_is_on(tmp_path, monkeypatch):
    request = prepared(monkeypatch)
    transport = Acknowledged()
    submitter = SaxoSimSubmitter(str(tmp_path / "orders.sqlite"), network_enabled=True,
                                 transport=transport, approval_verifier=TrustedVerifier())
    with pytest.raises(SubmissionBlocked, match="NO-GO"):
        submitter.submit(request, approve(request), now=NOW)
    assert transport.calls == 0
    assert submission_module.SIM_SUBMISSION_RELEASED is False


def test_submission_is_disabled_and_approval_is_exactly_bound(tmp_path, monkeypatch, released):
    request = prepared(monkeypatch)
    approval = approve(request)
    with pytest.raises(SubmissionBlocked, match="disabled"):
        SaxoSimSubmitter(str(tmp_path / "orders.sqlite"),
                         approval_verifier=TrustedVerifier()).submit(request, approval, now=NOW)
    forged = ExecutionAuthorization("x", "operator", "sidedeck-automation", "sofi-1", "wrong",
                                    "tradingagents", "SOFI", 23241352, "Buy", 1, "Market",
                                    "wrong", "wrong", "wrong", NOW + timedelta(minutes=1))
    with pytest.raises(SubmissionBlocked, match="authorization"):
        SaxoSimSubmitter(str(tmp_path / "enabled.sqlite"), network_enabled=True,
                         transport=Acknowledged(), approval_verifier=TrustedVerifier()).submit(
                             request, forged, now=NOW)


def test_fixture_labels_cannot_upgrade_market_data_or_create_approval(monkeypatch):
    with pytest.raises(SubmissionBlocked, match="attestation"):
        prepared(monkeypatch, market_verifier=None)
    request = prepared(monkeypatch)
    with pytest.raises(SubmissionBlocked, match="verifier"):
        accept_operator_approval(request, authorization_id="no-trust", approver="operator",
                                 expires_at=NOW + timedelta(minutes=1), attestation="x",
                                 verifier=None, now=NOW)


def test_self_attesting_verifier_cannot_approve_its_own_request(tmp_path, monkeypatch, released):
    class SelfAttesting(TrustedVerifier):
        def attest(self, material):
            return "self"

    request = prepared(monkeypatch)
    with pytest.raises(SubmissionBlocked, match="cannot authorize its own"):
        approve(request, verifier=SelfAttesting())
    transport = Acknowledged()
    with pytest.raises(SubmissionBlocked, match="cannot authorize its own"):
        SaxoSimSubmitter(str(tmp_path / "o.sqlite"), network_enabled=True, transport=transport,
                         approval_verifier=SelfAttesting()).submit(request, approve(request), now=NOW)
    assert transport.calls == 0


def test_requester_cannot_approve_and_signature_is_bound_to_exact_order(monkeypatch):
    request = prepared(monkeypatch)
    with pytest.raises(SubmissionBlocked, match="requesting principal"):
        approve(request, approver="sidedeck-automation")
    other = prepared(monkeypatch, order_key="sofi-other")
    expires = NOW + timedelta(minutes=5)
    signature_for_other = operator_signature(
        approval_material(other, authorization_id="approval-1", approver="operator",
                          expires_at=expires), "operator")
    with pytest.raises(SubmissionBlocked, match="signature is not valid"):
        approve(request, signature=signature_for_other)
    operator_sig = operator_signature(
        approval_material(request, authorization_id="approval-1", approver="operator",
                          expires_at=expires), "operator")
    with pytest.raises(SubmissionBlocked, match="signature is not valid"):
        approve(request, approver="intruder", signature=operator_sig)


def test_approval_expiry_window_and_stale_evidence_are_enforced(tmp_path, monkeypatch, released):
    request = prepared(monkeypatch)
    with pytest.raises(SubmissionBlocked, match="expiry"):
        approve(request, expires_at=NOW + timedelta(hours=1))
    with pytest.raises(SubmissionBlocked, match="expiry"):
        approve(request, expires_at=NOW)
    submitter = SaxoSimSubmitter(str(tmp_path / "o.sqlite"), network_enabled=True,
                                 transport=Acknowledged(), approval_verifier=TrustedVerifier())
    approval = approve(request, expires_at=NOW + timedelta(minutes=10))
    with pytest.raises(SubmissionBlocked, match="stale"):
        submitter.submit(request, approval, now=NOW + timedelta(minutes=6))
    short = approve(request, authorization_id="a2", expires_at=NOW + timedelta(minutes=1))
    with pytest.raises(SubmissionBlocked, match="expired"):
        submitter.submit(request, short, now=NOW + timedelta(minutes=2))


def test_stale_quote_cannot_pass_with_a_permissive_bundle_max_age(monkeypatch):
    old = NOW - timedelta(minutes=10)
    quote = MarketSnapshot(instrument_id="US:SOFI", ticker="SOFI", provider="licensed-feed",
                           price_type=PriceType.QUOTE, price=Decimal("41"), market_timestamp=old,
                           ingestion_timestamp=old, session=Session.REGULAR, quality="firm")
    fx = FxSnapshot("licensed-fx", "EUR/USD", Decimal("1.10"), NOW, NOW, "firm")
    permissive = ExecutionEvidence(quote, fx, NOW, timedelta(days=1), Decimal("0.10"),
                                   Decimal("0.20"), Decimal("0"),
                                   quote_origin=EvidenceOrigin.AUTHENTICATED_PROVIDER,
                                   fx_origin=EvidenceOrigin.AUTHENTICATED_PROVIDER)
    with pytest.raises(SubmissionBlocked, match="stale"):
        prepared(monkeypatch, evidence=permissive)


def test_hand_built_or_fixture_precheck_cannot_authorize(monkeypatch):
    from dataclasses import replace
    assert precheck().reason == "broker_precheck_validated"
    with pytest.raises(SubmissionBlocked, match="SIM precheck transport"):
        prepared(monkeypatch, precheck=precheck())
    sealed = sealed_precheck(monkeypatch)
    assert sealed.is_transport_sealed()
    assert not replace(sealed, estimated_cash_required=Decimal("1.00")).is_transport_sealed()


def test_economically_inconsistent_precheck_is_rejected(monkeypatch):
    inverted = dict(PRECHECK_BODY, InstrumentToAccountConversionRate="1.10",
                    EstimatedTotalCostInAccountCurrency="0.33")
    with pytest.raises(SubmissionBlocked, match="rate disagrees"):
        prepared(monkeypatch, precheck=sealed_precheck(monkeypatch, inverted))
    cheap = dict(PRECHECK_BODY, EstimatedCashRequired="5.00")
    with pytest.raises(SubmissionBlocked, match="cash requirement disagrees"):
        prepared(monkeypatch, precheck=sealed_precheck(monkeypatch, cheap))


def test_acknowledged_order_links_lifecycle_and_fill_posts_end_to_end(tmp_path, monkeypatch, released):
    from sidedeck.application.foundation import initialise_two_portfolios
    from sidedeck.application.saxo_execution_pipeline import SaxoExecutionPipeline
    from sidedeck.domain.contracts import ExperimentManifest

    db = str(tmp_path / "e2e.sqlite")
    request = prepared(monkeypatch)
    transport = Acknowledged()
    submitter = SaxoSimSubmitter(db, network_enabled=True, transport=transport,
                                 approval_verifier=TrustedVerifier())
    assert submitter.submit(request, approve(request), now=NOW) == "broker-1"
    assert lifecycle_state(db, "sofi-1")[:2] == ("ACKNOWLEDGED", "broker-1")
    assert auth_row(db) == ("CONSUMED", "broker-1")
    with pytest.raises(SubmissionBlocked, match="already"):
        submitter.submit(request, approve(request), now=NOW)
    assert transport.calls == 1
    rows = ({"AccountId": "approved", "OrderId": "broker-1", "ExternalReference": "sofi-1",
             "ExecutionId": "fill-1", "Status": "FinalFill", "FillAmount": 1, "Uic": 23241352,
             "BuySell": "Buy", "ExecutionPrice": "41", "Fees": "0.27",
             "ExecutionTime": "2026-10-19T14:00:30Z"},)
    fills = parse_executions(rows, account_id="approved", order_id="broker-1",
                             external_reference="sofi-1", instrument_currency="USD",
                             account_currency="EUR", price_currency="USD", fees_currency="EUR",
                             authorized_quantity=Decimal("1"), expected_uic=23241352)
    ledger = initialise_two_portfolios(ExperimentManifest(
        experiment_id="p4", configuration_revision="r1", created_at=NOW,
        instruments=("US:SOFI",), data_policy="licensed"), NOW)
    applied = SaxoExecutionPipeline(db, ledger).apply_buy_fill(
        fills[0], order_key="sofi-1", portfolio_id="tradingagents", fx=evidence().fx,
        account_id="approved", now=NOW)
    assert applied.fee_usd == Decimal("0.2970")
    assert ledger.replay("tradingagents").positions["US:SOFI"].quantity == Decimal("1")
    assert ledger.replay("ai-trading").cash == Decimal("1000")
    assert lifecycle_state(db, "sofi-1")[0] == "FILLED"


def test_malformed_ack_is_uncertain_and_explicit_error_is_rejected(tmp_path, monkeypatch, released):
    db = str(tmp_path / "ack.sqlite")
    request = prepared(monkeypatch)
    submitter = SaxoSimSubmitter(db, network_enabled=True, transport=Acknowledged({"Status": "ok"}),
                                 approval_verifier=TrustedVerifier())
    with pytest.raises(SubmissionBlocked, match="uncertain"):
        submitter.submit(request, approve(request), now=NOW)
    assert auth_row(db)[0] == "UNKNOWN" and lifecycle_state(db, "sofi-1")[0] == "UNKNOWN"
    second = prepared(monkeypatch, order_key="sofi-2")
    rejecting = SaxoSimSubmitter(db, network_enabled=True,
                                 transport=Acknowledged({"ErrorInfo": {"ErrorCode": "X"}}),
                                 approval_verifier=TrustedVerifier())
    with pytest.raises(SubmissionBlocked, match="rejected"):
        rejecting.submit(second, approve(second, authorization_id="approval-2"), now=NOW)
    assert auth_row(db, "sofi-2")[0] == "REJECTED"
    assert lifecycle_state(db, "sofi-2")[0] == "REJECTED"


def test_authorization_cannot_be_reused_for_another_order(tmp_path, monkeypatch, released):
    db = str(tmp_path / "reuse.sqlite")
    submitter = SaxoSimSubmitter(db, network_enabled=True, transport=Acknowledged(),
                                 approval_verifier=TrustedVerifier())
    first = prepared(monkeypatch)
    submitter.submit(first, approve(first), now=NOW)
    second = prepared(monkeypatch, order_key="sofi-2")
    with pytest.raises(SubmissionBlocked, match="already consumed"):
        submitter.submit(second, approve(second, authorization_id="approval-1"), now=NOW)


def test_injected_sim_transport_is_single_attempt_and_uncertain(tmp_path, monkeypatch, released):
    db = str(tmp_path / "orders.sqlite")
    request = prepared(monkeypatch, order_key="sofi-2", portfolio_id="ai-trading")
    transport = Timeout()
    submitter = SaxoSimSubmitter(db, transport=transport, network_enabled=True,
                                 approval_verifier=TrustedVerifier())
    approval = approve(request, authorization_id="approval-2")
    with pytest.raises(SubmissionBlocked, match="uncertain"):
        submitter.submit(request, approval, now=NOW)
    with pytest.raises(SubmissionBlocked, match="already"):
        submitter.submit(request, approval, now=NOW)
    assert transport.calls == 1
    assert lifecycle_state(db, "sofi-2")[0] == "UNKNOWN"


def test_uncertain_order_is_reconciled_read_only_and_never_resubmitted(tmp_path, monkeypatch, released):
    db = str(tmp_path / "reconcile.sqlite")
    request = prepared(monkeypatch)
    transport = Timeout()
    with pytest.raises(SubmissionBlocked, match="uncertain"):
        SaxoSimSubmitter(db, transport=transport, network_enabled=True,
                         approval_verifier=TrustedVerifier()).submit(request, approve(request), now=NOW)
    assert reconcile_uncertain_submission(db, "sofi-1", account_id="approved",
                                          activity_rows=()) == "NOT_FOUND_REMAINS_UNKNOWN"
    assert lifecycle_state(db, "sofi-1")[0] == "UNKNOWN"
    other_account = ({"ExternalReference": "sofi-1", "AccountId": "other", "OrderId": "b",
                      "Uic": 23241352, "BuySell": "Buy", "Status": "Placed"},)
    with pytest.raises(ValueError, match="different identity"):
        reconcile_uncertain_submission(db, "sofi-1", account_id="approved",
                                       activity_rows=other_account)
    with pytest.raises(ValueError, match="authorized account"):
        reconcile_uncertain_submission(db, "sofi-1", account_id="other", activity_rows=())
    two = tuple({"ExternalReference": "sofi-1", "AccountId": "approved", "OrderId": oid,
                 "Uic": 23241352, "BuySell": "Buy", "Status": "Placed"} for oid in ("b1", "b2"))
    with pytest.raises(ValueError, match="multiple broker orders"):
        reconcile_uncertain_submission(db, "sofi-1", account_id="approved", activity_rows=two)
    found = ({"ExternalReference": "sofi-1", "AccountId": "approved", "OrderId": "broker-9",
              "Uic": 23241352, "BuySell": "Buy", "Status": "Placed"},
             {"ExternalReference": "unrelated", "AccountId": "approved", "OrderId": "x"})
    assert reconcile_uncertain_submission(db, "sofi-1", account_id="approved",
                                          activity_rows=found) == "ACKNOWLEDGED"
    assert lifecycle_state(db, "sofi-1")[:2] == ("ACKNOWLEDGED", "broker-9")
    assert auth_row(db) == ("CONSUMED", "broker-9")
    assert transport.calls == 1


def test_history_rejects_naive_time_wrong_instrument_and_sell_side():
    base = {"AccountId": "a", "OrderId": "o", "ExternalReference": "k", "ExecutionId": "f",
            "Status": "FinalFill", "FillAmount": 1, "Uic": 23241352, "BuySell": "Buy",
            "ExecutionPrice": "41", "Fees": "0", "ExecutionTime": "2026-10-19T14:00:00Z"}
    kwargs = dict(account_id="a", order_id="o", external_reference="k",
                  instrument_currency="USD", account_currency="EUR", price_currency="USD",
                  fees_currency="EUR", authorized_quantity=Decimal("1"), expected_uic=23241352)
    assert parse_executions((base,), **kwargs)[0].occurred_at == "2026-10-19T14:00:00+00:00"
    for change, message in (({"ExecutionTime": "2026-10-19T14:00:00"}, "timezone"),
                            ({"Uic": 211}, "instrument or side"),
                            ({"BuySell": "Sell"}, "instrument or side")):
        with pytest.raises(ValueError, match=message):
            parse_executions((dict(base, **change),), **kwargs)


def test_account_activity_cursor_cannot_widen_scope():
    from sidedeck.application.saxo_execution_history import account_activity_path
    path = account_activity_path(SCOPE)
    assert validate_continuation(path + "&%24skip=100", SCOPE, None)
    with pytest.raises(ValueError, match="scope"):
        validate_continuation(path.replace("opaque-account-key", "other"), SCOPE, None)


def test_offline_acceptance_reports_no_go_with_code_gates_passing(tmp_path, capsys):
    from sidedeck.application import saxo_p4_acceptance
    report = tmp_path / "p4.json"
    assert saxo_p4_acceptance.main(["--offline", "--json", str(report)]) == 0
    out = capsys.readouterr().out
    assert "P4_OFFLINE_CHECK=PASS" in out and "P4_DECISION=NO-GO" in out
    assert "SELF_APPROVAL_REJECTED=PASS" in out and "HAND_BUILT_PRECHECK_REJECTED=PASS" in out
    assert "BROKER_REQUESTS_MADE=0" in out
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["decision"] == "NO-GO" and data["broker_requests_made"] == 0


EXTERNAL_GATES = ("AUTHENTICATED_SIM_ACCOUNT_AND_INSTRUMENT", "CURRENT_SOFI_QUOTE_PROVENANCE",
                  "CURRENT_EURUSD_FX_PROVENANCE", "BROKER_PRECHECK_AND_ACCOUNT_CURRENCY",
                  "EXACT_ORDER_PAYLOAD", "INDEPENDENT_OPERATOR_APPROVAL")


def evaluated(**kwargs):
    from sidedeck.application import saxo_p4_acceptance
    gates, decision = saxo_p4_acceptance.evaluate(now=NOW, **kwargs)
    return {gate.name: (gate.status, gate.detail) for gate in gates}, decision


def full_inputs(monkeypatch, tmp_path):
    """Sealed precheck, the exact evidence object, and a prepared request."""
    sealed = sealed_precheck(monkeypatch)
    market = evidence()
    request = prepared(monkeypatch, precheck=sealed, evidence=market)
    signers = tmp_path / "allowed_signers"
    signers.write_text("operator ssh-ed25519 AAAAplaceholder\n", encoding="utf-8")
    return request, sealed, market, signers


def test_hand_built_or_altered_request_cannot_pass_any_external_gate(monkeypatch, tmp_path):
    from dataclasses import replace
    request, sealed, market, signers = full_inputs(monkeypatch, tmp_path)
    assert request.is_prepared()
    unsealed = replace(request, preparation_seal="")
    altered = replace(request, expected_price_usd=Decimal("1"))  # keeps the old seal
    for candidate in (unsealed, altered):
        assert not candidate.is_prepared()
        status, decision = evaluated(request=candidate, precheck=sealed, evidence=market,
                                     market_verifier=TrustedMarketVerifier(),
                                     authorization=approve(request), allowed_signers=signers)
        assert decision == "NO-GO"
        for name in EXTERNAL_GATES:
            assert status[name][0] == "MISSING", name
        assert "hand-built or altered" in status["EXACT_ORDER_PAYLOAD"][1]


def test_matching_authorization_values_are_not_an_approval(monkeypatch, tmp_path):
    request, sealed, market, signers = full_inputs(monkeypatch, tmp_path)
    fixture_signed = approve(request)  # every field matches; signature is not an operator's
    forged = ExecutionAuthorization(
        "approval-1", "operator", request.requested_by, request.order_key, request.account_id,
        request.portfolio_id, request.ticker, request.uic, "Buy", request.quantity, "Market",
        request.digest(), request.broker_payload_digest(), request.risk_evidence_sha256,
        NOW + timedelta(minutes=5), attestation="-----BEGIN SSH SIGNATURE-----\nAA\n"
        "-----END SSH SIGNATURE-----")
    for authorization in (fixture_signed, forged):
        status, decision = evaluated(request=request, precheck=sealed, evidence=market,
                                     market_verifier=TrustedMarketVerifier(),
                                     authorization=authorization, allowed_signers=signers)
        assert status["INDEPENDENT_OPERATOR_APPROVAL"][0] == "MISSING"
        assert "does not verify" in status["INDEPENDENT_OPERATOR_APPROVAL"][1]
        assert decision == "NO-GO"
    status, _ = evaluated(request=request, precheck=sealed, evidence=market,
                          market_verifier=TrustedMarketVerifier(), authorization=fixture_signed)
    assert status["OPERATOR_VERIFIER_CONFIGURED"][0] == "MISSING"
    assert status["INDEPENDENT_OPERATOR_APPROVAL"][0] == "MISSING"


def test_market_evidence_must_be_reverified_by_a_registered_verifier_type(monkeypatch, tmp_path):
    request, sealed, market, _ = full_inputs(monkeypatch, tmp_path)

    class DuckVerifier:
        def verify(self, market_evidence):
            return True

    class SubclassVerifier(TrustedMarketVerifier):
        pass

    for verifier in (None, DuckVerifier(), SubclassVerifier()):
        status, _ = evaluated(request=request, precheck=sealed, evidence=market,
                              market_verifier=verifier)
        assert status["CURRENT_SOFI_QUOTE_PROVENANCE"] == (
            "MISSING", "no registered market-data verifier type")
    status, _ = evaluated(request=request, precheck=sealed, evidence=evidence(),
                          market_verifier=TrustedMarketVerifier())
    assert "differs from the evidence" in status["CURRENT_EURUSD_FX_PROVENANCE"][1]
    status, _ = evaluated(request=request, precheck=sealed, evidence=market,
                          market_verifier=TrustedMarketVerifier())
    assert status["CURRENT_SOFI_QUOTE_PROVENANCE"][0] == "PASS"
    monkeypatch.setattr(submission_module, "TRUSTED_MARKET_VERIFIER_TYPES", ())
    status, _ = evaluated(request=request, precheck=sealed, evidence=market,
                          market_verifier=TrustedMarketVerifier())
    assert status["CURRENT_SOFI_QUOTE_PROVENANCE"][0] == "MISSING"


def test_precheck_gate_requires_the_sealed_precheck_bound_to_the_request(monkeypatch, tmp_path):
    from dataclasses import replace
    request, sealed, market, _ = full_inputs(monkeypatch, tmp_path)
    other = sealed_precheck(monkeypatch, dict(PRECHECK_BODY, EstimatedCashRequired="37.60"))
    for candidate in (None, precheck(), replace(sealed, transport_seal=""), other):
        status, _ = evaluated(request=request, precheck=candidate)
        assert status["BROKER_PRECHECK_AND_ACCOUNT_CURRENCY"][0] == "MISSING"
        assert status["AUTHENTICATED_SIM_ACCOUNT_AND_INSTRUMENT"][0] == "MISSING"
    status, _ = evaluated(request=request, precheck=sealed)
    assert status["BROKER_PRECHECK_AND_ACCOUNT_CURRENCY"][0] == "PASS"
    from sidedeck.application import saxo_p4_acceptance
    gates, _ = saxo_p4_acceptance.evaluate(request=request, precheck=sealed,
                                           now=NOW + timedelta(minutes=6))
    stale = {g.name: (g.status, g.detail) for g in gates}["BROKER_PRECHECK_AND_ACCOUNT_CURRENCY"]
    assert stale == ("MISSING", "prepared request is stale")


def test_hand_built_scope_and_unprepared_request_are_refused(tmp_path, monkeypatch, released):
    from dataclasses import replace
    with pytest.raises(SubmissionBlocked, match="authenticated SIM responses"):
        prepared(monkeypatch, account_scope=SCOPE)
    with pytest.raises(SubmissionBlocked, match="authenticated SIM responses"):
        prepared(monkeypatch, account_scope=replace(authenticated_scope(), account_id="approved",
                                                    account_key="other-key"))
    request = prepared(monkeypatch)
    transport = Acknowledged()
    submitter = SaxoSimSubmitter(str(tmp_path / "o.sqlite"), network_enabled=True,
                                 transport=transport, approval_verifier=TrustedVerifier())
    unsealed = replace(request, preparation_seal="")
    with pytest.raises(SubmissionBlocked, match="production preparation"):
        submitter.submit(unsealed, approve(request), now=NOW)
    assert transport.calls == 0


def test_unregistered_market_verifier_cannot_prepare_an_order(monkeypatch):
    monkeypatch.setattr(submission_module, "TRUSTED_MARKET_VERIFIER_TYPES", ())
    with pytest.raises(SubmissionBlocked, match="no registered market-data verifier"):
        prepared(monkeypatch)


def test_real_operator_signature_passes_but_release_keeps_no_go(monkeypatch, tmp_path):
    import test_saxo_operator_approval as ssh
    if ssh.SSH_KEYGEN is None:
        pytest.skip("ssh-keygen unavailable")
    from sidedeck.infrastructure.saxo_operator_approval import SshSignatureApprovalVerifier
    request, sealed, market, _ = full_inputs(monkeypatch, tmp_path)
    key, signers = ssh.operator_setup(tmp_path)
    expires = NOW + timedelta(minutes=5)
    material = approval_material(request, authorization_id="approval-1", approver="operator",
                                 expires_at=expires)
    signature = ssh.operator_signs(tmp_path, key, material)
    authorization = accept_operator_approval(
        request, authorization_id="approval-1", approver="operator", expires_at=expires,
        attestation=signature, verifier=SshSignatureApprovalVerifier(signers), now=NOW)
    status, decision = evaluated(request=request, precheck=sealed, evidence=market,
                                 market_verifier=TrustedMarketVerifier(),
                                 authorization=authorization, allowed_signers=signers,
                                 ssh_keygen=ssh.SSH_KEYGEN)
    for name in EXTERNAL_GATES:
        assert status[name][0] == "PASS", (name, status[name])
    assert status["SIM_SUBMISSION_RELEASE"][0] == "DISABLED"
    assert decision == "NO-GO"
    from dataclasses import replace
    tampered = replace(authorization, expires_at=NOW + timedelta(minutes=4))
    status, _ = evaluated(request=request, precheck=sealed, evidence=market,
                          market_verifier=TrustedMarketVerifier(), authorization=tampered,
                          allowed_signers=signers, ssh_keygen=ssh.SSH_KEYGEN)
    assert status["INDEPENDENT_OPERATOR_APPROVAL"][0] == "MISSING"
