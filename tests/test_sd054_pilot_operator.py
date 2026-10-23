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
from sidedeck.application.sd058_forensic_audit import PreflightAudit
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
        return sign(self.keys, digest, operator.APPROVAL_NAMESPACE)

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


def test_main_run_is_locked_and_consumes_nothing(capsys, monkeypatch):
    monkeypatch.setattr(transport_module, "UNLOCKED_PILOT_DIGEST", None)
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
    import hashlib
    blob = (keys / "owner.pub").read_text().split()[1]
    monkeypatch.setattr(operator, "PINNED_SIGNER_KEY_SHA256",
                        hashlib.sha256(blob.encode("ascii")).hexdigest())
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



# ---- independent review fixes (SD-056) ---------------------------------------------

def test_m1_interruption_after_open_trips_kill_switch_and_reports_unresolved(keys, tmp_path):
    rig = Rig(keys, tmp_path)

    def approve(label, digest, scope):
        if label == "close":
            raise KeyboardInterrupt
        return sign(keys, digest, operator.APPROVAL_NAMESPACE)
    rig.approve = approve
    with pytest.raises(KeyboardInterrupt):
        rig.run()
    saved = json.loads((tmp_path / "op" / "report.json").read_text(encoding="utf-8"))
    assert saved["result"] == UNRESOLVED and "may be OPEN" in saved["reason"]
    from sidedeck.application.sd033_approval_killswitch import ApprovalKillSwitch
    controls = ApprovalKillSwitch(str(tmp_path / "op" / "controls.sqlite3"), lambda *a: False)
    try:
        assert controls.is_halted()
    finally:
        controls.close()


def test_m2_factory_validation_runs_before_the_release_is_consumed(keys, tmp_path):
    rig = Rig(keys, tmp_path)

    class Locked:
        def validate(self):
            raise RuntimeError("locked")

        def __call__(self, release, ledger):
            raise AssertionError("must not be reached")
    good = rig.factory
    rig.factory = Locked()
    with pytest.raises(RuntimeError, match="locked"):
        rig.run()
    assert rig.opener.requests == []
    rig.factory = good
    assert rig.run()["result"] == "COMPLETE"          # the release was not consumed


def test_m3_open_refused_when_too_little_window_remains(keys, tmp_path):
    rig = Rig(keys, tmp_path)
    now = datetime.now(timezone.utc)
    rig.intent = make_intent(not_before=now - timedelta(minutes=1),
                             expires_at=now + timedelta(minutes=15))
    report = rig.run()
    assert report["result"] == "ABORTED_WINDOW_TOO_SHORT" and rig.posts() == []
    assert rig.prompts == []


def test_m5_generic_paper_approval_signature_is_not_accepted(keys, tmp_path):
    rig = Rig(keys, tmp_path)
    rig.approve = lambda label, digest, scope: sign(keys, digest, "sidedeck-paper-approval")
    assert rig.run()["result"] == "ABORTED_OPEN_NOT_APPROVED" and rig.posts() == []


def test_operator_persists_preflight_audit_next_to_atomic_report(keys, tmp_path):
    report = Rig(keys, tmp_path).run()
    assert report["result"] == "COMPLETE"
    audit_path = tmp_path / "op" / "audit.sqlite3"
    assert audit_path.is_file() and (tmp_path / "op" / "report.json").is_file()
    audit = PreflightAudit(audit_path, "unused")
    rows = audit.rows()
    audit.close()
    assert [row["request_type"] for row in rows[:3]] == ["pnl", "eligibility", "rates"]
    assert all(row["pilot_digest"] != "unused" for row in rows)


def test_pinned_signer_refuses_other_or_extra_keys(keys, signed_data):
    data, _ = signed_data
    signers = data / "approval_allowed_signers"
    operator.require_pinned_signer(signers)
    other = (keys / "other.pub").read_text().split()
    extra = f"owner@sidedeck {other[0]} {other[1]}"
    signers.write_text(signers.read_text() + extra + chr(10))
    with pytest.raises(operator.OperatorRefused):
        operator.require_pinned_signer(signers)
    signers.write_text(extra + chr(10))
    with pytest.raises(operator.OperatorRefused):
        operator.require_pinned_signer(signers)


def test_console_approval_command_checks_digest_and_drops_stale_signature(signed_data,
                                                                          monkeypatch, capsys):
    data, _ = signed_data
    folder = data / "sd054"
    folder.mkdir()
    (folder / "open-approval.digest.sig").write_text("stale", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    assert operator.console_approval("open", "ab" * 32, "scope") == ""
    out = json.loads(capsys.readouterr().out)
    assert "-ceq '" + "ab" * 32 + "'" in out["sign_in_powershell"]
    assert operator.APPROVAL_NAMESPACE in out["sign_in_powershell"]


def test_production_factory_validate_refuses_while_locked():
    from sidedeck.application.sd036_etoro_demo_desk import BrokerExecutionDisabled
    factory = transport_module.production_transport_factory(ENV, "a" * 64)
    with pytest.raises(BrokerExecutionDisabled, match="locked"):
        factory.validate()
    assert "synthetic" not in repr(factory)



# ---- release-bound unlock (SD-058 lock-lift design) ---------------------------------

def test_unlock_is_bound_to_exactly_one_digest(monkeypatch):
    assert transport_module.UNLOCKED_PILOT_DIGEST in (None, operator.PINNED_INTENT_DIGEST)
    assert transport_module.NETWORK_TRANSPORT_ENABLED is False
    monkeypatch.setattr(transport_module, "UNLOCKED_PILOT_DIGEST", "c" * 64)
    assert transport_module.network_transport_enabled("c" * 64) is True
    assert transport_module.network_transport_enabled("d" * 64) is False
    assert transport_module.network_transport_enabled() is False
    for wildcard in ("", "*", "c" * 63, 64):
        monkeypatch.setattr(transport_module, "UNLOCKED_PILOT_DIGEST", wildcard)
        assert transport_module.network_transport_enabled("c" * 64) is False


def test_unlock_for_one_pilot_does_not_open_the_network_for_another(keys, tmp_path, monkeypatch):
    """With another digest unlocked, this pilot's transport still refuses a real opener."""
    from sidedeck.application.sd036_etoro_demo_desk import BrokerExecutionDisabled
    rig = Rig(keys, tmp_path)
    monkeypatch.setattr(transport_module, "UNLOCKED_PILOT_DIGEST", "e" * 64)

    def real_factory(release, ledger):
        return EtoroDemoHttpTransport(api_key=ENV["ETORO_DEMO_TRADE_API_KEY"],
                                      user_key=ENV["ETORO_DEMO_TRADE_USER_KEY"],
                                      release=release, ledger_path=ledger)
    rig.factory = real_factory
    with pytest.raises(BrokerExecutionDisabled, match="locked"):
        rig.run()
    factory = transport_module.production_transport_factory(ENV, "e" * 64)
    factory.validate()                                   # unlocked digest + valid credentials
    with pytest.raises(BrokerExecutionDisabled, match="differs"):
        factory(type("R", (), {"digest": "f" * 64})(), str(tmp_path / "l.sqlite3"))


# ---- per-pilot budget isolation (SD-058 abort -> fresh Friday pilot) -------------------
def _legacy_budget_rows(path):
    import sqlite3
    with sqlite3.connect(path) as db:
        return sorted(db.execute("SELECT route, used FROM sd046_pilot_budget"))


def test_fresh_pilot_gets_own_budget_and_old_usage_stays_recorded(keys, tmp_path):
    from sidedeck.application.sd046_etoro_demo_pilot import PilotBudget
    (tmp_path / "op").mkdir()
    budget_file = str(tmp_path / "op" / "budget.sqlite3")
    legacy = PilotBudget(budget_file)            # the aborted pilot's unscoped record
    legacy.reserve("pnl")
    legacy.reserve("eligibility")
    legacy.close()
    aborted = Rig(keys, tmp_path, ask="101")     # an aborted scoped pilot, too
    assert aborted.run()["result"] == "ABORTED_PREFLIGHT"
    aborted_usage = PilotBudget(budget_file, pilot_id=aborted.intent.pilot_id).usage()
    assert sum(aborted_usage.values()) > 0

    fresh = Rig(keys, tmp_path)
    report = fresh.run()
    assert report["result"] == "COMPLETE"
    assert len(fresh.opener.requests) <= 12 and len(fresh.posts()) == 2
    assert _legacy_budget_rows(budget_file) == [("eligibility", 1), ("pnl", 1)]
    assert PilotBudget(budget_file, pilot_id=aborted.intent.pilot_id).usage() == aborted_usage


def test_same_pilot_never_gets_a_fresh_budget_on_restart(keys, tmp_path):
    from sidedeck.application.sd046_etoro_demo_pilot import PilotBudget, PilotBudgetExhausted
    rig = Rig(keys, tmp_path, ask="101")
    assert rig.run()["result"] == "ABORTED_PREFLIGHT"
    with pytest.raises(PilotReleaseRefused):     # single-use release, same digest
        rig.run()
    budget_file = str(tmp_path / "op" / "budget.sqlite3")
    reopened = PilotBudget(budget_file, pilot_id=rig.intent.pilot_id)
    assert reopened.usage()["eligibility"] == 1
    with pytest.raises(PilotBudgetExhausted):
        reopened.reserve("eligibility")
    with pytest.raises(Exception):               # non-canonical id cannot alias a pilot
        PilotBudget(budget_file, pilot_id=rig.intent.pilot_id.upper())


def test_concurrent_reservers_cannot_exceed_a_pilot_cap(tmp_path):
    import threading
    from sidedeck.application.sd046_etoro_demo_pilot import PilotBudget, PilotBudgetExhausted
    path, pilot = str(tmp_path / "budget.sqlite3"), str(uuid.uuid4())
    PilotBudget(path, pilot_id=pilot).close()
    wins, losses, barrier = [], [], threading.Barrier(8)

    def worker():
        budget = PilotBudget(path, pilot_id=pilot)
        barrier.wait()
        try:
            budget.reserve("eligibility")
            wins.append(1)
        except PilotBudgetExhausted:
            losses.append(1)
        except sqlite3_locked() as exc:          # a busy writer also never over-spends
            losses.append(exc)
        finally:
            budget.close()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(wins) == 1 and len(losses) == 7
    assert PilotBudget(path, pilot_id=pilot).usage()["eligibility"] == 1


def sqlite3_locked():
    import sqlite3
    return sqlite3.OperationalError


def test_unresolved_pilot_still_blocks_the_next_signed_pilot(keys, tmp_path):
    first = Rig(keys, tmp_path, decline={"close"})   # position left OPEN, kill switch trips
    assert first.run()["result"] == UNRESOLVED
    second = Rig(keys, tmp_path)
    with pytest.raises(PilotReleaseRefused):
        second.run()
    assert second.opener.requests == []


def test_real_routes_stay_excluded_for_scoped_pilots(keys, tmp_path):
    from sidedeck.domain.etoro_demo_orders import RealExecutionExcluded, require_demo_route
    rig = Rig(keys, tmp_path)
    assert rig.run()["result"] == "COMPLETE"
    assert all("/demo/" in urlsplit(r.full_url).path or "market-data" in r.full_url
               for r in rig.opener.requests)
    for method, path in (("POST", "/api/v2/trading/execution/orders"),
                         ("POST", "/api/v1/trading/execution/market-close-orders/positions/1"),
                         ("GET", "/api/v1/trading/info/pnl")):
        with pytest.raises(RealExecutionExcluded):
            require_demo_route(method, path)


# ---- owner signing UX: an early Enter must not silently abort the pilot ------------------
def test_console_approval_reprompts_until_the_signature_exists(signed_data, monkeypatch,
                                                               capsys):
    data, _ = signed_data
    sig = data / "sd054" / "open-approval.digest.sig"
    answers = iter(["", "", "go"])

    def fake_input(prompt):
        answer = next(answers)
        if answer == "go":                      # owner signs in the SECOND window, then Enter
            sig.write_text("SSHSIG-synthetic", encoding="utf-8")
        return answer

    monkeypatch.setattr("builtins.input", fake_input)
    assert operator.console_approval("open", "ab" * 32, "scope") == "SSHSIG-synthetic"
    guidance = capsys.readouterr().err
    assert "SECOND PowerShell window" in guidance and "no signature file yet" in guidance


def test_console_approval_no_declines_immediately(signed_data, monkeypatch):
    calls = []
    monkeypatch.setattr("builtins.input", lambda prompt: calls.append(prompt) or "no")
    assert operator.console_approval("close", "cd" * 32, "scope") == ""
    assert len(calls) == 1


def test_console_approval_gives_up_after_bounded_empty_presses(signed_data, monkeypatch):
    calls = []
    monkeypatch.setattr("builtins.input", lambda prompt: calls.append(prompt) or "")
    assert operator.console_approval("open", "ef" * 32, "scope") == ""
    assert len(calls) == operator.MAX_EMPTY_APPROVAL_PROMPTS


# ---- Monday readiness: full offline rehearsal through the production approval prompts -------
def test_rehearsal_production_console_approvals_buy_fill_close_reconcile(keys, signed_data,
                                                                         tmp_path, monkeypatch,
                                                                         capsys):
    """run_pilot + the real console_approval (files, prompts, ssh-keygen file signatures),
    offline simulator broker: open approval -> fill -> separate close approval -> full close
    -> MATCHED final snapshot. The owner presses Enter once too early at each prompt."""
    data, _ = signed_data
    pressed = []

    def owner_at_keyboard(prompt):
        label = "open" if "[open]" in prompt else "close"
        pressed.append(label)
        digest_file = data / "sd054" / f"{label}-approval.digest"
        if pressed.count(label) == 1:
            return ""                                   # early Enter: must re-prompt
        # the owner runs the displayed command in a SECOND window (file signature)
        subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(keys / "owner"), "-n",
                        operator.APPROVAL_NAMESPACE, str(digest_file)],
                       check=True, capture_output=True)
        return ""

    monkeypatch.setattr("builtins.input", owner_at_keyboard)
    rig = Rig(keys, tmp_path)
    report = operator.run_pilot(
        intent=rig.intent, release_signature=sign(keys, rig.intent.digest(), PILOT_NAMESPACE),
        principal=PRINCIPAL, signers_path=str(keys / "allowed_signers"), env=ENV,
        baseline=BASELINE, baseline_status="MATCHED", transport_factory=rig.factory,
        await_approval=operator.console_approval, paths=operator.OperatorPaths(tmp_path / "op"))

    assert report["result"] == "COMPLETE"                       # close FILLED, flat, MATCHED
    assert pressed == ["open", "open", "close", "close"]
    phases = [s["phase"] for s in report["steps"]]
    assert phases == ["preflight", "open", "close"]
    assert report["steps"][1]["result"] == "OPEN_FILLED_AWAITING_CLOSE_APPROVAL"
    assert report["steps"][1]["entry"]["units"] == "0.4"
    assert report["steps"][2]["sidedeck_open_positions"] == 0
    assert report["steps"][2]["writes"] == 2 and len(rig.posts()) == 2
    assert report["steps"][2]["kill_switch"] == "CLEAR"
    err = capsys.readouterr().err
    assert err.count("SECOND PowerShell window") >= 2 and "STOP: no signature file yet" in err
