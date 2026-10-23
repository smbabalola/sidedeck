from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from sidedeck.application.sd090_uk_market import NormalizedQuote
from sidedeck.application.sd093_uk_sim_desk import (
    FillPlan,
    SimDeskError,
    SimInterruption,
    SimVenueMapping,
    UkOrderIntent,
    UkSimDesk,
)

CID = "UK:ZZSYN0000020"
OPEN = datetime(2026, 10, 23, 8, 0, tzinfo=UTC)      # 09:00 BST
LATER = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)
BOOK = "SIM_UK_SWING"


def _quote(at: datetime, bid: str = "8.68", ask: str = "8.70", cid: str = CID,
           unit: str = "GBP") -> NormalizedQuote:
    b, a = Decimal(bid), Decimal(ask)
    return NormalizedQuote(cid, "TEST", "SYNTHETIC_FIXTURE", "test", at - timedelta(seconds=10),
                           "GBX", unit, b, a, (a + b) / 2, (a - b) / ((a + b) / 2) * 10_000)


def _desk(tmp: Path, name: str = "d.sqlite3", asset: str = "COMMON_STOCK",
          step: str = "1", book: str = BOOK) -> UkSimDesk:
    mapping = SimVenueMapping(CID, "SIDEDECK_SIM_LSE", "SIM:1", asset, Decimal("10"),
                              Decimal(step))
    return UkSimDesk(tmp / name, book_id=book, capital_gbp=Decimal("1000"),
                     mappings={CID: mapping})


def _intent(iid: str, qty: str, at: datetime = OPEN, side: str = "BUY",
            limit: str | None = None, book: str = BOOK) -> UkOrderIntent:
    default = "8.70" if side == "BUY" else "8.68"
    return UkOrderIntent(iid, book, CID, side, Decimal(qty), Decimal(limit or default),
                         "CONTROLLED_EXECUTION_FIXTURE", at)


def test_round_trip_reconciles_and_fees_are_in_cost_basis(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    entry = desk.submit(_intent("e1", "17"), _quote(OPEN), OPEN)
    assert (entry.status, entry.filled_quantity, entry.avg_price_gbp) == (
        "FILLED", Decimal(17), Decimal("8.70"))
    assert entry.fees_gbp == Decimal("0.74")  # 0.5% stamp duty on 147.90
    assert entry.label == "SIMULATION" and entry.fill_basis == "SIMULATED_LOCAL"
    open_rec = desk.reconcile()
    assert open_rec.status == "MATCHED" and open_rec.positions[0].quantity == 17
    exit_ = desk.submit(_intent("x1", "17", LATER, "SELL", "8.75"),
                        _quote(LATER, "8.75", "8.77"), LATER)
    assert exit_.status == "FILLED" and exit_.fees_gbp == 0  # no stamp duty on sales
    final = desk.reconcile()
    assert final.status == "MATCHED" and final.positions == ()
    assert final.cash_gbp - Decimal(1000) == final.realized_pnl_gbp == Decimal("0.11")
    # Crash safety: a fresh desk object replays the same book from disk.
    again = _desk(tmp_path)
    assert again.reconcile() == final


def test_etf_purchases_have_no_stamp_duty(tmp_path: Path) -> None:
    desk = _desk(tmp_path, asset="ETF")
    assert desk.submit(_intent("e1", "10"), _quote(OPEN), OPEN).fees_gbp == 0


@pytest.mark.parametrize(("intent_kw", "quote_kw", "now", "reason"), [
    ({}, {"at": OPEN}, OPEN + timedelta(minutes=5), "STALE_QUOTE"),
    ({}, {"at": OPEN + timedelta(minutes=1)}, OPEN, "FUTURE_QUOTE"),
    ({}, {"at": OPEN, "unit": "GBX"}, OPEN, "QUOTE_NOT_NORMALIZED_TO_GBP"),
    ({}, {"at": OPEN, "cid": "UK:OTHER"}, OPEN, "QUOTE_INSTRUMENT_MISMATCH"),
    ({}, {"at": datetime(2026, 10, 24, 10, tzinfo=UTC)},
     datetime(2026, 10, 24, 10, tzinfo=UTC), "MARKET_CLOSED"),
    ({}, {"at": datetime(2026, 8, 31, 10, tzinfo=UTC)},
     datetime(2026, 8, 31, 10, tzinfo=UTC), "MARKET_CLOSED"),
    ({"qty": "1"}, {"at": OPEN}, OPEN, "BELOW_MINIMUM_ORDER"),
    ({"qty": "1.5"}, {"at": OPEN}, OPEN, "QUANTITY_NOT_A_MULTIPLE_OF_STEP"),
    ({"limit": "8.69"}, {"at": OPEN}, OPEN, "LIMIT_BELOW_ASK_NOT_MARKETABLE"),
    ({"qty": "200"}, {"at": OPEN}, OPEN, "INSUFFICIENT_SIM_CASH"),
    ({"side": "SELL", "qty": "5"}, {"at": OPEN}, OPEN, "SELL_EXCEEDS_SIM_POSITION"),
    ({"book": "SIM_UK_POSITION"}, {"at": OPEN}, OPEN, "BOOK_MISMATCH_PROTECTED_SEPARATION"),
])
def test_pre_trade_refusals(tmp_path: Path, intent_kw: dict[str, str], quote_kw: dict[str, object],
                            now: datetime, reason: str) -> None:
    desk = _desk(tmp_path)
    kw = {"qty": "5", **intent_kw}
    result = desk.submit(_intent("r1", kw.pop("qty"), **kw), _quote(**quote_kw), now)  # type: ignore[arg-type]
    assert (result.status, result.reason) == ("REJECTED", reason)
    assert desk.reconcile().status == "MATCHED" and desk.reconcile().cash_gbp == 1000


def test_missing_mapping_and_protected_books(tmp_path: Path) -> None:
    desk = UkSimDesk(tmp_path / "m.sqlite3", book_id=BOOK, capital_gbp=Decimal(1000), mappings={})
    assert desk.submit(_intent("m1", "5"), _quote(OPEN), OPEN).reason == "MISSING_VENUE_MAPPING"
    for book in ("ETORO_DEMO_BASELINE", "ETORO_DEMO_MSFT_PILOT", "SWING", "US_SWING", "UK_X"):
        with pytest.raises(SimDeskError, match="PROTECTED_OR_NON_SIMULATION_BOOK"):
            UkSimDesk(tmp_path / f"{book}.sqlite3", book_id=book, capital_gbp=Decimal(1),
                      mappings={})
    with pytest.raises(SimDeskError, match="BOOK_FILE_BELONGS_TO_ANOTHER_BOOK"):
        _desk(tmp_path, "m.sqlite3", book="SIM_UK_POSITION")


def test_strategy_intents_need_eligible_decisions() -> None:
    with pytest.raises(SimDeskError, match="ELIGIBLE"):
        UkOrderIntent("s", BOOK, CID, "BUY", Decimal(1), Decimal(1), "STRATEGY_DECISION", OPEN,
                      decision_status="WATCHLIST")
    with pytest.raises(SimDeskError, match="SIMULATION"):
        UkOrderIntent("s", BOOK, CID, "BUY", Decimal(1), Decimal(1),
                      "CONTROLLED_EXECUTION_FIXTURE", OPEN, label="DEMO")
    with pytest.raises(SimDeskError, match="unknown intent source"):
        UkOrderIntent("s", BOOK, CID, "BUY", Decimal(1), Decimal(1), "AGENT_OPINION", OPEN)


def test_partial_fill_and_duplicate_intent(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    part = desk.submit(_intent("p1", "10"), _quote(OPEN), OPEN, plan=FillPlan(Decimal("0.45")))
    assert (part.status, part.filled_quantity) == ("PARTIALLY_FILLED", Decimal(4))
    dup = desk.submit(_intent("p1", "10"), _quote(OPEN), OPEN)
    assert dup.reason == "DUPLICATE_INTENT_ORIGINAL_RESULT" and dup.filled_quantity == 4
    fills = [k for k, _, _ in desk.events() if k in ("FILLED", "PARTIALLY_FILLED")]
    assert fills == ["PARTIALLY_FILLED"] and desk.reconcile().status == "MATCHED"


def test_interrupted_execution_recovers_by_lookup_only(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    with pytest.raises(SimInterruption):
        desk.submit(_intent("i1", "5"), _quote(OPEN), OPEN, plan=FillPlan(crash_after_venue=True))
    restarted = _desk(tmp_path)
    assert restarted.submit(_intent("i2", "5"), _quote(OPEN), OPEN).reason == \
        "PRIOR_ORDER_OUTCOME_PENDING"
    assert restarted.submit(_intent("i1", "5"), _quote(OPEN), OPEN).status == "SUBMITTED"
    (res,) = restarted.recover(OPEN + timedelta(minutes=1))
    assert res.status == "FILLED" and res.filled_quantity == 5
    assert [k for k, _, _ in restarted.events()].count("SUBMITTED") == 1
    assert restarted.reconcile().status == "MATCHED"


def test_interrupted_before_any_venue_fill_cancels(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    with pytest.raises(SimInterruption):
        desk.submit(_intent("c1", "5"), _quote(OPEN), OPEN,
                    plan=FillPlan(Decimal("0.1"), crash_after_venue=True))
    (res,) = desk.recover(OPEN)
    assert res.status == "CANCELLED_UNFILLED" and desk.reconcile().status == "MATCHED"


def test_unknown_exit_outcome_trips_kill_switch(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    desk.submit(_intent("u1", "5"), _quote(OPEN), OPEN)
    with pytest.raises(SimInterruption):
        desk.submit(_intent("u2", "5", LATER, "SELL"), _quote(LATER), LATER,
                    plan=FillPlan(crash_after_venue=True, venue_lookup_available=False))
    (res,) = desk.recover(LATER)
    assert res.status == "UNRESOLVED" and desk.kill_switch
    rec = desk.reconcile()
    assert rec.status == "UNRESOLVED"
    assert [p.status for p in rec.positions] == ["MAY_BE_OPEN_UNRESOLVED"]
    assert desk.submit(_intent("u3", "5", LATER), _quote(LATER), LATER).reason == \
        "KILL_SWITCH_ACTIVE"


def test_event_log_is_append_only(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    desk.submit(_intent("a1", "5"), _quote(OPEN), OPEN)
    conn = sqlite3.connect(tmp_path / "d.sqlite3")
    try:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("UPDATE events SET kind='REJECTED'")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("DELETE FROM events")
    finally:
        conn.close()


def test_fractional_quantity_step(tmp_path: Path) -> None:
    desk = _desk(tmp_path, step="0.1")
    assert desk.submit(_intent("f1", "1.5"), _quote(OPEN), OPEN).status == "FILLED"


def test_review_m2_reused_intent_id_with_different_params_is_refused(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    assert desk.submit(_intent("d1", "5"), _quote(OPEN), OPEN).status == "FILLED"
    other = desk.submit(_intent("d1", "6"), _quote(OPEN), OPEN)
    assert (other.status, other.reason) == ("REJECTED", "INTENT_ID_REUSED_WITH_DIFFERENT_PARAMS")
    assert [k for k, _, _ in desk.events()].count("FILLED") == 1


def test_review_l2_desk_refuses_foreign_database_files(tmp_path: Path) -> None:
    path = tmp_path / "pilot.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE baseline_positions (id TEXT)")
    conn.commit()
    conn.close()
    with pytest.raises(SimDeskError, match="FILE_IS_NOT_A_UK_SIMULATION_BOOK"):
        UkSimDesk(path, book_id=BOOK, capital_gbp=Decimal(1000), mappings={})
    conn = sqlite3.connect(path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert tables == {"baseline_positions"}  # nothing was created inside the foreign file
