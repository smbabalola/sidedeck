"""SD-078 Alpaca SIP pilot runner. Mock transport; synthetic payloads; no network or keys."""
from __future__ import annotations

import io
import json
import urllib.error
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from sidedeck.application.sd077_data_authorization import AuthorizationRefused, DataRequestLedger
from sidedeck.application.sd078_alpaca_sip_pilot import (
    ENDPOINT,
    MAX_REQUESTS,
    PILOT_END,
    PILOT_START,
    PILOT_SYMBOLS,
    draft_authorization,
    proposal,
    run_pilot,
)
from sidedeck.application.us_equity_calendar import expected_regular_sessions

NOW = datetime(2026, 10, 22, 19, tzinfo=UTC)
SESSIONS = expected_regular_sessions(PILOT_START, PILOT_END)


def _payload(drop: int = 0) -> bytes:
    bars = [{"t": f"{d.isoformat()}T04:00:00Z", "o": 100, "h": 101 + (i % 3), "l": 99,
             "c": 100 + (i % 3) / 2, "v": 1000 + i} for i, d in enumerate(SESSIONS)]
    if drop:
        del bars[drop]
    return json.dumps({"bars": bars, "next_page_token": None}).encode()


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *a: object) -> None:
        self.close()


def _opener(calls: list[str], fail_on: str | None = None, drop_for: str | None = None) -> Any:
    def open_(request: Any, timeout: float = 20) -> _Resp:
        calls.append(request.full_url)
        assert request.full_url.startswith("https://data.alpaca.markets/v2/stocks/")
        assert "feed=sip" in request.full_url and "adjustment=split" in request.full_url
        assert "end=2026-10-23T23%3A59%3A59Z" in request.full_url   # final session included
        if fail_on and f"/{fail_on}/" in request.full_url:
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", None, None)  # type: ignore[arg-type]
        return _Resp(_payload(drop=5 if drop_for and f"/{drop_for}/" in request.full_url else 0))
    return open_


def _run(tmp_path: Path, opener: Any) -> tuple[dict[str, Any], DataRequestLedger]:
    auth = draft_authorization(NOW - timedelta(minutes=1), owner_terms_reviewed=True)
    ledger = DataRequestLedger(tmp_path / "l.sqlite3", auth)
    summary = run_pilot(auth, ledger, tmp_path / "out", key_id="k", secret="s",
                        now=lambda: NOW, opener=opener, pause=lambda: None)
    return summary, ledger


def test_proposal_is_bounded_and_honest() -> None:
    p = proposal()
    assert p["instrument_count"] == 20 == len(set(PILOT_SYMBOLS))
    assert p["max_authenticated_requests"] == MAX_REQUESTS and p["retries"] == 0
    assert p["broker_requests"] == 0 and p["orders"] == 0
    assert any("survivorship" in item for item in p["limitations"])
    assert p["estimated_bars"] == len(SESSIONS) * 20


def test_successful_pilot_one_request_per_symbol(tmp_path: Path) -> None:
    calls: list[str] = []
    summary, ledger = _run(tmp_path, _opener(calls, drop_for="IWM"))
    assert len(calls) == 20 == summary["requests_used"] == ledger.used()
    assert summary["stopped_early"] is None
    assert summary["coverage_counts"] == {"COVERED": 19, "PARTIALLY_COVERED": 1, "UNAVAILABLE": 0}
    assert summary["benchmark_status"] == "COVERED"
    assert "RESEARCH_DATA_ONLY" in summary["acceptance"]
    raw = (tmp_path / "out" / "raw").rglob("*.json")
    assert all("APCA" not in path.read_text() and '"s"' not in path.read_text() for path in raw)


def test_first_failure_stops_without_retry(tmp_path: Path) -> None:
    calls: list[str] = []
    summary, ledger = _run(tmp_path, _opener(calls, fail_on="IWM"))
    assert len(calls) == 3 and ledger.used() == 3       # SPY, QQQ, IWM(403), then stop
    assert summary["stopped_early"].startswith("IWM")
    assert summary["coverage_counts"]["UNAVAILABLE"] == 18


def test_scope_mismatch_and_reuse_refused(tmp_path: Path) -> None:
    auth = draft_authorization(NOW - timedelta(minutes=1), owner_terms_reviewed=True)
    narrow = type(auth)(**{**auth.__dict__, "urls": (ENDPOINT.format(symbol="SPY"),)})
    with pytest.raises(AuthorizationRefused, match="pilot symbol set"):
        run_pilot(narrow, DataRequestLedger(tmp_path / "n.sqlite3", narrow), tmp_path / "o",
                  key_id="k", secret="s", now=lambda: NOW, opener=_opener([]),
                  pause=lambda: None)
    ledger = DataRequestLedger(tmp_path / "l.sqlite3", auth)
    run_pilot(auth, ledger, tmp_path / "out", key_id="k", secret="s", now=lambda: NOW,
              opener=_opener([]))
    with pytest.raises(AuthorizationRefused, match="already exists"):
        run_pilot(auth, ledger, tmp_path / "out", key_id="k", secret="s", now=lambda: NOW,
                  opener=_opener([]))


def test_review_pilot_refuses_signed_budget_above_cap(tmp_path: Path) -> None:
    auth = draft_authorization(NOW - timedelta(minutes=1), owner_terms_reviewed=True)
    big = type(auth)(**{**auth.__dict__, "max_requests": MAX_REQUESTS + 1})
    with pytest.raises(AuthorizationRefused, match="at most"):
        run_pilot(big, DataRequestLedger(tmp_path / "l.sqlite3", big), tmp_path / "o",
                  key_id="k", secret="s", now=lambda: NOW, opener=_opener([]),
                  pause=lambda: None)


def test_draft_never_asserts_the_owner_terms_review():
    with pytest.raises(AuthorizationRefused, match="terms"):
        draft_authorization(NOW)
    from sidedeck.application.sd078_alpaca_sip_pilot import main
    with pytest.raises(SystemExit):
        main(["draft", "--out", "unused-never-written.json"])
    assert not Path("unused-never-written.json").exists()


def test_run_requires_explicit_credential_variable_names():
    from sidedeck.application.sd078_alpaca_sip_pilot import main
    with pytest.raises(SystemExit):
        main(["run", "--authorization", "a.json", "--signature", "a.sig"])


def test_proposal_scope_is_exact():
    p = proposal()
    assert p["instrument_count"] == 20 and len(set(PILOT_SYMBOLS)) == 20
    assert p["max_authenticated_requests"] == MAX_REQUESTS == 24 and p["retries"] == 0
    assert p["period"].endswith("2026-10-23")



import shutil  # noqa: E402
import subprocess  # noqa: E402
import hashlib as _hashlib  # noqa: E402

needs_ssh = pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="ssh-keygen missing")


def _signed_rig(tmp_path: Path, monkeypatch: Any, *, pin_test_key: bool = True):
    from sidedeck.application import sd078_alpaca_sip_pilot as pilot
    from sidedeck.application.sd077_data_authorization import NAMESPACE, prepare
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "t", "-f",
                    str(tmp_path / "k")], check=True, capture_output=True)
    blob = (tmp_path / "k.pub").read_text().split()[1]
    signers = tmp_path / "allowed_signers"
    signers.write_text(f"owner@sidedeck ssh-ed25519 {blob}" + chr(10))
    if pin_test_key:
        monkeypatch.setattr(pilot, "PINNED_SIGNER_KEY_SHA256",
                            _hashlib.sha256(blob.encode("ascii")).hexdigest())
    auth = draft_authorization(datetime.now(UTC) - timedelta(minutes=1),
                               owner_terms_reviewed=True)
    auth_path, _digest = prepare(auth, tmp_path / "auth")
    sig = subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(tmp_path / "k"), "-n", NAMESPACE],
                         input=auth.digest.encode(), capture_output=True, check=True).stdout
    (tmp_path / "auth.sig").write_bytes(sig)
    monkeypatch.delenv("SD078_TEST_MISSING_KEY", raising=False)
    (tmp_path / ".env").write_text("UNRELATED=1" + chr(10))
    calls: list[str] = []
    monkeypatch.setattr(pilot, "run_pilot", lambda *a, **k: calls.append("run") or {})
    args = ["run", "--authorization", str(auth_path), "--signature", str(tmp_path / "auth.sig"),
            "--allowed-signers", str(signers), "--env-file", str(tmp_path / ".env"),
            "--key-id-env", "SD078_TEST_MISSING_KEY", "--secret-env", "SD078_TEST_MISSING_SECRET",
            "--out-dir", str(tmp_path / "out")]
    return pilot, auth_path, args, calls


@needs_ssh
def test_missing_credential_never_burns_the_authorization(tmp_path, monkeypatch):
    pilot, auth_path, args, calls = _signed_rig(tmp_path, monkeypatch)
    with pytest.raises(Exception, match="credential"):
        pilot.main(args)
    assert not list(auth_path.parent.glob("*.consumed")) and calls == []


@needs_ssh
def test_unpinned_signer_is_refused_before_verification(tmp_path, monkeypatch):
    pilot, auth_path, args, calls = _signed_rig(tmp_path, monkeypatch, pin_test_key=False)
    with pytest.raises(Exception, match="pinned"):
        pilot.main(args)
    assert not list(auth_path.parent.glob("*.consumed")) and calls == []

def test_signed_spy_five_minute_collects_real_timestamp_shape_offline(tmp_path):
    from sidedeck.application.sd077_data_authorization import DataAuthorization
    from sidedeck.application.sd078_alpaca_sip_pilot import collect_signed_spy_five_minute

    auth = DataAuthorization(
        authorization_id="sd156-test", provider="ALPACA_SIP_INTRADAY",
        purpose="fixture five-minute fetch", urls=(ENDPOINT.format(symbol="SPY"),),
        max_requests=2, max_retries=0, credentials_required=True,
        issued_at=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(hours=1),
        owner_terms_reviewed=True,
        scope={"timeframe": "5Min", "feed": "sip", "adjustment": "split",
               "start": "2026-10-22T00:00:00Z", "end": "2026-10-23T00:00:00Z",
               "limit": "10000"},
    )
    ledger = DataRequestLedger(tmp_path / "intraday.sqlite3", auth)
    calls = []
    def opener(request, timeout=20):
        calls.append(request.full_url)
        rows = [{"t": "2026-10-22T13:30:00Z", "o": 100,
                 "h": 101, "l": 99, "c": 100, "v": 500}]
        return _Resp(json.dumps({"bars": rows, "next_page_token": None}).encode())
    out = collect_signed_spy_five_minute(
        auth, ledger, key_id="fixture", secret="fixture",
        now=lambda: NOW, opener=opener,
    )
    assert len(calls) == 1
    assert out["bars"][0]["timestamp_utc"] == "2026-10-22T13:30:00+00:00"
    assert out["strategy_admission_eligible"] is False
    assert out["broker_execution"] == "DISABLED"
    assert ledger.used() == 1



@pytest.mark.parametrize("stamp, expected", [
    ("2026-10-21T13:30:00Z", "outside signed date window"),
    ("2026-10-22T13:31:00Z", "off-grid"),
])
def test_signed_five_minute_rejects_invalid_bar_time(tmp_path, stamp, expected):
    from sidedeck.application.sd077_data_authorization import DataAuthorization
    from sidedeck.application.sd078_alpaca_sip_pilot import (
        MarketDataUnavailable, collect_signed_spy_five_minute,
    )
    auth = DataAuthorization(
        authorization_id="sd156-badtime", provider="ALPACA_SIP_INTRADAY",
        purpose="fixture", urls=(ENDPOINT.format(symbol="SPY"),),
        max_requests=2, max_retries=0, credentials_required=True,
        issued_at=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(hours=1),
        owner_terms_reviewed=True,
        scope={"timeframe": "5Min", "feed": "sip", "adjustment": "split",
               "start": "2026-10-22T00:00:00Z", "end": "2026-10-23T00:00:00Z",
               "limit": "10000"},
    )
    ledger = DataRequestLedger(tmp_path / "intraday.sqlite3", auth)
    def opener(request, timeout=20):
        rows = [{"t": stamp, "o": 100, "h": 101, "l": 99, "c": 100, "v": 500}]
        return _Resp(json.dumps({"bars": rows, "next_page_token": None}).encode())
    with pytest.raises(MarketDataUnavailable, match=expected):
        collect_signed_spy_five_minute(
            auth, ledger, key_id="fixture", secret="fixture",
            now=lambda: NOW, opener=opener,
        )
    assert ledger.used() == 1



def test_intraday_excludes_extended_hours_without_losing_opening_bar(tmp_path):
    from sidedeck.application.sd077_data_authorization import DataAuthorization
    from sidedeck.application.sd078_alpaca_sip_pilot import collect_signed_spy_five_minute

    auth = DataAuthorization(
        authorization_id="sd156-extended", provider="ALPACA_SIP_INTRADAY",
        purpose="fixture", urls=(ENDPOINT.format(symbol="SPY"),),
        max_requests=1, max_retries=0, credentials_required=True,
        issued_at=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(hours=1),
        owner_terms_reviewed=True,
        scope={"timeframe": "5Min", "feed": "sip", "adjustment": "split",
               "start": "2026-10-22T00:00:00Z", "end": "2026-10-23T00:00:00Z",
               "limit": "10000"},
    )
    ledger = DataRequestLedger(tmp_path / "extended.sqlite3", auth)
    def opener(request, timeout=20):
        rows = [{"t": t, "o": 100, "h": 101, "l": 99, "c": 100, "v": 500}
                for t in ("2026-10-22T12:30:00Z", "2026-10-22T13:30:00Z",
                          "2026-10-22T20:00:00Z")]
        return _Resp(json.dumps({"bars": rows, "next_page_token": None}).encode())
    result = collect_signed_spy_five_minute(
        auth, ledger, key_id="fixture", secret="fixture",
        now=lambda: NOW, opener=opener,
    )
    assert len(result["bars"]) == 1
    assert result["bars"][0]["timestamp_utc"] == "2026-10-22T13:30:00+00:00"
    assert result["excluded_extended_hours"] == 2
    assert result["strategy_admission_eligible"] is False

def test_intraday_draft_requires_explicit_owner_terms_and_is_network_free(tmp_path):
    from sidedeck.application.sd078_alpaca_sip_pilot import main
    target = tmp_path / "alpaca-5min.json"
    with pytest.raises(SystemExit):
        main(["draft-intraday", "--out", str(target)])
    assert not target.exists()
    assert main(["draft-intraday", "--out", str(target),
                 "--owner-confirms-terms-reviewed"]) == 0
    draft = json.loads(target.read_text(encoding="utf-8"))
    assert draft["provider"] == "ALPACA_SIP_INTRADAY"
    assert draft["urls"] == [ENDPOINT.format(symbol="SPY")]
    assert draft["scope"]["timeframe"] == "5Min"
    assert draft["scope"]["feed"] == "sip"
    assert draft["max_retries"] == 0
    with pytest.raises(SystemExit):
        main(["draft-intraday", "--out", str(target),
              "--owner-confirms-terms-reviewed"])


def test_intraday_accepts_alpaca_base64_page_token_and_paginates(tmp_path):
    from sidedeck.application.sd077_data_authorization import DataAuthorization
    from sidedeck.application.sd078_alpaca_sip_pilot import collect_signed_spy_five_minute
    from urllib.parse import parse_qs, urlsplit

    auth = DataAuthorization(
        authorization_id="sd156-base64", provider="ALPACA_SIP_INTRADAY",
        purpose="mock historical pagination", urls=(ENDPOINT.format(symbol="SPY"),),
        max_requests=2, max_retries=0, credentials_required=True,
        issued_at=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(hours=1),
        owner_terms_reviewed=True,
        scope={"timeframe": "5Min", "feed": "sip", "adjustment": "split",
               "start": "2026-10-22T00:00:00Z", "end": "2026-10-23T00:00:00Z",
               "limit": "10000"},
    )
    ledger = DataRequestLedger(tmp_path / "base64.sqlite3", auth)
    cursor = "QUFQTHxNfDIwMjItMDEtMDNUMDk6MDA6MDAuMDAwMDAwMDAwWg=="
    calls = []
    def opener(request, timeout=20):
        calls.append(request.full_url)
        query = parse_qs(urlsplit(request.full_url).query)
        assert query.get("page_token") == ([cursor] if len(calls) == 2 else None)
        stamp = "2026-10-22T13:30:00Z" if len(calls) == 1 else "2026-10-22T13:35:00Z"
        return _Resp(json.dumps({
            "bars": [{"t": stamp, "o": 100, "h": 101, "l": 99, "c": 100, "v": 500}],
            "next_page_token": cursor if len(calls) == 1 else None,
        }).encode())
    result = collect_signed_spy_five_minute(
        auth, ledger, key_id="fixture", secret="fixture",
        now=lambda: NOW, opener=opener,
    )
    assert result["pages"] == 2
    assert len(result["bars"]) == 2
    assert ledger.used() == 2
    assert result["strategy_admission_eligible"] is False


def test_intraday_checkpoint_survives_page_budget_exhaustion(tmp_path):
    from sidedeck.application.sd077_data_authorization import DataAuthorization
    from sidedeck.application.sd078_alpaca_sip_pilot import (
        MarketDataUnavailable, collect_signed_spy_five_minute,
    )
    auth = DataAuthorization(
        authorization_id="sd156-checkpoint", provider="ALPACA_SIP_INTRADAY",
        purpose="mock pagination limit", urls=(ENDPOINT.format(symbol="SPY"),),
        max_requests=1, max_retries=0, credentials_required=True,
        issued_at=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(hours=1),
        owner_terms_reviewed=True,
        scope={"timeframe": "5Min", "feed": "sip", "adjustment": "split",
               "start": "2026-10-22T00:00:00Z", "end": "2026-10-23T00:00:00Z",
               "limit": "10000"},
    )
    ledger = DataRequestLedger(tmp_path / "ledger.sqlite3", auth)
    directory = tmp_path / "checkpoints"
    def opener(request, timeout=20):
        return _Resp(json.dumps({
            "bars": [{"t": "2026-10-22T13:30:00Z",
                      "o": 100, "h": 101, "l": 99, "c": 100, "v": 500}],
            "next_page_token": "bmV4dA==",
        }).encode())
    with pytest.raises(MarketDataUnavailable, match="page budget exhausted"):
        collect_signed_spy_five_minute(
            auth, ledger, key_id="fixture", secret="fixture",
            now=lambda: NOW, opener=opener, checkpoint_dir=directory,
        )
    progress = json.loads((directory / "progress.json").read_text())
    page = json.loads((directory / "page-001.json").read_text())
    assert progress["complete"] is False
    assert progress["pages"] == 1
    assert progress["page_accepted_count"] == 1
    assert page[0]["timestamp_utc"] == "2026-10-22T13:30:00+00:00"
    assert ledger.used() == 1
    import hashlib
    assert progress["page_sha256"] == hashlib.sha256((directory / "page-001.json").read_bytes()).hexdigest()
    assert "bmV4dA" not in (directory / "progress.json").read_text()

