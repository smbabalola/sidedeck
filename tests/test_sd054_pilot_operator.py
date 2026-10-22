"""SD-054 supervised pilot operator, end to end over the offline simulator (no sockets)."""
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

from sidedeck.application import sd054_pilot_operator as operator
from sidedeck.application.sd036_etoro_demo_desk import (
    SYNTHETIC_BASELINE_ROWS, OfflineEtoroDemoSimulator, TransportNotFound,
)
from sidedeck.application.sd046_etoro_demo_pilot import UNRESOLVED
from sidedeck.application.sd048_pilot_release import (
    PILOT_NAMESPACE, PilotIntent, PilotReleaseRefused,
)
from sidedeck.domain.etoro_demo import parse_demo_portfolio
from sidedeck.domain.etoro_demo_books import BaselinePosition
from sidedeck.domain.etoro_demo_orders import DEMO_OPEN_PATH
from sidedeck.infrastructure import etoro_demo_write_transport as transport_module
from sidedeck.infrastructure.etoro_demo_write_transport import EtoroDemoHttpTransport

pytestmark = pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="ssh-keygen missing")
PRINCIPAL = "owner@sidedeck"
INSTRUMENT = 2002
ENV = {"ETORO_DEMO_TRADE_API_KEY": "synthetic-app-key-111",
       "ETORO_DEMO_TRADE_USER_KEY": "synthetic-user-key-222"}
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
    return root


def sign(root, digest, namespace, key="owner"):
    return subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(root / key), "-n", namespace],
                          input=digest.encode(), capture_output=True, check=True).stdout.decode()


class FakeResponse:
    def __init__(self, status, payload):
        self.status, self._raw = status, payload

    def read(self, n):
        return self._raw[:n]


class SimOpener:
    def __init__(self, sim):
        self.sim, self.requests = sim, []

    def open(self, request, timeout):
        self.requests.append(request)
        url = urlsplit(request.full_url)
        headers = {k.lower(): v for k, v in request.header_items()}
        query = {k: v[0] for k, v in parse_qs(url.query).items()} or None
        body = json.loads(request.data) if request.data else None
        try:
            result = self.sim.send(request.get_method(), url.path,
                                   reference_id=headers["x-request-id"], body=body, query=query)
        except TransportNotFound:
            raise HTTPError(request.full_url, 404, "nf", Message(), io.BytesIO(b"{}")) from None
        return FakeResponse(200, json.dumps(result).encode())


def make_intent(**changes):
    now = datetime.now(timezone.utc)
    values = dict(pilot_id=str(uuid.uuid4()), strategy="tradingagents", instrument_id=INSTRUMENT,
                  units=Decimal("0.4"), max_limit_rate=Decimal("100.5"),
                  reference_price=Decimal("100"), max_notional_usd=Decimal("50"),
                  not_before=now - timedelta(minutes=1), expires_at=now + timedelta(hours=2))
    values.update(changes)
    return PilotIntent(**values)


class Rig:
    def __init__(self, keys, tmp_path, *, decline=(), ask=None):
        self.keys, self.tmp = keys, tmp_path
        self.sim = OfflineEtoroDemoSimulator(fill_price=Decimal("100.25"))
        self.sim.baseline_rows = [dict(r) for r in SYNTHETIC_BASELINE_ROWS]
        if ask is not None:
            self.sim.ask = Decimal(ask)
        self.opener = SimOpener(self.sim)
        self.decline, self.prompts = set(decline), []
        self.intent = make_intent()

    def factory(self, release, ledger):
        return EtoroDemoHttpTransport(api_key=ENV["ETORO_DEMO_TRADE_API_KEY"],
                                      user_key=ENV["ETORO_DEMO_TRADE_USER_KEY"],
                                      release=release, ledger_path=ledger, opener=self.opener)

    def approve(self, label, digest, scope):
        self.prompts.append((label, scope))
        if label in self.decline:
            return ""
        return sign(self.keys, digest, "sidedeck-paper-approval")

    def run(self, release_signature=None, baseline_status="MATCHED"):
        signature = release_signature or sign(self.keys, self.intent.digest(), PILOT_NAMESPACE)
        return operator.run_pilot(
            intent=self.intent, release_signature=signature, principal=PRINCIPAL,
            signers_path=str(self.keys / "allowed_signers"), env=ENV, baseline=BASELINE,
            baseline_status=baseline_status, transport_factory=self.factory,
            await_approval=self.approve, paths=operator.OperatorPaths(self.tmp / "op"))

    def posts(self):
        return [r for r in self.opener.requests if r.get_method() == "POST"
                and urlsplit(r.full_url).path != "/api/v2/trading/info/demo/eligibility"]


def test_full_supervised_pilot_completes_with_two_writes(keys, tmp_path):
    rig = Rig(keys, tmp_path)
    report = rig.run()
    assert report["result"] == "COMPLETE"
    assert [label for label, _ in rig.prompts] == ["open", "close"]
    assert len(rig.posts()) == 2 and len(rig.opener.requests) <= 12
    assert Decimal(report["open_request"]["limit_rate"]) <= Decimal("100.5")
    saved = json.loads((tmp_path / "op" / "report.json").read_text(encoding="utf-8"))
    assert saved["result"] == "COMPLETE" and saved["intent_digest"] == rig.intent.digest()
    assert "synthetic-user-key-222" not in json.dumps(saved)


def test_declined_open_approval_sends_no_order(keys, tmp_path):
    rig = Rig(keys, tmp_path, decline={"open"})
    report = rig.run()
    assert report["result"] == "ABORTED_OPEN_NOT_APPROVED" and rig.posts() == []


def test_declined_close_trips_kill_switch_and_is_never_complete(keys, tmp_path):
    rig = Rig(keys, tmp_path, decline={"close"})
    report = rig.run()
    assert report["result"] == UNRESOLVED and "OPEN" in report["reason"]
    assert [urlsplit(r.full_url).path for r in rig.posts()] == [DEMO_OPEN_PATH]


def test_ask_above_signed_max_aborts_before_any_write(keys, tmp_path):
    rig = Rig(keys, tmp_path, ask="101")
    report = rig.run()
    assert report["result"] == "ABORTED_PREFLIGHT" and rig.posts() == []
    assert rig.prompts == []


def test_wrong_release_signature_or_gate_refuses_before_any_request(keys, tmp_path):
    rig = Rig(keys, tmp_path)
    wrong = sign(keys, rig.intent.digest(), PILOT_NAMESPACE, key="other")
    with pytest.raises(PilotReleaseRefused):
        rig.run(release_signature=wrong)
    with pytest.raises(PilotReleaseRefused, match="BASELINE"):
        Rig(keys, tmp_path / "b").run(baseline_status="UNKNOWN")
    approval_ns = sign(keys, rig.intent.digest(), "sidedeck-paper-approval")
    with pytest.raises(PilotReleaseRefused):
        Rig(keys, tmp_path / "c").run(release_signature=approval_ns)
    assert rig.opener.requests == []


def test_release_is_single_use(keys, tmp_path):
    rig = Rig(keys, tmp_path)
    assert rig.run()["result"] == "COMPLETE"
    with pytest.raises(PilotReleaseRefused):
        rig.run()


def test_main_run_is_locked_and_consumes_nothing(capsys):
    assert operator.main(["run", "--confirm-owner-release"]) == 5
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "REFUSED_LOCKED" and out["requests_sent"] == 0
    assert out["release_consumed"] is False
    assert transport_module.NETWORK_TRANSPORT_ENABLED is False
    with pytest.raises(SystemExit):
        operator.main(["run"])                       # confirmation flag is mandatory


@pytest.fixture
def signed_data(keys, tmp_path, monkeypatch):
    from sidedeck.application import sd053_msft_pilot_intent as sd053
    from sidedeck.infrastructure.etoro_demo_store import EtoroDemoStore
    data = tmp_path / "data"
    data.mkdir()
    (data / "approval_allowed_signers").write_text(
        (keys / "allowed_signers").read_text(encoding="utf-8"), encoding="utf-8")
    EtoroDemoStore(str(data / "etoro_demo.sqlite3")).capture_baseline(
        OfflineEtoroDemoSimulator(fill_price=Decimal(1)).pnl_payload(SYNTHETIC_BASELINE_ROWS),
        observed_at=datetime.now(timezone.utc), expected_positions=len(SYNTHETIC_BASELINE_ROWS))
    monkeypatch.setattr(operator, "_data_dir", lambda: data)
    from sidedeck.application import sd050_msft_instrument_lookup as lookup
    monkeypatch.setattr(lookup, "DATA_DIR", data)
    monkeypatch.setattr(sd053, "INTENT_PATH", data / "sd053-msft-pilot-intent.json")
    record = sd053.prepare(sd053.INTENT_PATH, frozenset())
    monkeypatch.setattr(operator, "PINNED_INTENT_DIGEST", record["digest"])
    return data, record


def test_main_verify_checks_owner_signature_offline(keys, signed_data, capsys):
    data, record = signed_data
    assert operator.main(["verify"]) == 5                     # no signature yet
    assert "signature file is missing" in capsys.readouterr().out
    sig = data / "sd053-msft-pilot-intent.digest.sig"
    sig.write_text(sign(keys, record["digest"], PILOT_NAMESPACE), encoding="utf-8")
    assert operator.main(["verify"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["signature_valid"] is True and out["release_consumed"] is False
    sig.write_text(sign(keys, record["digest"], PILOT_NAMESPACE, key="other"),
                   encoding="utf-8")
    assert operator.main(["verify"]) == 1
    sig.write_text(sign(keys, record["digest"], "sidedeck-paper-approval"), encoding="utf-8")
    assert operator.main(["verify"]) == 1


def test_verify_refuses_a_digest_other_than_the_pinned_one(keys, signed_data, monkeypatch,
                                                           capsys):
    monkeypatch.setattr(operator, "PINNED_INTENT_DIGEST", "0" * 64)
    assert operator.main(["verify"]) == 5
    assert "differs from the reviewed" in capsys.readouterr().out


# ---- failure modes through the full operator --------------------------------------

def _rig(keys, tmp_path, **sim):
    rig = Rig(keys, tmp_path)
    for name, value in sim.items():
        setattr(rig.sim, name, value)
    return rig


@pytest.mark.parametrize("sim,expected,writes", [
    ({"mode": "REJECT"}, "OPEN_REJECTED_CLEAN", 1),
    ({"mode": "PENDING"}, UNRESOLVED, 1),
    ({"lose_next_response": True}, UNRESOLVED, 1),
    ({"quote_age_seconds": 120}, "ABORTED_PREFLIGHT", 0),
    ({"quote_type": "delayed"}, "ABORTED_PREFLIGHT", 0),
    ({"close_mode": "PENDING"}, UNRESOLVED, 2),
    ({"close_mode": "PARTIAL"}, UNRESOLVED, 2),
])
def test_failure_modes_never_report_complete_or_repeat_writes(keys, tmp_path, sim, expected,
                                                             writes):
    rig = _rig(keys, tmp_path, **sim)
    report = rig.run()
    assert report["result"] == expected
    assert len(rig.posts()) == writes
    paths = [urlsplit(r.full_url).path for r in rig.posts()]
    assert paths.count(DEMO_OPEN_PATH) <= 1 and len(rig.opener.requests) <= 12


def test_complete_run_budget_and_accounting(keys, tmp_path):
    rig = Rig(keys, tmp_path)
    report = rig.run()
    final = report["steps"][-1]
    used = final["requests_used"]
    assert used["pnl"] == 3 and used["eligibility"] == 1 and used["rates"] == 1
    assert used["open"] == 1 and used["close"] == 1 and used["lookup"] <= 3
    assert used["close_info"] <= 2 and final["requests_total"] <= 12
    entry = final["accounting"]["entry"]
    assert entry["avg_price"] == "100.25" and Decimal(entry["units"]) == Decimal("0.4")
    assert "DERIVED" in final["accounting"].get("realized_pnl_source", "DERIVED")


def test_recorded_baseline_status_reads_sd038_ledger(tmp_path):
    import sqlite3
    path = tmp_path / "sd038.sqlite3"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE sd038_budget (singleton INTEGER, authorization_id TEXT, "
               "attempts INTEGER, outcome TEXT, updated_at TEXT)")
    db.execute("INSERT INTO sd038_budget VALUES (1, 'SD-038', 1, 'MATCHED', 'x')")
    db.commit()
    db.close()
    assert operator.recorded_baseline_status(str(path)) == "MATCHED"
    assert operator.recorded_baseline_status(str(tmp_path / "none")) == "UNKNOWN"


def test_terminal_partial_ioc_fill_closes_exactly_the_filled_units(keys, tmp_path):
    rig = _rig(keys, tmp_path, mode="PARTIAL")
    report = rig.run()
    assert report["result"] == "COMPLETE" and len(rig.posts()) == 2
    entry = report["steps"][-1]["accounting"]["entry"]
    assert Decimal(entry["units"]) == Decimal("0.2")
