"""SD-094 bounded UK requests: part A verifier and single-GET runner (fake opener only);
parts B and C are templates and can never be executed from this module."""
from __future__ import annotations

import json
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from sidedeck.application import sd094_uk_data_requests as sd094
from sidedeck.application.sd077_data_authorization import AuthorizationRefused, DataRequestLedger
from sidedeck.application.sd089_exchange_calendar import UK_CLOSURES

NOW = datetime(2026, 10, 23, 15, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_: Any, **__: Any) -> None:
        raise AssertionError("network access attempted in an offline SD-094 test")
    monkeypatch.setattr(socket.socket, "connect", refuse)


def _feed(drop: int = 0) -> str:
    events = [{"date": d.isoformat(), "title": t} for d, t in sorted(UK_CLOSURES.items())]
    return json.dumps({"england-and-wales": {"division": "england-and-wales",
                                             "events": events[drop:]}})


class _Fake:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.status, self._body, self.calls = status, body, 0

    def __call__(self, request: Any, timeout: float) -> "_Fake":
        self.calls += 1
        assert request.full_url == sd094.URL_A and "Authorization" not in request.headers
        return self

    def read(self, n: int = -1) -> bytes:
        return self._body

    def __enter__(self) -> "_Fake":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_verifier_matches_and_reports_mismatches_without_correcting() -> None:
    assert sd094.verify_against_gov_uk(_feed())["status"] == "MATCHED"
    mismatch = sd094.verify_against_gov_uk(_feed(drop=1))
    assert mismatch["status"] == "MISMATCH"
    assert mismatch["half_days"]["status"] == "NOT_IN_SOURCE"
    with pytest.raises(sd094.CalendarCheckFailed):
        sd094.verify_against_gov_uk("{}")


def test_part_a_makes_exactly_one_unauthenticated_get(tmp_path: Path) -> None:
    auth = sd094.draft_authorization_a(NOW)
    ledger = DataRequestLedger(tmp_path / "ledger.sqlite3", auth)
    fake = _Fake(_feed().encode("utf-8"))
    summary = sd094.run_part_a(auth, ledger, tmp_path / "out", now=NOW, opener=fake)
    assert fake.calls == 1 and summary["requests_used"] == 1
    assert summary["comparison"]["status"] == "MATCHED"
    assert (tmp_path / "out" / "raw" / auth.authorization_id / "bank-holidays.json").is_file()
    with pytest.raises(sd094.CalendarCheckFailed, match="refusing to overwrite"):
        sd094.run_part_a(auth, ledger, tmp_path / "out", now=NOW, opener=fake)
    assert fake.calls == 1


def test_part_a_failures_stop_without_retry(tmp_path: Path) -> None:
    auth = sd094.draft_authorization_a(NOW)
    fake = _Fake(b"oops", status=503)
    with pytest.raises(sd094.CalendarCheckFailed, match="not retried"):
        sd094.run_part_a(auth, DataRequestLedger(tmp_path / "l.sqlite3", auth), tmp_path / "o",
                         now=NOW, opener=fake)
    assert fake.calls == 1


def test_part_a_refuses_a_broadened_authorization(tmp_path: Path) -> None:
    from dataclasses import replace
    auth = replace(sd094.draft_authorization_a(NOW), max_requests=2)
    with pytest.raises(AuthorizationRefused):
        sd094.run_part_a(auth, DataRequestLedger(tmp_path / "l.sqlite3", sd094.draft_authorization_a(NOW)),
                         tmp_path / "o", now=NOW, opener=_Fake(b""))


def test_parts_b_and_c_are_templates_that_never_send(capsys: pytest.CaptureFixture[str]) -> None:
    for key in ("B", "C"):
        t = sd094.REQUEST_TEMPLATES[key]
        assert t["status"] == "TEMPLATE_ONLY_NOT_AUTHORIZED" and t["max_requests"] == 5
        assert "never the MSFT pilot budget" in " ".join(sd094.REQUEST_TEMPLATES["B"]["preconditions"])
    assert not hasattr(sd094, "run_part_b") and not hasattr(sd094, "run_part_c")
    assert sd094.main(["templates"]) == 0
    assert "NETWORK_REQUESTS=0" in capsys.readouterr().out
