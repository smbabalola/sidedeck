"""SD-077 signed data authorizations and SD-075A import. Mock transport only; no network."""
from __future__ import annotations

import io
import shutil
import subprocess
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from sidedeck.application.sd045_ssh_approval_verifier import SshSignatureVerifier
from sidedeck.application.sd075a_nasdaq_universe_import import FILES, ImportFailed, run_import
from sidedeck.application.sd077_data_authorization import (
    NAMESPACE,
    AuthorizationRefused,
    DataAuthorization,
    DataRequestLedger,
    prepare,
    signing_command,
    verify_authorization,
)

NOW = datetime(2026, 10, 22, 19, tzinfo=UTC)


def _auth(**kw: Any) -> DataAuthorization:
    base = DataAuthorization(
        authorization_id="sd075a-2026-10-22", provider="NASDAQ_TRADER_SYMBOL_DIRECTORY",
        purpose="first genuine US symbol snapshot", urls=tuple(FILES.values()), max_requests=2,
        max_retries=0, credentials_required=False, issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(days=1), owner_terms_reviewed=True,
    )
    return replace(base, **kw)


@pytest.mark.parametrize("change, message", [
    ({"provider": "ETORO_DEMO"}, "cannot be authorized"),
    ({"urls": ("http://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",)}, "not allowed"),
    ({"urls": ("https://evil.example/nasdaqlisted.txt",)}, "not allowed"),
    ({"urls": ("https://www.nasdaqtrader.com/x?y=1",)}, "not allowed"),
    ({"provider": "ALPACA_SIP_DAILY", "urls": ("https://data.alpaca.markets/v2/account",)},
     "never authorized"),
    ({"urls": ()}, "at least one"),
    ({"max_requests": 0}, "max_requests"),
    ({"max_retries": 3}, "max_retries"),
    ({"expires_at": NOW + timedelta(days=30)}, "7 days"),
    ({"owner_terms_reviewed": False}, "terms"),
    ({"authorization_id": "../escape"}, "simple identifier"),
    ({"max_requests": 1.5}, "integer"),
    ({"max_requests": True}, "integer"),
    ({"owner_terms_reviewed": 1}, "boolean"),
    ({"purpose": 7}, "string"),
    ({"provider": "ALPACA_SIP_DAILY",
      "urls": ("https://data.alpaca.markets/v2/stocks/%2e%2e/%2e%2e/acc%6funt",)}, "unsafe"),
    ({"provider": "ALPACA_SIP_DAILY",
      "urls": ("https://data.alpaca.markets/v2/stocks/SPY/bars/../../account",)}, "unsafe"),
    ({"urls": ("https://user@www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",)},
     "not allowed"),
    ({"urls": ("https://www.nasdaqtrader.com:8443/dynamic/SymDir/nasdaqlisted.txt",)},
     "not allowed"),
])
def test_authorization_scope_validation(change: dict[str, Any], message: str) -> None:
    with pytest.raises(AuthorizationRefused, match=message):
        _auth(**change)


def test_intraday_alpaca_scope_is_separate_and_read_only(tmp_path: Path) -> None:
    url = "https://data.alpaca.markets/v2/stocks/SPY/bars"
    auth = _auth(
        provider="ALPACA_SIP_INTRADAY", urls=(url,),
        authorization_id="sd156-spy-intraday-fixture", max_requests=1,
    )
    assert auth.allows_url(url + "?timeframe=5Min&feed=sip&limit=10000")
    assert not auth.allows_url("https://data.alpaca.markets/v2/stocks/QQQ/bars")
    assert not auth.allows_url("https://data.alpaca.markets/v2/stocks/SPY/orders")
    ledger = DataRequestLedger(tmp_path / "intraday.sqlite3", auth)
    ledger.reserve(url + "?timeframe=5Min&feed=sip&limit=10000", NOW)
    with pytest.raises(AuthorizationRefused, match="exhausted"):
        ledger.reserve(url + "?timeframe=5Min&feed=sip&limit=10000", NOW)
    with pytest.raises(AuthorizationRefused):
        _auth(
            provider="ALPACA_SIP_INTRADAY",
            urls=("https://data.alpaca.markets/v2/account",),
        )


def test_canonical_round_trip_and_prepare(tmp_path: Path) -> None:
    auth = _auth()
    again = DataAuthorization.from_json(auth.canonical())
    assert again == auth and again.digest == auth.digest
    auth_path, digest_path = prepare(auth, tmp_path)
    assert digest_path.read_text() == auth.digest and auth_path.exists()
    with pytest.raises(AuthorizationRefused, match="overwrite"):
        prepare(auth, tmp_path)
    command = signing_command(digest_path, auth.digest)
    assert NAMESPACE in command and auth.digest in command and "digest mismatch" in command


def test_ledger_reserves_before_send_and_caps_requests(tmp_path: Path) -> None:
    auth = _auth()
    ledger = DataRequestLedger(tmp_path / "l.sqlite3", auth)
    first = ledger.reserve(FILES["nasdaqlisted"], NOW)
    ledger.record(first, "OK")
    with pytest.raises(AuthorizationRefused):
        ledger.record(first, "OK")
    with pytest.raises(AuthorizationRefused, match="outside"):
        ledger.reserve("https://www.nasdaqtrader.com/dynamic/SymDir/other.txt", NOW)
    with pytest.raises(AuthorizationRefused, match="retry"):
        ledger.reserve(FILES["otherlisted"], NOW, attempt=1)
    ledger.reserve(FILES["otherlisted"], NOW)
    restarted = DataRequestLedger(tmp_path / "l.sqlite3", auth)
    with pytest.raises(AuthorizationRefused, match="exhausted"):
        restarted.reserve(FILES["otherlisted"], NOW)
    with pytest.raises(AuthorizationRefused, match="not currently valid"):
        DataRequestLedger(tmp_path / "m.sqlite3", auth).reserve(
            FILES["otherlisted"], NOW + timedelta(days=2))


NASDAQ = (
    "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
    "AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N\n"
    "QQQ|Invesco QQQ Trust, Series 1|G|N|N|100|Y|N\n"
    "ZXZZT|NASDAQ TEST STOCK|G|Y|N|100|N|N\n"
    "File Creation Time: 1022202608:31|||||||\n"
)
OTHER = (
    "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
    "SPY|SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|SPY\n"
    "UNH|UnitedHealth Group Incorporated Common Stock|N|UNH|N|100|N|UNH\n"
    "File Creation Time: 1022202608:31|||||||\n"
)


class _Resp(io.BytesIO):
    def __init__(self, body: bytes, status: int = 200) -> None:
        super().__init__(body)
        self.status = status


def _opener(bodies: dict[str, tuple[bytes, int]], calls: list[str]) -> Any:
    def open_(request: Any, timeout: float) -> _Resp:
        calls.append(request.full_url)
        assert "Authorization" not in request.headers and "Cookie" not in request.headers
        body, status = bodies[request.full_url]
        return _Resp(body, status)
    return open_


def test_import_success_two_requests_snapshot_only(tmp_path: Path) -> None:
    calls: list[str] = []
    auth = _auth()
    ledger = DataRequestLedger(tmp_path / "l.sqlite3", auth)
    opener = _opener({FILES["nasdaqlisted"]: (NASDAQ.encode(), 200),
                      FILES["otherlisted"]: (OTHER.encode(), 200)}, calls)
    summary = run_import(auth, ledger, tmp_path / "out", now=NOW, opener=opener)
    assert calls == [FILES["nasdaqlisted"], FILES["otherlisted"]]
    assert summary["requests_used"] == 2 and summary["merged_instruments"] == 4
    assert summary["history_basis"].startswith("SNAPSHOT")
    assert summary["price_coverage"].startswith("UNAVAILABLE")
    nas = summary["files"][0]
    assert nas["rejected"] == {"TEST_ISSUE": 1}
    assert nas["by_asset_type"] == {"COMMON_STOCK": 1, "ETF": 1}
    assert len(nas["sha256"]) == 64
    raw = tmp_path / "out" / "raw" / auth.authorization_id / "nasdaqlisted.txt"
    assert raw.read_bytes() == NASDAQ.encode()
    with pytest.raises(AuthorizationRefused, match="exhausted"):
        run_import(auth, ledger, tmp_path / "out2", now=NOW, opener=opener)
    assert len(calls) == 2   # budget refused before any further request


@pytest.mark.parametrize("bodies, message", [
    ({FILES["nasdaqlisted"]: (b"", 403)}, "HTTP 403"),
    ({FILES["nasdaqlisted"]: (NASDAQ.rsplit("File", 1)[0].encode(), 200)}, "schema"),
    ({FILES["nasdaqlisted"]: (b"x" * 5_000_001, 200)}, "oversized"),
])
def test_import_failures_stop_without_retry(tmp_path: Path, bodies: dict[str, tuple[bytes, int]],
                                            message: str) -> None:
    calls: list[str] = []
    auth = _auth()
    ledger = DataRequestLedger(tmp_path / "l.sqlite3", auth)
    with pytest.raises(ImportFailed, match=message):
        run_import(auth, ledger, tmp_path / "out", now=NOW, opener=_opener(bodies, calls))
    assert calls == [FILES["nasdaqlisted"]] and ledger.used() == 1


def test_import_refuses_wrong_scope(tmp_path: Path) -> None:
    narrow = _auth(urls=(FILES["nasdaqlisted"],), max_requests=1)
    with pytest.raises(AuthorizationRefused, match="exactly the two"):
        run_import(narrow, DataRequestLedger(tmp_path / "l.sqlite3", narrow), tmp_path, now=NOW,
                   opener=_opener({}, []))


ssh = pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="ssh-keygen missing")


def _keypair(tmp_path: Path, name: str) -> Path:
    key = tmp_path / name
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(key)],
                   check=True)
    return key


def _sign(key: Path, digest: str, namespace: str) -> str:
    result = subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", namespace],
                            input=digest.encode(), capture_output=True, check=True)
    return result.stdout.decode()


@ssh
def test_owner_signature_required_in_data_namespace(tmp_path: Path) -> None:
    owner = _keypair(tmp_path, "owner")
    other = _keypair(tmp_path, "other")
    signers = tmp_path / "allowed_signers"
    signers.write_text("owner@sidedeck " + (tmp_path / "owner.pub").read_text())
    verifier = SshSignatureVerifier(str(signers), "owner@sidedeck", namespace=NAMESPACE)
    auth = _auth()
    good = _sign(owner, auth.digest, NAMESPACE)
    assert verify_authorization(auth, good, verifier=verifier, principal="owner@sidedeck",
                                now=NOW) == auth
    for bad in (_sign(other, auth.digest, NAMESPACE),
                _sign(owner, auth.digest, "sidedeck-paper-approval"),
                _sign(owner, _auth(max_requests=1).digest, NAMESPACE)):
        with pytest.raises(AuthorizationRefused, match="did not verify"):
            verify_authorization(auth, bad, verifier=verifier, principal="owner@sidedeck", now=NOW)
    with pytest.raises(AuthorizationRefused):
        verify_authorization(_auth(max_requests=1), good, verifier=verifier,
                             principal="owner@sidedeck", now=NOW)
    with pytest.raises(AuthorizationRefused, match="not currently valid"):
        verify_authorization(auth, good, verifier=verifier, principal="owner@sidedeck",
                             now=NOW + timedelta(days=2))
    wrong_ns = SshSignatureVerifier(str(signers), "owner@sidedeck")
    with pytest.raises(AuthorizationRefused, match="namespace"):
        verify_authorization(auth, good, verifier=wrong_ns, principal="owner@sidedeck", now=NOW)


def test_review_request_urls_must_match_exactly(tmp_path: Path) -> None:
    from sidedeck.application.sd078_alpaca_sip_pilot import draft_authorization as alpaca

    auth = alpaca(NOW - timedelta(minutes=1), owner_terms_reviewed=True)
    ledger = DataRequestLedger(tmp_path / "l.sqlite3", auth)
    base = "https://data.alpaca.markets/v2/stocks/SPY/bars"
    for bad in (base + "/../../../account", base + "/%2e%2e/orders", base + "/extra",
                "https://data.alpaca.markets/v2/stocks/SPY/bars//x"):
        with pytest.raises(AuthorizationRefused):
            ledger.reserve(bad, NOW)
    assert ledger.used() == 0
    ledger.reserve(base + "?timeframe=1Day&feed=sip", NOW)
    assert ledger.used() == 1


def test_review_authorization_can_be_claimed_once(tmp_path: Path) -> None:
    from sidedeck.application.sd077_data_authorization import claim_authorization

    auth_path, _ = prepare(_auth(), tmp_path)
    claim_authorization(auth_path, _auth())
    with pytest.raises(AuthorizationRefused, match="already used"):
        claim_authorization(auth_path, _auth())


def test_review_import_rejects_oversized_signed_budget_and_marks_partial(tmp_path: Path) -> None:
    big = _auth(max_requests=5)
    with pytest.raises(AuthorizationRefused, match="at most 2"):
        run_import(big, DataRequestLedger(tmp_path / "b.sqlite3", big), tmp_path / "b",
                   now=NOW, opener=_opener({}, []))
    auth = _auth()
    out = tmp_path / "out"
    with pytest.raises(ImportFailed):
        run_import(auth, DataRequestLedger(tmp_path / "l.sqlite3", auth), out, now=NOW,
                   opener=_opener({FILES["nasdaqlisted"]: (NASDAQ.encode(), 200),
                                   FILES["otherlisted"]: (b"", 500)}, []))
    status = (out / f"import-status-{auth.authorization_id}.json").read_text()
    assert "FAILED_PARTIAL" in status
