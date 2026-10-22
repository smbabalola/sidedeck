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
        assert "end=2026-10-21T23%3A59%3A59Z" in request.full_url   # final session included
        if fail_on and f"/{fail_on}/" in request.full_url:
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", None, None)  # type: ignore[arg-type]
        return _Resp(_payload(drop=5 if drop_for and f"/{drop_for}/" in request.full_url else 0))
    return open_


def _run(tmp_path: Path, opener: Any) -> tuple[dict[str, Any], DataRequestLedger]:
    auth = draft_authorization(NOW - timedelta(minutes=1))
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
    auth = draft_authorization(NOW - timedelta(minutes=1))
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
    auth = draft_authorization(NOW - timedelta(minutes=1))
    big = type(auth)(**{**auth.__dict__, "max_requests": MAX_REQUESTS + 1})
    with pytest.raises(AuthorizationRefused, match="at most"):
        run_pilot(big, DataRequestLedger(tmp_path / "l.sqlite3", big), tmp_path / "o",
                  key_id="k", secret="s", now=lambda: NOW, opener=_opener([]),
                  pause=lambda: None)
