"""SD-048: C7 Demo transport (mock openers only) and C8 signed pilot release. No network."""
import http.client
import io
import json
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from email.message import Message
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

from sidedeck.application.sd032_durable_paper_intent import DurablePaperIntentStore
from sidedeck.application.sd033_approval_killswitch import ApprovalKillSwitch, intent_digest
from sidedeck.application.sd036_etoro_demo_desk import (
    SYNTHETIC_BASELINE_ROWS, BrokerExecutionDisabled, DemoDeskPolicy, DemoRateBudget,
    EtoroDemoDesk, EtoroDemoLineage, OfflineEtoroDemoSimulator, TransportNotFound,
    TransportOutcomeUnknown, open_scope,
)
from sidedeck.application.sd042_etoro_credential_roles import POLICY
from sidedeck.application.sd045_ssh_approval_verifier import SshSignatureVerifier
from sidedeck.application.sd046_etoro_demo_pilot import (
    UNRESOLVED, EtoroDemoPilot, PilotBudget, PilotTransport,
)
from sidedeck.application.sd048_pilot_release import (
    PILOT_NAMESPACE, PilotIntent, PilotRelease, PilotReleaseRefused, PilotReleaseStore, ReleaseGates,
    authorize_pilot,
)
from sidedeck.domain.etoro_demo import parse_demo_portfolio
from sidedeck.domain.etoro_demo_books import BaselinePosition
from sidedeck.domain.etoro_demo_orders import (
    DEMO_OPEN_PATH, DEMO_ORDER_LOOKUP_PATH, DEMO_PNL_PATH, DemoOpenRequest,
    RealExecutionExcluded,
)
from sidedeck.infrastructure import etoro_demo_write_transport as transport_module
from sidedeck.infrastructure.etoro_demo_write_transport import (
    EtoroDemoHttpTransport, EtoroDemoTransportError,
)

pytestmark = pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="ssh-keygen missing")
INSTRUMENT = 2002
PRINCIPAL = "owner@sidedeck"
API, USER = "synthetic-app-key-111", "synthetic-user-key-222"
GATES = ReleaseGates(POLICY, "MATCHED", True, True, True)
BASELINE = tuple(BaselinePosition.of(p) for p in parse_demo_portfolio(
    OfflineEtoroDemoSimulator(fill_price=Decimal(1)).pnl_payload(SYNTHETIC_BASELINE_ROWS),
    observed_at=datetime.now(timezone.utc)).positions)


@pytest.fixture(scope="module")
def keys(tmp_path_factory):
    root = tmp_path_factory.mktemp("keys")
    for name in ("owner", "other"):
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f",
                        str(root / name)], check=True, capture_output=True)
    signers = root / "allowed_signers"
    signers.write_text(f"{PRINCIPAL} " + (root / "owner.pub").read_text().strip() + "\n")
    return root, SshSignatureVerifier(str(signers), PRINCIPAL, namespace=PILOT_NAMESPACE)


def sign(root, digest, key="owner", namespace=PILOT_NAMESPACE):
    return subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(root / key), "-n", namespace],
                          input=digest.encode(), capture_output=True, check=True).stdout.decode()


def intent(**changes):
    now = datetime.now(timezone.utc)
    values = dict(pilot_id=str(uuid.uuid4()), strategy="tradingagents", instrument_id=INSTRUMENT,
                  units=Decimal("0.4"), max_limit_rate=Decimal("100.5"),
                  reference_price=Decimal("100"), max_notional_usd=Decimal("50"),
                  not_before=now - timedelta(minutes=1), expires_at=now + timedelta(hours=2))
    values.update(changes)
    return PilotIntent(**values)


def release_for(keys, tmp_path, signed_intent=None, gates=GATES):
    root, verifier = keys
    signed_intent = signed_intent or intent()
    store = PilotReleaseStore(str(tmp_path / f"releases-{uuid.uuid4()}.sqlite3"))
    try:
        return authorize_pilot(intent=signed_intent, signature=sign(root, signed_intent.digest()),
                               principal=PRINCIPAL, verifier=verifier, gates=gates,
                               baseline=BASELINE, store=store)
    finally:
        store.close()


# ---- C8: signed pilot release ---------------------------------------------------

def test_valid_signature_and_gates_issue_single_use_release(keys, tmp_path):
    root, verifier = keys
    signed = intent()
    store = PilotReleaseStore(str(tmp_path / "r.sqlite3"))
    release = authorize_pilot(intent=signed, signature=sign(root, signed.digest()),
                              principal=PRINCIPAL, verifier=verifier, gates=GATES,
                              baseline=BASELINE, store=store)
    assert release.digest == signed.digest() and store.used() == 1
    with pytest.raises(PilotReleaseRefused, match="replay"):
        authorize_pilot(intent=signed, signature=sign(root, signed.digest()), principal=PRINCIPAL,
                        verifier=verifier, gates=GATES, baseline=BASELINE, store=store)
    store.close()


@pytest.mark.parametrize("mutate", [
    {"units": Decimal("0.3")}, {"max_limit_rate": Decimal("100.4")}, {"instrument_id": 2003},
    {"max_notional_usd": Decimal("49")},
    {"expires_at": datetime.now(timezone.utc) + timedelta(hours=3)},
])
def test_signature_binds_every_intent_field(keys, tmp_path, mutate):
    root, verifier = keys
    signed = intent()
    tampered = PilotIntent(**{**signed.__dict__, **mutate})
    store = PilotReleaseStore(str(tmp_path / "r.sqlite3"))
    with pytest.raises(PilotReleaseRefused, match="signature"):
        authorize_pilot(intent=tampered, signature=sign(root, signed.digest()),
                        principal=PRINCIPAL, verifier=verifier, gates=GATES, baseline=BASELINE,
                        store=store)
    assert store.used() == 0
    store.close()


def test_other_key_or_principal_refused(keys, tmp_path):
    root, verifier = keys
    signed = intent()
    store = PilotReleaseStore(str(tmp_path / "r.sqlite3"))
    for principal, key in ((PRINCIPAL, "other"), ("attacker@x", "owner")):
        with pytest.raises(PilotReleaseRefused, match="signature"):
            authorize_pilot(intent=signed, signature=sign(root, signed.digest(), key),
                            principal=principal, verifier=verifier, gates=GATES,
                            baseline=BASELINE, store=store)
    assert store.used() == 0
    store.close()


@pytest.mark.parametrize("gates,label", [
    (ReleaseGates("EXTRA_CREDENTIAL_NAMES_REFUSED", "MATCHED", True, True, True), "CREDENTIAL"),
    (ReleaseGates(POLICY, "DISCREPANCY", True, True, True), "BASELINE"),
    (ReleaseGates(POLICY, "MATCHED", False, True, True), "KILL_SWITCH"),
    (ReleaseGates(POLICY, "MATCHED", True, False, True), "BUDGET"),
    (ReleaseGates(POLICY, "MATCHED", True, True, False), "SIGNERS"),
])
def test_valid_signature_alone_is_not_enough(keys, tmp_path, gates, label):
    with pytest.raises(PilotReleaseRefused, match=label):
        release_for(keys, tmp_path, gates=gates)


@pytest.mark.parametrize("changes,match", [
    ({"max_notional_usd": Decimal("51")}, "USD 50"),
    ({"units": Decimal("1")}, "notional"),
    ({"max_limit_rate": Decimal("106")}, "5 %"),
    ({"instrument_id": 1001}, "baseline"),
    ({"broker": "etoro-real"}, "Demo"),
    ({"request_caps": (("close", 1), ("close_info", 3), ("lookup", 3), ("open", 2),
                       ("pnl", 3))}, "caps"),
    ({"expires_at": datetime.now(timezone.utc) + timedelta(hours=9)}, "8 hours"),
    ({"not_before": datetime.now(timezone.utc) + timedelta(hours=1)}, "window"),
    ({"pilot_id": "not-a-uuid"}, "UUID"),
])
def test_intent_bounds(keys, tmp_path, changes, match):
    with pytest.raises(PilotReleaseRefused, match=match):
        release_for(keys, tmp_path, signed_intent=intent(**changes))


def test_release_cannot_be_forged_or_mutated(keys, tmp_path):
    with pytest.raises(BrokerExecutionDisabled):
        PilotRelease(object(), intent(), datetime.now(timezone.utc))
    release = release_for(keys, tmp_path)
    with pytest.raises(AttributeError):
        release.intent = intent()
    release.require_active()
    with pytest.raises(BrokerExecutionDisabled, match="window"):
        release.require_active(datetime.now(timezone.utc) + timedelta(hours=3))


# ---- C7: transport with mock openers ------------------------------------------------

class FakeResponse:
    def __init__(self, status, payload):
        self.status, self._raw = status, payload

    def read(self, n):
        return self._raw[:n]


class SimOpener:
    """Routes urllib Requests into the offline simulator. No sockets."""

    def __init__(self, sim, fault=None, fault_on=None):
        self.sim, self.fault, self.requests = sim, fault, []
        self.fault_on = fault_on       # (method, path) the fault targets; None = next request

    def _dispatch(self, request, url, headers, body, query):
        return self.sim.send(request.get_method(), url.path, reference_id=headers["x-request-id"],
                             body=body, query=query)

    def open(self, request, timeout):
        assert timeout == 15.0
        self.requests.append(request)
        url = urlsplit(request.full_url)
        assert url.scheme == "https" and url.netloc == "public-api.etoro.com"
        headers = {k.lower(): v for k, v in request.header_items()}
        query = {k: v[0] for k, v in parse_qs(url.query).items()} or None
        body = json.loads(request.data) if request.data else None
        fault = None
        if self.fault and (self.fault_on is None
                           or (request.get_method(), url.path) == self.fault_on):
            fault, self.fault = self.fault, None
        if fault == "timeout_after":
            self._dispatch(request, url, headers, body, query)
            raise TimeoutError()
        if isinstance(fault, int):
            raise HTTPError(request.full_url, fault, "err", Message(), io.BytesIO(b"{}"))
        if fault == "malformed":
            self._dispatch(request, url, headers, body, query)
            return FakeResponse(200, b"{not json")
        if fault == "oversized":
            return FakeResponse(200, b" " * 1_000_001)
        try:
            result = self._dispatch(request, url, headers, body, query)
        except TransportNotFound:
            raise HTTPError(request.full_url, 404, "nf", Message(), io.BytesIO(b"{}")) from None
        return FakeResponse(200, json.dumps(result).encode())


def make_transport(keys, tmp_path, fault=None):
    sim = OfflineEtoroDemoSimulator(fill_price=Decimal("100.25"))
    sim.baseline_rows = list(SYNTHETIC_BASELINE_ROWS)
    opener = SimOpener(sim, fault)
    release = release_for(keys, tmp_path)
    return EtoroDemoHttpTransport(api_key=API, user_key=USER, release=release,
                                  ledger_path=str(tmp_path / f"ledger-{uuid.uuid4()}.sqlite3"),
                                  opener=opener, test_only_opener=True), opener, release


def test_network_is_locked_without_injected_opener(keys, tmp_path):
    assert transport_module.NETWORK_TRANSPORT_ENABLED is False
    release = release_for(keys, tmp_path)
    with pytest.raises(BrokerExecutionDisabled, match="locked"):
        EtoroDemoHttpTransport(api_key=API, user_key=USER, release=release_for(keys, tmp_path),
                               ledger_path=str(tmp_path / "l.sqlite3"))
    with pytest.raises(BrokerExecutionDisabled, match="custom openers are restricted"):
        EtoroDemoHttpTransport(api_key=API, user_key=USER, release=release,
                               ledger_path=str(tmp_path / "custom.sqlite3"),
                               opener=SimOpener(None))
    with pytest.raises(BrokerExecutionDisabled, match="signed pilot release"):
        EtoroDemoHttpTransport(api_key=API, user_key=USER, release=object(),
                               ledger_path=str(tmp_path / "l.sqlite3"), opener=SimOpener(None), test_only_opener=True)


def test_test_only_opener_stays_refused_when_release_digest_is_unlocked(keys, tmp_path, monkeypatch):
    release = release_for(keys, tmp_path)
    monkeypatch.setattr(transport_module, "UNLOCKED_PILOT_DIGEST", release.digest)
    with pytest.raises(BrokerExecutionDisabled, match="custom openers are restricted"):
        EtoroDemoHttpTransport(
            api_key=API, user_key=USER, release=release,
            ledger_path=str(tmp_path / "unlocked-custom.sqlite3"),
            opener=SimOpener(None), test_only_opener=True,
        )


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/v2/trading/execution/orders"), ("GET", "/api/v1/trading/info/real/pnl"),
    ("POST", "/api/v2/agent-portfolios"), ("GET", "/api/v1/agent-portfolios"),
    ("DELETE", "/api/v2/trading/execution/demo/orders"),
])
def test_real_and_agent_routes_refused_before_io(keys, tmp_path, method, path):
    transport, opener, _ = make_transport(keys, tmp_path)
    with pytest.raises(RealExecutionExcluded):
        transport.send(method, path, reference_id=str(uuid.uuid4()), body={})
    assert opener.requests == []


def test_headers_ids_and_credentials_hidden(keys, tmp_path):
    transport, opener, _ = make_transport(keys, tmp_path)
    reference = str(uuid.uuid4())
    request = DemoOpenRequest(reference, INSTRUMENT, Decimal("0.4"), Decimal("100.5"))
    transport.send("POST", DEMO_OPEN_PATH, reference_id=reference, body=request.body())
    transport.send("GET", DEMO_ORDER_LOOKUP_PATH, reference_id="ignored",
                   query={"referenceId": reference})
    post, get = ({k.lower(): v for k, v in r.header_items()} for r in opener.requests)
    assert post["x-request-id"] == reference and get["x-request-id"] != reference
    assert post["x-api-key"] == API and post["x-user-key"] == USER
    assert "authorization" not in post and post["user-agent"].startswith("SideDeck/")
    assert USER not in repr(transport) and API not in repr(transport)
    with pytest.raises(EtoroDemoTransportError, match="QUERY_REFUSED"):
        transport.send("GET", DEMO_ORDER_LOOKUP_PATH, reference_id="r",
                       query={"referenceId": reference, "orderId": "1"})


def test_reference_reuse_only_with_identical_body(keys, tmp_path):
    transport, opener, _ = make_transport(keys, tmp_path)
    reference = str(uuid.uuid4())
    body = DemoOpenRequest(reference, INSTRUMENT, Decimal("0.4"), Decimal("100.5")).body()
    transport.send("POST", DEMO_OPEN_PATH, reference_id=reference, body=body)
    with pytest.raises(EtoroDemoTransportError, match="DURABLE_WRITE_REFERENCE_ALREADY_RESERVED"):
        transport.send("POST", DEMO_OPEN_PATH, reference_id=reference, body=body)
    with pytest.raises(EtoroDemoTransportError, match="SIGNED_INTENT"):
        transport.send("POST", DEMO_OPEN_PATH, reference_id=reference, body={**body, "units": 0.3})
    assert len(opener.requests) == 1


def test_sd138_write_reference_survives_restart_with_no_second_post(keys, tmp_path):
    sim = OfflineEtoroDemoSimulator(fill_price=Decimal("100.25"))
    sim.baseline_rows = list(SYNTHETIC_BASELINE_ROWS)
    release = release_for(keys, tmp_path)
    ledger = str(tmp_path / "write-refs.sqlite3")
    reference = str(uuid.uuid4())
    body = DemoOpenRequest(reference, INSTRUMENT, Decimal("0.4"), Decimal("100.5")).body()
    first_opener = SimOpener(sim)
    first = EtoroDemoHttpTransport(api_key=API, user_key=USER, release=release,
                                   ledger_path=ledger, opener=first_opener,
                                   test_only_opener=True)
    first.send("POST", DEMO_OPEN_PATH, reference_id=reference, body=body)
    assert len(first_opener.requests) == 1
    first.close()

    second_opener = SimOpener(sim)
    second = EtoroDemoHttpTransport(api_key=API, user_key=USER, release=release,
                                    ledger_path=ledger, opener=second_opener,
                                    test_only_opener=True)
    with pytest.raises(EtoroDemoTransportError, match="DURABLE_WRITE_REFERENCE_ALREADY_RESERVED"):
        second.send("POST", DEMO_OPEN_PATH, reference_id=reference, body=body)
    assert second_opener.requests == []
    second.close()


def test_sd138_lost_post_response_cannot_be_replayed_after_restart(keys, tmp_path):
    sim = OfflineEtoroDemoSimulator(fill_price=Decimal("100.25"))
    sim.baseline_rows = list(SYNTHETIC_BASELINE_ROWS)
    release = release_for(keys, tmp_path)
    ledger = str(tmp_path / "lost-post-refs.sqlite3")
    reference = str(uuid.uuid4())
    body = DemoOpenRequest(reference, INSTRUMENT, Decimal("0.4"), Decimal("100.5")).body()
    first_opener = SimOpener(sim, fault="timeout_after")
    first = EtoroDemoHttpTransport(api_key=API, user_key=USER, release=release,
                                   ledger_path=ledger, opener=first_opener,
                                   test_only_opener=True)
    with pytest.raises(TransportOutcomeUnknown):
        first.send("POST", DEMO_OPEN_PATH, reference_id=reference, body=body)
    assert len(first_opener.requests) == 1
    first.close()

    second_opener = SimOpener(sim)
    second = EtoroDemoHttpTransport(api_key=API, user_key=USER, release=release,
                                    ledger_path=ledger, opener=second_opener,
                                    test_only_opener=True)
    with pytest.raises(EtoroDemoTransportError, match="DURABLE_WRITE_REFERENCE_ALREADY_RESERVED"):
        second.send("POST", DEMO_OPEN_PATH, reference_id=reference, body=body)
    assert second_opener.requests == []
    second.close()


def test_sd138_write_reservations_are_atomic_across_two_sqlite_handles(keys, tmp_path):
    # The private quota/ref ledger is tested directly; no transport or broker calls.
    release = release_for(keys, tmp_path)
    path = str(tmp_path / "parallel-write-refs.sqlite3")
    first = transport_module._ReleaseLedger(path, release)
    second = transport_module._ReleaseLedger(path, release)
    ref = str(uuid.uuid4())
    first.reserve("open", reference_id=ref, body_sha256="a" * 64)
    with pytest.raises(EtoroDemoTransportError, match="DURABLE_WRITE_REFERENCE_ALREADY_RESERVED"):
        second.reserve("open", reference_id=ref, body_sha256="a" * 64)
    with pytest.raises(EtoroDemoTransportError, match="SIGNED_REQUEST_CAP"):
        second.reserve("open", reference_id=str(uuid.uuid4()), body_sha256="b" * 64)
    first.close()
    second.close()


@pytest.mark.parametrize("fault,method,expected", [
    ("timeout_after", "POST", TransportOutcomeUnknown),
    (500, "POST", TransportOutcomeUnknown),
    (503, "POST", TransportOutcomeUnknown),
    ("malformed", "POST", TransportOutcomeUnknown),
    ("oversized", "POST", TransportOutcomeUnknown),
    ("timeout_after", "GET", EtoroDemoTransportError),
    (401, "POST", EtoroDemoTransportError),
    (403, "GET", EtoroDemoTransportError),
    (429, "POST", EtoroDemoTransportError),
    (404, "GET", TransportNotFound),
])
def test_failure_classification(keys, tmp_path, fault, method, expected):
    transport, opener, _ = make_transport(keys, tmp_path, fault=fault)
    reference = str(uuid.uuid4())
    if method == "POST":
        body = DemoOpenRequest(reference, INSTRUMENT, Decimal("0.4"), Decimal("100.5")).body()
        with pytest.raises(expected) as info:
            transport.send("POST", DEMO_OPEN_PATH, reference_id=reference, body=body)
    else:
        with pytest.raises(expected) as info:
            transport.send("GET", DEMO_PNL_PATH, reference_id=reference)
    assert USER not in str(info.value) and API not in str(info.value)
    assert len(opener.requests) == 1                       # never retried


def test_expired_release_blocks_send_before_io(keys, tmp_path, monkeypatch):
    transport, opener, _ = make_transport(keys, tmp_path)

    def expired(self, now=None):
        raise BrokerExecutionDisabled("pilot release is outside its signed time window")
    monkeypatch.setattr(PilotRelease, "require_active", expired)
    with pytest.raises(BrokerExecutionDisabled, match="window"):
        transport.send("GET", DEMO_PNL_PATH, reference_id=str(uuid.uuid4()))
    assert opener.requests == []


# ---- desk + pilot through the real transport code (mock opener) ---------------------

class HttpRig:
    def __init__(self, keys, tmp_path, *, policy=None, with_release=True, fault=None):
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.sim = OfflineEtoroDemoSimulator(fill_price=Decimal("100.25"))
        self.sim.baseline_rows = [dict(r) for r in SYNTHETIC_BASELINE_ROWS]
        self.opener = SimOpener(self.sim, fault, fault_on=("POST", DEMO_OPEN_PATH))
        self.release = release_for(keys, tmp_path)
        http = EtoroDemoHttpTransport(api_key=API, user_key=USER, release=self.release,
                                      ledger_path=str(tmp_path / "ledger.sqlite3"),
                                      opener=self.opener, test_only_opener=True)
        self.controls = ApprovalKillSwitch(str(tmp_path / "c.sqlite3"),
                                           lambda k, d, s: s == f"{k}:{d}")
        self.lineage = EtoroDemoLineage(str(tmp_path / "l.sqlite3"),
                                        baseline_position_ids=[b.position_id for b in BASELINE],
                                        baseline_order_ids=[b.order_id for b in BASELINE])
        self.outbox = DurablePaperIntentStore(str(tmp_path / "o.sqlite3"))
        self.rate = DemoRateBudget(str(tmp_path / "rate.sqlite3"))
        self.budget = PilotBudget(str(tmp_path / "p.sqlite3"))
        self.stores = (self.outbox, self.controls, self.lineage, self.rate, self.budget)
        self.transport = PilotTransport(http, self.budget)
        try:
            self.desk = EtoroDemoDesk(
                outbox=self.outbox, controls=self.controls, lineage=self.lineage,
                transport=self.transport,
                policy=policy or DemoDeskPolicy(Decimal("50"), frozenset({INSTRUMENT}), 1),
                baseline=BASELINE, budget=self.rate,
                pilot_release=self.release if with_release else None)
        except Exception:
            self.shutdown()
            raise
        self.pilot = EtoroDemoPilot(desk=self.desk, transport=self.transport, budget=self.budget,
                                    controls=self.controls, lineage=self.lineage,
                                    baseline=BASELINE, scope=self.release.intent.scope(),
                                    release=self.release)

    def approve(self, intent_id, scope):
        digest = intent_digest(intent_id, scope)
        self.controls.approve(f"a-{intent_id}", intent_id, scope, "sidedeck", "owner", "pk",
                              f"pk:{digest}", datetime.now(timezone.utc) + timedelta(minutes=10))

    def open(self):
        pre = self.pilot.preflight()
        if pre["result"] != "READY_FOR_OPEN_APPROVAL":
            return pre
        _, scope = self.pilot.open_approval_scope()
        self.approve("open", scope)
        return self.pilot.open_phase(intent_id="open")

    def close(self):
        request, scope = self.pilot.close_request(str(uuid.uuid4()))
        if not self.controls.is_halted():
            self.approve("close", scope)
        return self.pilot.close_phase(intent_id="close", request=request)

    def shutdown(self):
        for store in self.stores:
            store.close()

    def posts(self, path=None):
        return [r for r in self.opener.requests if r.get_method() == "POST"
                and (path is None or urlsplit(r.full_url).path == path)]


def test_desk_refuses_http_transport_without_release_or_matching_policy(keys, tmp_path):
    with pytest.raises(BrokerExecutionDisabled, match="signed pilot release"):
        HttpRig(keys, tmp_path / "none", with_release=False)
    for index, policy in enumerate((
            DemoDeskPolicy(Decimal("50"), frozenset({INSTRUMENT, 2003}), 1),
            DemoDeskPolicy(Decimal("51"), frozenset({INSTRUMENT}), 1),
            DemoDeskPolicy(Decimal("50"), frozenset({INSTRUMENT}), 2))):
        with pytest.raises(BrokerExecutionDisabled, match="policy"):
            HttpRig(keys, tmp_path / f"p{index}", policy=policy)


def test_full_pilot_through_transport_code_completes(keys, tmp_path):
    rig = HttpRig(keys, tmp_path)
    try:
        assert rig.open()["result"] == "OPEN_FILLED_AWAITING_CLOSE_APPROVAL"
        result = rig.close()
        assert result["result"] == "COMPLETE" and result["writes"] == 2
        assert result["requests_total"] <= 12
        assert len(rig.opener.requests) == result["requests_total"]
    finally:
        rig.shutdown()


def test_open_must_equal_signed_intent(keys, tmp_path):
    rig = HttpRig(keys, tmp_path)
    try:
        rig.pilot.preflight()
        for units, limit in ((Decimal("0.3"), Decimal("100.5")), (Decimal("0.4"), Decimal("100.6"))):
            request = DemoOpenRequest(str(uuid.uuid4()), INSTRUMENT, units, limit)
            rig.approve(f"open-{units}-{limit}", open_scope("etoro-demo:tradingagents", request))
            with pytest.raises(Exception, match="signed pilot intent"):
                rig.desk.submit_open(intent_id=f"open-{units}-{limit}", strategy="tradingagents",
                                     request=request)
        assert rig.posts(DEMO_OPEN_PATH) == []
    finally:
        rig.shutdown()


def test_interrupted_open_is_recovered_never_resubmitted(keys, tmp_path):
    rig = HttpRig(keys, tmp_path, fault="timeout_after")
    try:
        result = rig.open()
        assert result["result"] == UNRESOLVED and "acknowledgement lost" in result["reason"]
        assert result["kill_switch"] == "HALTED" and len(rig.posts(DEMO_OPEN_PATH)) == 1
    finally:
        rig.shutdown()


def test_unresolved_close_through_transport(keys, tmp_path):
    rig = HttpRig(keys, tmp_path)
    try:
        rig.open()
        rig.sim.close_mode = "PENDING"
        result = rig.close()
        assert result["result"] == UNRESOLVED and result["sidedeck_open_positions"] == 1
        assert result["kill_switch"] == "HALTED"
    finally:
        rig.shutdown()


def test_malformed_open_response_halts_without_resubmission(keys, tmp_path):
    rig = HttpRig(keys, tmp_path, fault="malformed")
    try:
        result = rig.open()
        assert result["kill_switch"] == "HALTED" and len(rig.posts(DEMO_OPEN_PATH)) == 1
    finally:
        rig.shutdown()


def test_second_open_never_reaches_broker(keys, tmp_path):
    rig = HttpRig(keys, tmp_path)
    try:
        rig.open()
        request = DemoOpenRequest(str(uuid.uuid4()), INSTRUMENT, Decimal("0.4"), Decimal("100.5"))
        rig.approve("open-2", open_scope("etoro-demo:tradingagents", request))
        with pytest.raises(Exception):
            rig.desk.submit_open(intent_id="open-2", strategy="tradingagents", request=request)
        assert len(rig.posts(DEMO_OPEN_PATH)) == 1
    finally:
        rig.shutdown()


# ---- independent security review regressions (2026-10-22) -----------------------------

def test_h1_signed_caps_enforced_in_transport_even_with_fresh_pilot_budget(keys, tmp_path):
    transport, opener, release = make_transport(keys, tmp_path)
    reference = str(uuid.uuid4())
    body = DemoOpenRequest(reference, INSTRUMENT, Decimal("0.4"), Decimal("100.5")).body()
    transport.send("POST", DEMO_OPEN_PATH, reference_id=reference, body=body)
    with pytest.raises(EtoroDemoTransportError, match="SIGNED_REQUEST_CAP"):
        transport.send("POST", DEMO_OPEN_PATH, reference_id=str(uuid.uuid4()), body=body)
    for _ in range(3):
        transport.send("GET", DEMO_PNL_PATH, reference_id="r")
    with pytest.raises(EtoroDemoTransportError, match="SIGNED_REQUEST_CAP"):
        transport.send("GET", DEMO_PNL_PATH, reference_id="r")
    assert len(opener.requests) == 4


def test_h1_ledger_is_persistent_per_release_digest(keys, tmp_path):
    sim = OfflineEtoroDemoSimulator(fill_price=Decimal("100.25"))
    sim.baseline_rows = list(SYNTHETIC_BASELINE_ROWS)
    release, ledger = release_for(keys, tmp_path), str(tmp_path / "ledger.sqlite3")
    first = EtoroDemoHttpTransport(api_key=API, user_key=USER, release=release,
                                   ledger_path=ledger, opener=SimOpener(sim), test_only_opener=True)
    for _ in range(3):
        first.send("GET", DEMO_PNL_PATH, reference_id="r")
    first.close()
    second = EtoroDemoHttpTransport(api_key=API, user_key=USER, release=release,
                                    ledger_path=ledger, opener=SimOpener(sim), test_only_opener=True)
    with pytest.raises(EtoroDemoTransportError, match="SIGNED_REQUEST_CAP"):
        second.send("GET", DEMO_PNL_PATH, reference_id="r")
    second.close()
    with pytest.raises(BrokerExecutionDisabled, match="durable"):
        EtoroDemoHttpTransport(api_key=API, user_key=USER, release=release,
                               ledger_path=":memory:", opener=SimOpener(sim), test_only_opener=True)


_OPEN = {"action": "open", "transaction": "buy", "instrumentId": INSTRUMENT,
         "orderType": "limitIOC", "limitRate": 100.5, "units": 0.4, "leverage": 1,
         "orderCurrency": "usd"}


@pytest.mark.parametrize("path,body", [
    (DEMO_OPEN_PATH, {**_OPEN, "leverage": 2}),
    (DEMO_OPEN_PATH, {**_OPEN, "transaction": "sellShort"}),
    (DEMO_OPEN_PATH, {**_OPEN, "instrumentId": 2003}),
    (DEMO_OPEN_PATH, {**_OPEN, "stopLossRate": 1}),
    ("/api/v1/trading/execution/demo/market-close-orders/positions/11",
     {"InstrumentID": 1001, "UnitsToDeduct": None}),
    ("/api/v1/trading/execution/demo/market-close-orders/positions/880001",
     {"InstrumentID": INSTRUMENT, "UnitsToDeduct": 0.1}),
])
def test_h1_write_bodies_must_equal_signed_intent(keys, tmp_path, path, body):
    transport, opener, _ = make_transport(keys, tmp_path)
    with pytest.raises(EtoroDemoTransportError, match="SIGNED_INTENT"):
        transport.send("POST", path, reference_id=str(uuid.uuid4()), body=body)
    assert opener.requests == []


def test_h2_verifier_type_namespace_and_store_are_pinned(keys, tmp_path):
    root, verifier = keys
    signed = intent()
    store = PilotReleaseStore(str(tmp_path / "r.sqlite3"))
    for bad in (lambda *a: True, SshSignatureVerifier(str(root / "allowed_signers"), PRINCIPAL)):
        with pytest.raises(PilotReleaseRefused, match="namespace"):
            authorize_pilot(intent=signed, signature=sign(root, signed.digest()),
                            principal=PRINCIPAL, verifier=bad, gates=GATES, baseline=BASELINE,
                            store=store)
    with pytest.raises(PilotReleaseRefused, match="signature"):
        authorize_pilot(intent=signed,
                        signature=sign(root, signed.digest(), namespace="sidedeck-paper-approval"),
                        principal=PRINCIPAL, verifier=verifier, gates=GATES, baseline=BASELINE,
                        store=store)
    assert store.used() == 0
    store.close()
    with pytest.raises(PilotReleaseRefused, match="durable"):
        PilotReleaseStore(":memory:")


def test_h2_gates_computed_from_runtime_objects(tmp_path):
    controls = ApprovalKillSwitch(str(tmp_path / "c.sqlite3"), lambda *a: False)
    budget = PilotBudget(str(tmp_path / "b.sqlite3"))
    signers = tmp_path / "allowed_signers"
    env = {"ETORO_DEMO_TRADE_API_KEY": "a", "ETORO_DEMO_TRADE_USER_KEY": "b"}
    gates = ReleaseGates.from_runtime(env=env, controls=controls, pilot_budget=budget,
                                      baseline_status="MATCHED", signers_path=str(signers))
    assert gates.failures() == ["SIGNERS_NOT_CONFIGURED"]
    signers.write_text("x")
    controls.trip("op", "test")
    budget.reserve("pnl")
    gates = ReleaseGates.from_runtime(env={**env, "ETORO_API_KEY": "x"}, controls=controls,
                                      pilot_budget=budget, baseline_status="MATCHED",
                                      signers_path=str(signers))
    assert gates.failures() == ["CREDENTIAL_POLICY", "KILL_SWITCH_ACTIVE", "PILOT_BUDGET_USED"]
    controls.close()
    budget.close()


@pytest.mark.parametrize("changes", [
    {"pilot_id": "{" + str(uuid.uuid4()) + "}"}, {"pilot_id": str(uuid.uuid4()).upper()},
    {"instrument_id": True}, {"strategy": 5},
])
def test_m8_intent_types_and_canonical_id(keys, tmp_path, changes):
    with pytest.raises(PilotReleaseRefused):
        release_for(keys, tmp_path, signed_intent=intent(**changes))


class _RaisingOpener:
    def __init__(self, exc):
        self.exc, self.requests = exc, []

    def open(self, request, timeout):
        self.requests.append(request)
        raise self.exc


@pytest.mark.parametrize("exc", [
    http.client.IncompleteRead(b"x"), http.client.BadStatusLine("x"), RecursionError(),
    ValueError("x"), HTTPError("u", 408, "timeout", Message(), io.BytesIO(b"")),
])
def test_m3_any_failure_after_write_io_is_outcome_unknown(keys, tmp_path, exc):
    release = release_for(keys, tmp_path)
    opener = _RaisingOpener(exc)
    transport = EtoroDemoHttpTransport(api_key=API, user_key=USER, release=release,
                                       ledger_path=str(tmp_path / "l.sqlite3"), opener=opener, test_only_opener=True)
    reference = str(uuid.uuid4())
    body = DemoOpenRequest(reference, INSTRUMENT, Decimal("0.4"), Decimal("100.5")).body()
    with pytest.raises(TransportOutcomeUnknown):
        transport.send("POST", DEMO_OPEN_PATH, reference_id=reference, body=body)
    assert len(opener.requests) == 1


def test_low_real_openers_and_malformed_keys_refused(keys, tmp_path):
    from urllib.request import build_opener
    release = release_for(keys, tmp_path)
    with pytest.raises(BrokerExecutionDisabled, match="real urllib"):
        EtoroDemoHttpTransport(api_key=API, user_key=USER, release=release,
                               ledger_path=str(tmp_path / "l.sqlite3"), opener=build_opener())
    with pytest.raises(ValueError, match="malformed"):
        EtoroDemoHttpTransport(api_key="bad\nkey", user_key=USER, release=release,
                               ledger_path=str(tmp_path / "l.sqlite3"), opener=SimOpener(None), test_only_opener=True)
    transport, _, _ = make_transport(keys, tmp_path)
    with pytest.raises(AttributeError):
        transport.offline_simulation = True


def test_low_route_regex_refuses_trailing_newline():
    from sidedeck.domain.etoro_demo_orders import require_demo_route
    with pytest.raises(RealExecutionExcluded):
        require_demo_route("GET", DEMO_PNL_PATH + "\n")


def test_m4_unreadable_open_acceptance_halts_desk(keys, tmp_path):
    rig = HttpRig(keys, tmp_path)
    try:
        real = rig.sim.send

        def broken(method, path, **kw):
            result = real(method, path, **kw)
            return {"orderId": result["orderId"]} if path == DEMO_OPEN_PATH else result
        rig.sim.send = broken
        request = DemoOpenRequest(str(uuid.uuid4()), INSTRUMENT, Decimal("0.4"), Decimal("100.5"))
        rig.approve("open", open_scope("etoro-demo:tradingagents", request))
        assert rig.desk.submit_open(intent_id="open", strategy="tradingagents",
                                    request=request, quote=_quote("100.25"),
                                    eligibility=_elig()) == "OUTCOME_UNKNOWN"
        assert rig.controls.is_halted() and len(rig.posts(DEMO_OPEN_PATH)) == 1
    finally:
        rig.shutdown()


# ---- SD-051 fresh-price / eligibility gates --------------------------------------------

def test_sd051_market_data_exception_is_exact_get_only():
    from sidedeck.domain.etoro_demo_orders import require_demo_route
    require_demo_route("GET", "/api/v2/market-data/rates")
    require_demo_route("POST", "/api/v2/trading/info/demo/eligibility")
    for method, path in (("POST", "/api/v2/market-data/rates"),
                         ("GET", "/api/v1/market-data/instruments/rates"),
                         ("GET", "/api/v2/market-data/instruments"),
                         ("POST", "/api/v2/trading/info/real/eligibility")):
        with pytest.raises(RealExecutionExcluded):
            require_demo_route(method, path)


def test_sd051_quote_and_eligibility_parsers_fail_closed():
    from sidedeck.domain.etoro_demo_orders import (
        EtoroDemoOrderError, parse_eligibility, parse_fresh_quote,
    )
    now = datetime.now(timezone.utc)
    row = {"instrumentId": INSTRUMENT, "bid": 100.0, "ask": 100.1, "date": now.isoformat(),
           "quoteType": "realtime"}
    assert parse_fresh_quote({"results": [row]}, instrument_id=INSTRUMENT, now=now).ask         == Decimal("100.1")
    for bad in ({"results": [row, {**row, "instrumentId": 1}]},
                {"results": [{**row, "date": (now + timedelta(seconds=30)).isoformat()}]},
                {"results": [{**row, "bid": 100.2}]}, {"results": [{**row, "ask": None}]},
                {"results": [{**row, "date": "2026-10-22T10:00:00"}]}):
        with pytest.raises(EtoroDemoOrderError):
            parse_fresh_quote(bad, instrument_id=INSTRUMENT, now=now)
    good = {"currency": "USD", "eligibilities": [{
        "instrumentId": INSTRUMENT, "minPositionExposure": 10, "allowOpenPosition": True,
        "allowClosePosition": True, "unitsQuantityType": "fractional",
        "allowedOrderQuantityType": "all", "tradeUnitType": "units",
        "leverageConfigs": [{"direction": "long", "leverageValues": [1],
                             "settlementType": "real", "minPositionAmount": 10}]}]}
    assert parse_eligibility(good, instrument_id=INSTRUMENT, units=Decimal("0.4"),
                             notional_usd=Decimal("40")).fractional
    for change in ({"currency": "EUR"},
                   {"eligibilities": [{**good["eligibilities"][0], "leverageConfigs": [
                       {"direction": "short", "leverageValues": [1], "minPositionAmount": 1}]}]},
                   {"eligibilities": [{**good["eligibilities"][0], "tradeUnitType": "contracts"}]}):
        with pytest.raises(EtoroDemoOrderError):
            parse_eligibility({**good, **change}, instrument_id=INSTRUMENT, units=Decimal("0.4"),
                              notional_usd=Decimal("40"))


def test_sd051_transport_pins_rates_query_and_eligibility_body(keys, tmp_path):
    transport, opener, _ = make_transport(keys, tmp_path)
    with pytest.raises(EtoroDemoTransportError, match="QUERY_REFUSED"):
        transport.send("GET", "/api/v2/market-data/rates", reference_id="r",
                       query={"instrumentIds": "2002,1001"})
    with pytest.raises(EtoroDemoTransportError, match="ELIGIBILITY"):
        transport.send("POST", "/api/v2/trading/info/demo/eligibility", reference_id="r",
                       body={"instrumentIds": [1001], "currency": "USD"})
    assert opener.requests == []



def _quote(ask, age_seconds=0, instrument=INSTRUMENT):
    from sidedeck.domain.etoro_demo_orders import FreshQuote
    return FreshQuote(instrument, Decimal(ask) - Decimal("0.05"), Decimal(ask),
                      datetime.now(timezone.utc) - timedelta(seconds=age_seconds))


def _elig(minimum="10", fractional=True, instrument=INSTRUMENT):
    from sidedeck.domain.etoro_demo_orders import Eligibility
    return Eligibility(instrument, fractional, Decimal(minimum))


@pytest.mark.parametrize("kwargs,match", [
    ({}, "evidence are required"),
    ({"quote": _quote("100.25", age_seconds=400), "eligibility": _elig()}, "older than 5"),
    ({"quote": _quote("99.00"), "eligibility": _elig()}, "0.5 %"),
    ({"quote": _quote("100.60"), "eligibility": _elig()}, "0.5 %"),
    ({"quote": _quote("100.25", instrument=2003), "eligibility": _elig()}, "different"),
    ({"quote": _quote("100.25"), "eligibility": _elig(minimum="60")}, "minimum"),
    ({"quote": _quote("100.25"), "eligibility": _elig(fractional=False)}, "fractional"),
])
def test_review2_desk_enforces_preflight_evidence_for_signed_opens(keys, tmp_path, kwargs, match):
    rig = HttpRig(keys, tmp_path)
    try:
        request = DemoOpenRequest(str(uuid.uuid4()), INSTRUMENT, Decimal("0.4"), Decimal("100.5"))
        rig.approve("open", open_scope("etoro-demo:tradingagents", request))
        with pytest.raises(Exception, match=match):
            rig.desk.submit_open(intent_id="open", strategy="tradingagents", request=request,
                                 **kwargs)
        assert rig.posts(DEMO_OPEN_PATH) == []
    finally:
        rig.shutdown()


def test_review2_eligibility_requires_real_settlement_and_int_leverage():
    from sidedeck.domain.etoro_demo_orders import EtoroDemoOrderError, parse_eligibility
    row = {"instrumentId": INSTRUMENT, "minPositionExposure": 10, "allowOpenPosition": True,
           "allowClosePosition": True, "unitsQuantityType": "fractional",
           "allowedOrderQuantityType": "all", "tradeUnitType": "units"}
    for config in ({"direction": "long", "leverageValues": [1], "settlementType": "cfd",
                    "minPositionAmount": 10},
                   {"direction": "long", "leverageValues": [True], "settlementType": "real",
                    "minPositionAmount": 10}):
        with pytest.raises(EtoroDemoOrderError, match="real-stock"):
            parse_eligibility({"currency": "USD", "eligibilities": [{**row, "leverageConfigs":
                                                                      [config]}]},
                              instrument_id=INSTRUMENT, units=Decimal("0.4"),
                              notional_usd=Decimal("40"))
    with pytest.raises(EtoroDemoOrderError, match="USD"):
        parse_eligibility({"eligibilities": []}, instrument_id=INSTRUMENT, units=Decimal("0.4"),
                          notional_usd=Decimal("40"))
