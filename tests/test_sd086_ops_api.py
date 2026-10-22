"""SD-086 read-only ops summaries. Ledgers are built with simulated fixtures only."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sidedeck.application.sd071_decision_engine import Decision, SizingProposal
from sidedeck.application.sd072_track_risk_limits import TrackLimits
from sidedeck.application.sd075a_nasdaq_universe_import import FILES
from sidedeck.application.sd077_data_authorization import DataAuthorization, DataRequestLedger
from sidedeck.application.sd079_track_ledgers import TrackBook
from sidedeck.application.sd086_ops_api import authorization_ledger_summary, track_ledgers_summary

NOW = datetime(2026, 10, 22, 15, tzinfo=UTC)


def _decision(cid: str) -> Decision:
    return Decision("ELIGIBLE", cid, "SWING", "fixture", NOW, ("x",), qualified_signal_ids=("s",),
                    sizing=SizingProposal(Decimal(2), Decimal(200), Decimal(96), 15, "TIME"))


def test_track_ledgers_summary_matches_ledger_accounting(tmp_path: Path) -> None:
    book = TrackBook.open(tmp_path, {"SWING": Decimal(1000), "DAY": Decimal(500)})
    swing = book.ledger("SWING")
    limits = TrackLimits("SWING", Decimal("0.5"), Decimal("0.5"), 9)
    prices = {"US:AAA": Decimal(100), "US:BBB": Decimal(100)}
    for ref, cid in (("p1", "US:AAA"), ("p2", "US:BBB")):
        swing.open_from_decision(ref, _decision(cid), Decimal(100), Decimal(1), NOW, limits=limits,
                                 prices=prices, session_start_equity=Decimal(1000))
    swing.close("p1", Decimal(110), Decimal(1), NOW + timedelta(days=2), "TIME")
    s = track_ledgers_summary(str(tmp_path))
    assert s["provenance"] == "SIMULATION" and s["fill_basis"] == "SIMULATED_LOCAL"
    by = {t["track"]: t for t in s["tracks"]}
    assert by["SWING"]["cash"] == str(swing.cash)
    assert by["SWING"]["realized_pnl"] == str(swing.realized_pnl)
    assert by["SWING"]["open_positions"] == 1 and by["SWING"]["entries"] == 2
    assert by["SWING"]["closes"] == 1 and by["SWING"]["fees"] == str(swing.fees)
    assert by["DAY"]["status"] == "ACTIVE" and by["POSITION"]["status"] == "NOT_STARTED"
    assert not (tmp_path / "position-ledger.sqlite3").exists()      # never created


def test_track_ledgers_unavailable_and_tamper(tmp_path: Path) -> None:
    assert track_ledgers_summary(None)["status"] == "UNAVAILABLE"
    TrackBook.open(tmp_path, {"SWING": Decimal(1000)})
    with sqlite3.connect(tmp_path / "swing-ledger.sqlite3") as conn:
        conn.execute("INSERT INTO events (kind, payload) VALUES ('HACK', '{}')")
    by = {t["track"]: t for t in track_ledgers_summary(str(tmp_path))["tracks"]}
    assert by["SWING"]["status"] == "UNAVAILABLE"


def test_authorization_ledger_summary(tmp_path: Path) -> None:
    assert authorization_ledger_summary(None)["status"] == "UNAVAILABLE"
    missing = tmp_path / "none.sqlite3"
    assert authorization_ledger_summary(str(missing))["status"] == "UNAVAILABLE"
    assert not missing.exists()
    auth = DataAuthorization("a1", "NASDAQ_TRADER_SYMBOL_DIRECTORY", "test", tuple(FILES.values()),
                             2, 0, False, NOW - timedelta(minutes=1), NOW + timedelta(hours=1), True)
    ledger = DataRequestLedger(tmp_path / "l.sqlite3", auth)
    ledger.record(ledger.reserve(FILES["nasdaqlisted"], NOW), "OK")
    ledger.reserve(FILES["otherlisted"], NOW)
    s = authorization_ledger_summary(str(tmp_path / "l.sqlite3"))
    assert s["status"] == "LOADED" and s["execution_enabled"] is False
    entry = s["authorizations"][0]
    assert entry["requests"] == 2 and entry["outcomes"] == {"OK": 1, "RESERVED": 1}
    assert entry["digest_prefix"] == auth.digest[:12] and "url" not in entry
