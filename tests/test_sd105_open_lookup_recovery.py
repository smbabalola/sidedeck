"""SD-105 finding (2026-10-26, pilot 4119f25c): the eToro Demo BUY was accepted (referenceId
echoed, orderId linked) and filled at the broker, but ``orders:lookup`` 0.8 s later returned
404 and SideDeck halted as if the order had vanished. Offline simulator only; synthetic IDs.
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from decimal import Decimal
from urllib.error import HTTPError

import pytest

from sidedeck.application import sd046_etoro_demo_pilot as sd046
from sidedeck.application.sd036_etoro_demo_desk import AcceptedOrderNotVisible
from sidedeck.application.sd046_etoro_demo_pilot import SD044_CAPS, UNRESOLVED
from sidedeck.domain.etoro_demo import parse_demo_portfolio
from sidedeck.domain.etoro_demo_books import EtoroDemoBookError
from sidedeck.domain.etoro_demo_orders import DEMO_ORDER_LOOKUP_PATH, EtoroDemoOrderError
from sidedeck.infrastructure.etoro_demo_write_transport import _problem_summary
from tests.test_sd046_quote_rereads_and_caps import QuoteRig, naive

CAPS_15 = {**SD044_CAPS, "rates": 4}                       # today's signed allocation
CAPS_PNL4 = {**CAPS_15, "pnl": 4, "lookup": 2}             # proposed; needs owner approval
BASELINE_POSITION_IDS = {11, 12, 13, 14}


@pytest.fixture
def make(tmp_path, monkeypatch):
    monkeypatch.setattr(sd046, "OPEN_LOOKUP_DELAYS", (3.0, 5.0, 8.0))
    rigs = []

    def factory(*, caps=CAPS_15, not_visible=0):
        folder = tmp_path / str(len(rigs))
        folder.mkdir()
        rig = QuoteRig(folder, [naive(2)], caps=caps)
        rig.sim.lookup_not_visible = not_visible
        rig.lookups = []
        inner = rig.sim.send

        def send(method, path, **kw):
            if path == DEMO_ORDER_LOOKUP_PATH:
                rig.lookups.append(dict(kw.get("query") or {}))
            return inner(method, path, **kw)

        rig.sim.send = send
        rigs.append(rig)
        return rig

    yield factory
    for r in rigs:
        r.shutdown()


# ---- the 2026-10-26 sequence ---------------------------------------------------------------

def test_replay_404_right_after_acceptance_no_longer_halts(make):
    """One 404 (as observed live), then the order is visible by its linked orderId."""
    rig = make(not_visible=1)
    opened = rig.open()
    assert opened["result"] == "OPEN_FILLED_AWAITING_CLOSE_APPROVAL"
    assert opened["kill_switch"] == "CLEAR" and opened["sidedeck_open_positions"] == 1
    assert rig.sleeps[-2:] == [3.0, 5.0]               # waits before each lookup, not 0.8 s
    assert list(rig.lookups[0]) == ["referenceId"] and list(rig.lookups[1]) == ["orderId"]
    assert opened["entry"]["source"].startswith("BROKER_REPORTED (orders:lookup")
    done = rig.close()
    assert done["result"] == "COMPLETE" and done["writes"] == 2
    assert done["requests_total"] <= 15 and len(rig.writes()) == 2


def test_first_lookup_waits_before_reading(make):
    rig = make()
    opened = rig.open()
    assert opened["result"] == "OPEN_FILLED_AWAITING_CLOSE_APPROVAL"
    assert rig.sleeps[-1:] == [3.0] and len(rig.lookups) == 1
    assert list(rig.lookups[0]) == ["referenceId"]


def test_never_visible_with_signed_pnl_cap_3_stops_without_spending_close_budget(make):
    """Today's caps leave no /pnl room to recover and still close: stop, never resubmit."""
    rig = make(not_visible=99)
    opened = rig.open()
    assert opened["result"] == UNRESOLVED and "no room" in opened["reason"]
    assert opened["kill_switch"] == "HALTED" and opened["writes"] == 1
    assert opened["requests_used"]["lookup"] == 3 and opened["requests_used"]["pnl"] == 1
    assert len(rig.writes()) == 1                       # the one open; no close, no resubmit
    assert [list(q) for q in rig.lookups] == [["referenceId"], ["orderId"], ["orderId"]]


def test_never_visible_is_recovered_from_pnl_when_owner_signs_pnl_4(make, monkeypatch):
    monkeypatch.setattr(sd046, "ROUTE_CAPS", {**sd046.ROUTE_CAPS, "pnl": 4})
    rig = make(caps=CAPS_PNL4, not_visible=99)
    opened = rig.open()
    assert opened["result"] == "OPEN_FILLED_AWAITING_CLOSE_APPROVAL"
    assert opened["open_status"] == "RECONCILED_FILLED_BY_SNAPSHOT"
    assert opened["kill_switch"] == "CLEAR" and opened["sidedeck_open_positions"] == 1
    entry = opened["entry"]
    assert entry["source"].startswith("BROKER_REPORTED (/pnl orderID")
    assert Decimal(entry["units"]) == Decimal("0.4")
    assert Decimal(entry["avg_price"]) == Decimal("100.25")
    assert entry["fees"].startswith("NOT_REPORTED")
    done = rig.close()
    assert done["result"] == "COMPLETE" and done["requests_used"]["pnl"] == 4
    assert done["requests_total"] <= 15 and done["writes"] == 2


def test_pnl_4_ceiling_is_not_in_force_without_owner_approval():
    assert sd046.ROUTE_CAPS["pnl"] == 3
    with pytest.raises(sd046.PilotError):
        sd046.check_caps(CAPS_PNL4)


def test_kill_switch_during_lookup_waits_stops_further_lookups(make):
    rig = make(not_visible=99)
    original = rig.pilot._sleep

    def trip_on_second_wait(seconds):
        original(seconds)
        if seconds == 5.0:
            rig.controls.trip("test", "operator halt during lookups")

    rig.pilot._sleep = trip_on_second_wait
    opened = rig.open()
    assert opened["result"] == UNRESOLVED and len(rig.lookups) == 1
    assert len(rig.writes()) == 1


# ---- desk-level /pnl recovery is strict ----------------------------------------------------

def _accepted_open(rig):
    """Preflight, approve and submit the open; no lookup is made."""
    assert rig.pilot.preflight()["result"] == "READY_FOR_OPEN_APPROVAL"
    request, scope = rig.pilot.open_approval_scope()
    rig.approve("pilot-open", scope)
    state = rig.desk.submit_open(intent_id="pilot-open", strategy="tradingagents",
                                 request=request, quote=rig.pilot._quote,
                                 eligibility=rig.pilot._eligibility)
    assert state == "ACCEPTED"
    return request


def _snapshot(rig, mutate=None, extra=None):
    payload = rig.sim.pnl_payload(rig.sim.baseline_rows)
    rows = payload["clientPortfolio"]["positions"]
    pilot_rows = [r for r in rows if r["positionID"] not in BASELINE_POSITION_IDS]
    if mutate:
        for row in pilot_rows:
            mutate(row)
    if extra:
        rows.append(extra(pilot_rows[0]))
    return parse_demo_portfolio(payload, observed_at=datetime.now(timezone.utc))


@pytest.mark.parametrize("mutate,extra,match", [
    (lambda r: r.update(instrumentID=2003), None, "instrument"),
    (lambda r: r.update(isBuy=False), None, "direct 1x long"),
    (lambda r: r.update(leverage=2), None, "direct 1x long"),
    (lambda r: r.update(mirrorID=55), None, "direct 1x long|does not reconcile"),
    (lambda r: r.update(units=0.5), None, "units"),
    (lambda r: r.update(openRate=100.6), None, "open rate"),
    (lambda r: r.pop("openRate"), None, "open rate"),
    (None, lambda r: {**r, "positionID": r["positionID"] + 1}, "more than one"),
])
def test_contradicting_pnl_halts_and_registers_nothing(make, mutate, extra, match):
    rig = make()
    request = _accepted_open(rig)
    with pytest.raises(EtoroDemoBookError, match=match):
        rig.desk.recover_open_from_snapshot(request.reference_id,
                                            snapshot=_snapshot(rig, mutate, extra),
                                            now=datetime.now(timezone.utc))
    assert rig.controls.is_halted() and rig.lineage.owned_positions() == []


def test_no_pnl_position_for_the_order_is_inconclusive_and_halts(make):
    rig = make()
    request = _accepted_open(rig)
    rig.sim._orders[request.reference_id]["positionExecutions"] = []   # nothing at broker
    with pytest.raises(EtoroDemoOrderError, match="not visible"):
        rig.desk.recover_open_from_snapshot(request.reference_id, snapshot=_snapshot(rig),
                                            now=datetime.now(timezone.utc))
    assert rig.controls.is_halted()
    assert rig.lineage.order(request.reference_id)["state"] == "NOT_FOUND_INCONCLUSIVE"


def test_recovery_refuses_a_baseline_position_claiming_the_order(make):
    rig = make()
    request = _accepted_open(rig)
    order_id = rig.lineage.order(request.reference_id)["order_id"]
    rig.sim._orders[request.reference_id]["positionExecutions"] = []
    rows = [dict(r) for r in rig.sim.baseline_rows]
    rows[0].update(orderID=order_id, instrumentID=2002, units=0.4, openRate=100.0)
    snapshot = parse_demo_portfolio(rig.sim.pnl_payload(rows),
                                    observed_at=datetime.now(timezone.utc))
    with pytest.raises(EtoroDemoBookError):
        rig.desk.recover_open_from_snapshot(request.reference_id, snapshot=snapshot,
                                            now=datetime.now(timezone.utc))
    assert rig.lineage.owned_positions() == [] and rig.controls.is_halted()


def test_recovery_refuses_a_stale_snapshot(make):
    rig = make()
    request = _accepted_open(rig)
    old = datetime(2026, 10, 26, 17, 0, tzinfo=timezone.utc)
    snapshot = parse_demo_portfolio(rig.sim.pnl_payload(rig.sim.baseline_rows), observed_at=old)
    with pytest.raises(Exception, match="stale"):
        rig.desk.recover_open_from_snapshot(request.reference_id, snapshot=snapshot,
                                            now=datetime.now(timezone.utc))
    assert rig.lineage.owned_positions() == []


def test_recovery_only_for_an_accepted_unfilled_open(make):
    rig = make()
    opened = rig.open()                                   # lookup visible: already FILLED
    assert opened["result"] == "OPEN_FILLED_AWAITING_CLOSE_APPROVAL"
    reference = rig.lineage.orders()[0]["reference_id"]
    with pytest.raises(EtoroDemoOrderError, match="accepted, unfilled"):
        rig.desk.recover_open_from_snapshot(reference, snapshot=_snapshot(rig),
                                            now=datetime.now(timezone.utc))


def test_default_refresh_open_still_halts_on_missing_accepted_order(make):
    """``recover()`` keeps the conservative behaviour: a 404 for a linked order halts."""
    rig = make(not_visible=1)
    request = _accepted_open(rig)
    with pytest.raises(EtoroDemoOrderError, match="no longer reports"):
        rig.desk.refresh_open(request.reference_id)
    assert rig.controls.is_halted()


def test_not_visible_does_not_halt_when_the_caller_handles_it(make):
    rig = make(not_visible=1)
    request = _accepted_open(rig)
    with pytest.raises(AcceptedOrderNotVisible):
        rig.desk.refresh_open(request.reference_id, halt_on_missing=False)
    assert not rig.controls.is_halted()
    assert rig.desk.refresh_open(request.reference_id, by_order_id=True).status_id == 3


# ---- evidence capture ----------------------------------------------------------------------

def _http_404(body: bytes) -> HTTPError:
    return HTTPError("https://example.invalid", 404, "Not Found", None, io.BytesIO(body))


def test_404_problem_details_are_kept_without_identifiers():
    body = json.dumps({"type": "about:blank", "title": "Order not found", "status": 404,
                       "detail": "No order for reference  x" + "y" * 300,
                       "instance": "/accounts/123456/orders", "traceId": "abc"}).encode()
    summary = _problem_summary(_http_404(body))
    assert summary.startswith("status=404; title=Order not found; detail=No order")
    assert "123456" not in summary and "abc" not in summary and " " not in summary
    assert len(summary) < 300


@pytest.mark.parametrize("body,expected", [
    (b"", "empty body"), (b"<html>", "body unreadable"), (b"[1]", "body not an object"),
    (b"{}", "no title/detail"), (b"x" * 5000, "body too large"),
])
def test_unusual_404_bodies_are_classified(body, expected):
    assert _problem_summary(_http_404(body)) == expected


def test_pnl_open_rate_is_parsed_and_optional():
    row = {"positionID": 7, "instrumentID": 2002, "orderID": 70, "isBuy": True, "units": 0.09,
           "amount": 47.75, "leverage": 1, "openDateTime": "2026-10-26T17:17:46Z",
           "openRate": 530.65}
    portfolio = {"positions": [row], "credit": 0, "bonusCredit": 0, "accountCurrencyId": 1,
                 "mirrors": [], "orders": [], "ordersForOpen": [], "ordersForClose": [],
                 "ordersForCloseMultiple": [], "entryOrders": [], "exitOrders": [],
                 "stockOrders": []}
    now = datetime.now(timezone.utc)
    snap = parse_demo_portfolio({"clientPortfolio": portfolio}, observed_at=now)
    assert snap.positions[0].open_rate == Decimal("530.65")
    del row["openRate"]
    assert parse_demo_portfolio({"clientPortfolio": portfolio},
                                observed_at=now).positions[0].open_rate is None


# ---- independent review follow-ups (Fable, 2026-10-27) -------------------------------------

def test_recovery_refuses_while_the_order_is_still_pending(make):
    rig = make()
    request = _accepted_open(rig)
    order_id = rig.lineage.order(request.reference_id)["order_id"]
    payload = rig.sim.pnl_payload(rig.sim.baseline_rows)
    payload["clientPortfolio"]["ordersForOpen"] = [{"orderID": order_id, "amount": 10}]
    snapshot = parse_demo_portfolio(payload, observed_at=datetime.now(timezone.utc))
    with pytest.raises(EtoroDemoBookError, match="pending"):
        rig.desk.recover_open_from_snapshot(request.reference_id, snapshot=snapshot,
                                            now=datetime.now(timezone.utc))
    assert rig.controls.is_halted() and rig.lineage.owned_positions() == []


@pytest.mark.parametrize("damage", [
    lambda rows: rows.append({**rows[0], "positionID": 99, "orderID": 4242}),   # unexplained
    lambda rows: rows.remove(rows[0]),                                           # baseline gone
])
def test_recovery_refuses_a_snapshot_that_does_not_reconcile(make, damage):
    rig = make()
    request = _accepted_open(rig)
    payload = rig.sim.pnl_payload(rig.sim.baseline_rows)
    damage(payload["clientPortfolio"]["positions"])
    snapshot = parse_demo_portfolio(payload, observed_at=datetime.now(timezone.utc))
    with pytest.raises(EtoroDemoBookError, match="does not reconcile"):
        rig.desk.recover_open_from_snapshot(request.reference_id, snapshot=snapshot,
                                            now=datetime.now(timezone.utc))
    assert rig.controls.is_halted() and rig.lineage.owned_positions() == []


def test_seen_non_terminal_then_404_stops_with_an_explicit_reason(make, monkeypatch):
    monkeypatch.setattr(sd046, "ROUTE_CAPS", {**sd046.ROUTE_CAPS, "pnl": 4})
    rig = make(caps={**CAPS_PNL4, "lookup": 3, "rates": 3})
    rig.sim.mode = "PENDING"                         # first lookup: PLACED (not terminal)
    inner = rig.sim.send

    def send(method, path, **kw):
        if path == DEMO_ORDER_LOOKUP_PATH and len(rig.lookups) == 2:
            rig.sim.lookup_not_visible = 99          # then it disappears from lookup
        return inner(method, path, **kw)

    rig.sim.send = send
    opened = rig.open()
    assert opened["result"] == UNRESOLVED and "seen by lookup" in opened["reason"]
    assert opened["requests_used"]["pnl"] == 1 and len(rig.writes()) == 1


def test_interrupt_during_lookup_wait_trips_the_kill_switch(make):
    rig = make()

    def interrupted(seconds):
        raise KeyboardInterrupt

    assert rig.pilot.preflight()["result"] == "READY_FOR_OPEN_APPROVAL"
    _, scope = rig.pilot.open_approval_scope()
    rig.approve("pilot-open", scope)
    rig.pilot._sleep = interrupted
    with pytest.raises(KeyboardInterrupt):
        rig.pilot.open_phase(intent_id="pilot-open")
    assert rig.controls.is_halted() and len(rig.writes()) == 1


def test_lookup_by_order_id_returning_another_order_halts(make):
    rig = make()
    request = _accepted_open(rig)
    linked = rig.lineage.order(request.reference_id)["order_id"]
    original = rig.sim.send

    def other_order(method, path, **kw):
        result = original(method, path, **kw)
        if path == DEMO_ORDER_LOOKUP_PATH:
            return {**result, "orderId": linked + 1}  # broker reports a different order
        return result

    rig.sim.send = other_order
    with pytest.raises(EtoroDemoOrderError):
        rig.desk.refresh_open(request.reference_id, by_order_id=True, halt_on_missing=False)
    assert rig.controls.is_halted() and rig.lineage.owned_positions() == []


def test_404_detail_identifiers_are_masked():
    body = json.dumps({"status": 404, "title": "Order not found",
                       "detail": "order 390542302 ref 45c9c00c-4168-47cb-87b1-b52ba978b85d "
                                 "account 12345"}).encode()
    summary = _problem_summary(_http_404(body))
    assert "390542302" not in summary and "45c9c00c" not in summary and "12345" not in summary
    assert summary.startswith("status=404; title=Order not found; detail=order # ref #")
