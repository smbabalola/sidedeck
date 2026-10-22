"""SD-079 per-track paper ledgers. Synthetic decisions and prices; simulated fills only."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from sidedeck.application.sd071_decision_engine import Decision, SizingProposal
from sidedeck.application.sd072_track_risk_limits import TrackLimits
from sidedeck.application.sd079_track_ledgers import LedgerError, TrackBook, TrackLedger

NOW = datetime(2026, 10, 22, 15, tzinfo=UTC)
SIZING = SizingProposal(Decimal("2"), Decimal("200"), Decimal("96"), 15, "STOP_OR_TIME_EXIT_15")
LIMITS = TrackLimits("SWING", Decimal("0.10"), Decimal("0.03"), 5)
PRICES = {"US:AAA": Decimal("100"), "US:BBB": Decimal("100")}


def _decision(track: str = "SWING", status: str = "ELIGIBLE", cid: str = "US:AAA") -> Decision:
    return Decision(status, cid, track, "fixture-policy", NOW, ("BINDING_LIMIT:X",),
                    qualified_signal_ids=("s1",),
                    sizing=SIZING if status == "ELIGIBLE" else None)


def _open(ledger: TrackLedger, ref: str, decision: Decision | None = None,
          limits: TrackLimits = LIMITS, fee: str = "0", at: datetime = NOW) -> None:
    ledger.open_from_decision(ref, decision or _decision(), Decimal("100"), Decimal(fee), at,
                              limits=limits, prices=PRICES,
                              session_start_equity=ledger.initial_capital)


def test_open_close_accounting_and_replay(tmp_path: Path) -> None:
    db = tmp_path / "swing.sqlite3"
    ledger = TrackLedger.open(db, "SWING", Decimal("1000"))
    _open(ledger, "p1", fee="1")
    assert ledger.cash == Decimal("799") and ledger.equity({"US:AAA": Decimal("100")}) == 999
    pnl = ledger.close("p1", Decimal("110"), Decimal("1"), NOW + timedelta(days=3), "TIME_EXIT")
    assert pnl == Decimal("18") and ledger.cash == Decimal("1018") and ledger.fees == 2
    again = TrackLedger.open(db, "SWING", Decimal("1000"))    # crash recovery by replay
    assert again.cash == ledger.cash and again.realized_pnl == pnl and not again.positions
    with pytest.raises(LedgerError, match="different track"):
        TrackLedger.open(db, "DAY", Decimal("1000"))


@pytest.mark.parametrize("decision, limits, message", [
    (_decision(track="DAY"), LIMITS, "another track"),
    (_decision(), TrackLimits("DAY", Decimal("0.1"), Decimal("0.03"), 5), "another track"),
    (_decision(status="WATCHLIST"), LIMITS, "ELIGIBLE"),
    (_decision(), TrackLimits("SWING", Decimal("0.1"), Decimal("0.03"), 0), "risk gate"),
])
def test_entry_refusals(tmp_path: Path, decision: Decision, limits: TrackLimits,
                        message: str) -> None:
    ledger = TrackLedger.open(tmp_path / "l.sqlite3", "SWING", Decimal("1000"))
    with pytest.raises(LedgerError, match=message):
        _open(ledger, "p1", decision, limits)


def test_cash_duplicate_and_timing_guards(tmp_path: Path) -> None:
    ledger = TrackLedger.open(tmp_path / "l.sqlite3", "SWING", Decimal("150"))
    with pytest.raises(LedgerError, match="cash"):
        _open(ledger, "p1")
    rich = TrackLedger.open(tmp_path / "r.sqlite3", "SWING", Decimal("1000"))
    with pytest.raises(LedgerError, match="after the decision"):
        _open(rich, "p1", at=NOW - timedelta(seconds=1))
    _open(rich, "p1")
    with pytest.raises(LedgerError, match="duplicate"):
        _open(rich, "p1")
    with pytest.raises(LedgerError, match="mark price"):
        rich.equity({})


def test_gate_is_recomputed_so_entry_cap_cannot_be_bypassed(tmp_path: Path) -> None:
    ledger = TrackLedger.open(tmp_path / "l.sqlite3", "SWING", Decimal("1000"))
    one_per_day = TrackLimits("SWING", Decimal("0.5"), Decimal("0.5"), 1)
    _open(ledger, "p1", limits=one_per_day)
    with pytest.raises(LedgerError, match="ORDER_FREQUENCY_LIMIT"):
        _open(ledger, "p2", _decision(cid="US:BBB"), limits=one_per_day)


def test_two_instances_cannot_double_spend(tmp_path: Path) -> None:
    db = tmp_path / "shared.sqlite3"
    a = TrackLedger.open(db, "SWING", Decimal("300"))
    b = TrackLedger.open(db, "SWING", Decimal("300"))
    _open(a, "p1")                                   # spends 200 of 300
    with pytest.raises(LedgerError, match="cash"):   # b catches up before validating
        _open(b, "p2", _decision(cid="US:BBB"))
    with pytest.raises(LedgerError, match="duplicate"):
        _open(b, "p1")
    assert b.cash == Decimal("100") and set(b.positions) == {"p1"}
    b.close("p1", Decimal("100"), Decimal(0), NOW + timedelta(days=1), "x")
    with pytest.raises(LedgerError, match="not open"):
        a.close("p1", Decimal("100"), Decimal(0), NOW + timedelta(days=1), "x")
    assert TrackLedger.open(db, "SWING", Decimal("300")).cash == Decimal("300")


def test_tracks_are_segregated(tmp_path: Path) -> None:
    book = TrackBook.open(tmp_path / "book", {"DAY": Decimal("500"), "SWING": Decimal("1000"),
                                              "POSITION": Decimal("1000")})
    swing = book.ledger("SWING")
    _open(swing, "p1")
    with pytest.raises(LedgerError, match="not open in this track"):
        book.ledger("DAY").close("p1", Decimal("100"), Decimal(0), NOW, "x")
    assert book.ledger("DAY").cash == Decimal("500")
    swing.mark({"US:AAA": Decimal("80")}, NOW)
    gate = swing.risk_gate(TrackLimits("SWING", Decimal("0.03"), Decimal("0.5"), 9),
                           {"US:AAA": Decimal("80")}, Decimal("1000"), "2026-10-23")
    assert "MAX_DRAWDOWN_BREACHED" in gate.reasons
    with pytest.raises(LedgerError):
        book.ledger("CRYPTO")
