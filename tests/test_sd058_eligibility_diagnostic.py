"""Offline security tests for the SD-058 one-request diagnostic."""
import hashlib
import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sidedeck.application import sd058_eligibility_diagnostic as diagnostic

pytestmark = pytest.mark.skipif(shutil.which("ssh-keygen") is None,
                                reason="ssh-keygen missing")


@pytest.fixture
def signing_material(tmp_path: Path):
    key = tmp_path / "owner"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "owner@sidedeck",
                    "-f", str(key)], check=True)
    public = key.with_suffix(".pub").read_text(encoding="utf-8").split()
    allowed = tmp_path / "allowed_signers"
    allowed.write_text(f"owner@sidedeck {public[0]} {public[1]}\n", encoding="utf-8")
    return key, allowed, hashlib.sha256(public[1].encode("ascii")).hexdigest()


def _sign(key: Path, digest: str) -> str:
    result = subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n",
                             diagnostic.DIAGNOSTIC_NAMESPACE], input=digest.encode("ascii"),
                            capture_output=True, check=True)
    return result.stdout.decode("ascii")


class Response:
    status = 200

    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self, limit):
        return self._raw[:limit]


class Opener:
    def __init__(self, payload=None, error=None):
        self.payload, self.error, self.requests = payload, error, []

    def open(self, request, timeout):
        self.requests.append(request)
        if self.error:
            raise self.error
        return Response(self.payload)


def _intent(now=None):
    moment = now or datetime.now(UTC)
    return diagnostic.DiagnosticIntent(str(uuid.uuid4()), moment - timedelta(minutes=1),
                                       moment + timedelta(minutes=5))


def _setup(monkeypatch, tmp_path, signing_material):
    key, allowed, pin = signing_material
    monkeypatch.setattr(diagnostic, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(diagnostic, "PINNED_SIGNER_KEY_SHA256", pin)
    intent = _intent()
    return intent, key, allowed, _sign(key, intent.digest())


def test_success_is_exactly_one_read_and_preserves_currency_metadata(
        monkeypatch, tmp_path, signing_material):
    intent, key, allowed, signature = _setup(monkeypatch, tmp_path, signing_material)
    opener = Opener({"currency": "EUR", "eligibilities": [{"instrumentId": 1004,
                                                               "currencyId": 2}]})
    result = diagnostic.run_diagnostic(intent=intent, signature=signature,
                                       env={"ETORO_DEMO_TRADE_API_KEY": "k",
                                            "ETORO_DEMO_TRADE_USER_KEY": "u"},
                                       allowed_signers=allowed, opener=opener)
    assert result["outcome"] == "RESPONSE_CAPTURED"
    assert len(opener.requests) == 1
    assert opener.requests[0].full_url == diagnostic.HOST + diagnostic.DEMO_ELIGIBILITY_PATH
    assert json.loads(opener.requests[0].data) == diagnostic.REQUEST_BODY
    assert result["response_schema"]["fields"][1]["currency_code"] == "EUR"
    audit = diagnostic.PreflightAudit(diagnostic.fixed_paths()["audit"], "unused")
    assert [row["outcome"] for row in audit.rows()] == ["AUTHORIZED_NOT_SENT",
                                                          "RESPONSE_CAPTURED"]
    audit.close()
    with pytest.raises(diagnostic.DiagnosticRefused, match="already been used"):
        diagnostic.run_diagnostic(intent=intent, signature=signature,
                                 env={"ETORO_DEMO_TRADE_API_KEY": "k",
                                      "ETORO_DEMO_TRADE_USER_KEY": "u"},
                                 allowed_signers=allowed, opener=opener)
    assert len(opener.requests) == 1


def test_invalid_signature_expiry_and_scope_refuse_before_network(
        monkeypatch, tmp_path, signing_material):
    intent, key, allowed, signature = _setup(monkeypatch, tmp_path, signing_material)
    opener = Opener({})
    with pytest.raises(diagnostic.DiagnosticRefused):
        diagnostic.run_diagnostic(intent=intent, signature=signature[:-5],
                                  env={"ETORO_DEMO_TRADE_API_KEY": "k",
                                       "ETORO_DEMO_TRADE_USER_KEY": "u"},
                                  allowed_signers=allowed, opener=opener)
    expired = diagnostic.DiagnosticIntent(intent.intent_id,
        datetime.now(UTC) - timedelta(minutes=10), datetime.now(UTC) - timedelta(minutes=5))
    with pytest.raises(diagnostic.DiagnosticRefused, match="outside"):
        diagnostic.run_diagnostic(intent=expired, signature=_sign(key, expired.digest()),
                                  env={"ETORO_DEMO_TRADE_API_KEY": "k",
                                       "ETORO_DEMO_TRADE_USER_KEY": "u"},
                                  allowed_signers=allowed, opener=opener)
    wrong = diagnostic.DiagnosticIntent(intent.intent_id, intent.not_before, intent.expires_at,
                                        instrument_id=1001)
    with pytest.raises(diagnostic.DiagnosticRefused, match="fixed MSFT"):
        diagnostic.run_diagnostic(intent=wrong, signature=_sign(key, wrong.digest()),
                                  env={"ETORO_DEMO_TRADE_API_KEY": "k",
                                       "ETORO_DEMO_TRADE_USER_KEY": "u"},
                                  allowed_signers=allowed, opener=opener)
    assert opener.requests == []


def test_uncertain_read_consumes_allowance_and_retries_are_refused(
        monkeypatch, tmp_path, signing_material):
    intent, _, allowed, signature = _setup(monkeypatch, tmp_path, signing_material)
    opener = Opener(error=ConnectionError("simulated disconnect"))
    result = diagnostic.run_diagnostic(intent=intent, signature=signature,
                                       env={"ETORO_DEMO_TRADE_API_KEY": "k",
                                            "ETORO_DEMO_TRADE_USER_KEY": "u"},
                                       allowed_signers=allowed, opener=opener)
    assert result["outcome"] == "DIAGNOSTIC_ABORTED" and len(opener.requests) == 1
    with pytest.raises(diagnostic.DiagnosticRefused, match="already been used"):
        diagnostic.run_diagnostic(intent=intent, signature=signature,
                                  env={"ETORO_DEMO_TRADE_API_KEY": "k",
                                       "ETORO_DEMO_TRADE_USER_KEY": "u"},
                                  allowed_signers=allowed, opener=opener)
    assert len(opener.requests) == 1


def test_concurrent_invocations_can_reserve_only_once(
        monkeypatch, tmp_path, signing_material):
    intent, _, allowed, signature = _setup(monkeypatch, tmp_path, signing_material)
    openers = [Opener({"currency": "USD"}), Opener({"currency": "USD"})]

    def invoke(opener):
        try:
            return diagnostic.run_diagnostic(
                intent=intent, signature=signature,
                env={"ETORO_DEMO_TRADE_API_KEY": "k", "ETORO_DEMO_TRADE_USER_KEY": "u"},
                allowed_signers=allowed, opener=opener)
        except Exception as exc:  # assertion below distinguishes the expected refusal
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(invoke, openers))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, diagnostic.DiagnosticRefused) for result in results) == 1
    assert sum(len(opener.requests) for opener in openers) == 1


def test_malformed_json_aborts_and_preserves_only_schema_safe_evidence(
        monkeypatch, tmp_path, signing_material):
    intent, _, allowed, signature = _setup(monkeypatch, tmp_path, signing_material)

    class MalformedResponse:
        status = 200

        def read(self, limit):
            return b"{not-json"

    class MalformedOpener(Opener):
        def open(self, request, timeout):
            self.requests.append(request)
            return MalformedResponse()

    opener = MalformedOpener()
    result = diagnostic.run_diagnostic(
        intent=intent, signature=signature,
        env={"ETORO_DEMO_TRADE_API_KEY": "k", "ETORO_DEMO_TRADE_USER_KEY": "u"},
        allowed_signers=allowed, opener=opener)
    assert result["outcome"] == "DIAGNOSTIC_ABORTED"
    assert result["error_classification"] == "DiagnosticTransportError"
    assert "not-json" not in json.dumps(result)
    assert len(opener.requests) == 1


def test_audit_failure_blocks_network(monkeypatch, tmp_path, signing_material):
    intent, _, allowed, signature = _setup(monkeypatch, tmp_path, signing_material)
    opener = Opener({"currency": "USD"})

    def fail(*args, **kwargs):
        raise OSError("audit unavailable")

    monkeypatch.setattr(diagnostic.PreflightAudit, "record", fail)
    with pytest.raises(OSError, match="audit unavailable"):
        diagnostic.run_diagnostic(intent=intent, signature=signature,
                                  env={"ETORO_DEMO_TRADE_API_KEY": "k",
                                       "ETORO_DEMO_TRADE_USER_KEY": "u"},
                                  allowed_signers=allowed, opener=opener)
    assert opener.requests == []


def test_prepare_has_fixed_scope_and_no_signature(monkeypatch, tmp_path):
    monkeypatch.setattr(diagnostic, "DATA_DIR", tmp_path / "data")
    intent, digest = diagnostic.prepare_intent(minutes=30, now=datetime(2026, 10, 23, 14, 0,
                                                                         tzinfo=UTC),
                                                intent_id="11111111-1111-1111-1111-111111111111")
    paths = diagnostic.fixed_paths()
    assert intent.instrument_id == 1004 and digest.read_bytes() == intent.digest().encode("ascii")
    assert paths["intent"].is_file() and not paths["signature"].exists()


def test_prepare_file_sign_verify_workflow(monkeypatch, tmp_path, signing_material):
    key, allowed, pin = signing_material
    monkeypatch.setattr(diagnostic, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(diagnostic, "PINNED_SIGNER_KEY_SHA256", pin)
    intent, digest_path = diagnostic.prepare_intent(minutes=30, now=datetime.now(UTC))
    subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n",
                    diagnostic.DIAGNOSTIC_NAMESPACE, str(digest_path)], check=True,
                   capture_output=True)
    signature_path = diagnostic.fixed_paths()["signature"]
    assert signature_path == digest_path.with_name("intent.digest.sig")
    result = diagnostic.run_diagnostic(
        intent=intent, signature=signature_path.read_text(encoding="ascii"),
        env={"ETORO_DEMO_TRADE_API_KEY": "k", "ETORO_DEMO_TRADE_USER_KEY": "u"},
        allowed_signers=allowed, opener=Opener({"currency": "USD", "eligibilities": []}))
    assert result["outcome"] == "RESPONSE_CAPTURED"
