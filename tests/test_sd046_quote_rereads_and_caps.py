"""Option B (owner decision 2026-10-26): signed caps enforced at runtime, stale-only quote
re-reads. Offline simulator only; synthetic IDs; no network."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from sidedeck.application import sd046_etoro_demo_pilot as sd046
from sidedeck.application.sd046_etoro_demo_pilot import (
    MAX_TOTAL_REQUESTS, ROUTE_CAPS, SD044_CAPS, EtoroDemoPilot, PilotBudget,
    PilotBudgetExhausted, PilotError, PilotTransport, check_caps,
)
from sidedeck.domain.etoro_demo_orders import MARKET_DATA_RATES_PATH
from tests.test_sd046_etoro_demo_pilot import PILOT_INSTRUMENT, SCOPE, Rig

PILOT_ID = "0b6f3c1e-8a2d-4e5f-9a7b-1c2d3e4f5a6b"
CAPS_15 = {**SD044_CAPS, "rates": 4}


# ---- caps -------------------------------------------------------------------------------

def test_ceilings_are_the_owner_approved_option_b_values():
    assert ROUTE_CAPS["rates"] == 4 and sum(ROUTE_CAPS.values()) == MAX_TOTAL_REQUESTS == 15
    assert ROUTE_CAPS["open"] + ROUTE_CAPS["close"] == 2
    assert sum(SD044_CAPS.values()) == 12 and SD044_CAPS["rates"] == 1
    assert check_caps(CAPS_15) == CAPS_15


@pytest.mark.parametrize("caps", [
    {**CAPS_15, "rates": 5},                       # above the per-route ceiling
    {**CAPS_15, "open": 2},                        # above ceiling and > 2 writes
    {**CAPS_15, "pnl": -1},
    {**CAPS_15, "pnl": 1.0},                       # not an int
    {k: v for k, v in CAPS_15.items() if k != "pnl"},
    {**CAPS_15, "candles": 1},                     # unknown route
])
def test_invalid_caps_refused(caps):
    with pytest.raises(PilotError):
        check_caps(caps)


def test_default_budget_is_the_original_12_request_plan(tmp_path):
    budget = PilotBudget(str(tmp_path / "b.sqlite3"))
    try:
        assert budget.caps == SD044_CAPS and budget.total_cap == 12
        budget.reserve("rates")
        with pytest.raises(PilotBudgetExhausted, match="rates budget 1"):
            budget.reserve("rates")
    finally:
        budget.close()


def test_signed_caps_bind_and_persist_across_restart(tmp_path):
    path = str(tmp_path / "b.sqlite3")
    budget = PilotBudget(path, pilot_id=PILOT_ID, caps=CAPS_15)
    for _ in range(2):
        budget.reserve("rates")
    budget.close()
    again = PilotBudget(path, pilot_id=PILOT_ID, caps=CAPS_15)   # restart: no fresh allowance
    try:
        again.reserve("rates")
        again.reserve("rates")
        with pytest.raises(PilotBudgetExhausted, match="rates budget 4"):
            again.reserve("rates")
        assert again.usage()["rates"] == 4
    finally:
        again.close()


def test_tighter_signed_caps_are_enforced_not_the_code_ceiling(tmp_path):
    caps = {**CAPS_15, "rates": 2, "lookup": 1}
    budget = PilotBudget(str(tmp_path / "b.sqlite3"), pilot_id=PILOT_ID, caps=caps)
    try:
        budget.reserve("lookup")
        with pytest.raises(PilotBudgetExhausted, match="lookup budget 1"):
            budget.reserve("lookup")
        budget.reserve("rates")
        budget.reserve("rates")
        with pytest.raises(PilotBudgetExhausted):
            budget.reserve("rates")
    finally:
        budget.close()


def test_total_cap_counts_every_route_including_unexpected_rows(tmp_path):
    path = str(tmp_path / "b.sqlite3")
    budget = PilotBudget(path, pilot_id=PILOT_ID, caps=CAPS_15)
    try:
        # A foreign row for this pilot (e.g. a tampered ledger) still counts in the total.
        budget._db.execute("INSERT INTO sd046_pilot_budget_scoped VALUES (?, 'legacy', 15)",
                           (PILOT_ID,))
        with pytest.raises(PilotBudgetExhausted, match="total budget 15"):
            budget.reserve("pnl")
    finally:
        budget.close()


def test_pilot_refuses_budget_caps_that_differ_from_the_signed_release(tmp_path):
    rig = Rig(tmp_path)
    try:
        release = SimpleNamespace(intent=SimpleNamespace(
            scope=lambda: SCOPE, request_caps=tuple(sorted(CAPS_15.items()))))
        with pytest.raises(PilotError, match="caps differ"):
            EtoroDemoPilot(desk=rig.desk, transport=rig.transport, budget=rig.budget,
                           controls=rig.controls, lineage=rig.lineage, baseline=rig.baseline,
                           scope=SCOPE, release=release)
    finally:
        rig.shutdown()


# ---- stale-only quote re-reads -----------------------------------------------------------

class QuoteRig(Rig):
    """Rig with the Option B caps and a scripted sequence of quote timestamps."""

    def __init__(self, tmp_path, stamps, *, caps=CAPS_15, quote_type="realtime"):
        super().__init__(tmp_path)
        self.budget.close()
        self.budget = PilotBudget(str(tmp_path / "pilot15.sqlite3"), caps=caps)
        self.transport = PilotTransport(self.sim, self.budget)
        self.desk._transport = self.transport
        self.sleeps: list[float] = []
        self.stamps = list(stamps)
        self.rates_calls = 0
        inner = self.sim.send

        def send(method, path, **kw):
            if method == "GET" and path == MARKET_DATA_RATES_PATH:
                self.rates_calls += 1
                stamp = self.stamps.pop(0)(datetime.now(timezone.utc))
                return {"results": [{"instrumentId": PILOT_INSTRUMENT, "bid": 99.9,
                                     "ask": 100.0, "date": stamp, "quoteType": quote_type}]}
            return inner(method, path, **kw)

        self.sim.send = send
        self.pilot = EtoroDemoPilot(desk=self.desk, transport=self.transport,
                                    budget=self.budget, controls=self.controls,
                                    lineage=self.lineage, baseline=self.baseline, scope=SCOPE,
                                    sleep=self.sleeps.append)


def naive(age_s):
    """eToro-style naive UTC stamp `age_s` seconds before the read."""
    return lambda now: (now - timedelta(seconds=age_s)).replace(tzinfo=None).isoformat(
        timespec="milliseconds")


def fixed(moment):
    return lambda now: moment.replace(tzinfo=None).isoformat(timespec="milliseconds")


@pytest.fixture
def make(tmp_path):
    rigs = []

    def factory(stamps, **kw):
        folder = tmp_path / str(len(rigs))
        folder.mkdir()
        r = QuoteRig(folder, stamps, **kw)
        rigs.append(r)
        return r

    yield factory
    for r in rigs:
        r.shutdown()


def test_stale_then_fresh_quote_is_accepted_after_spaced_rereads(make):
    rig = make([naive(72), naive(72), naive(3)])
    result = rig.pilot.preflight()
    assert result["result"] == "READY_FOR_OPEN_APPROVAL"
    assert rig.rates_calls == 3 and rig.sleeps == [15.0, 15.0]
    assert result["requests_used"]["rates"] == 3 and rig.writes() == []
    assert datetime.now(timezone.utc) - rig.pilot._quote.observed_at < timedelta(seconds=60)


def test_four_stale_quotes_abort_with_no_write_and_no_fifth_read(make):
    rig = make([naive(72)] * 5)
    result = rig.pilot.preflight()
    assert result["result"] == "ABORTED_PREFLIGHT" and "stale" in result["reason"]
    assert rig.rates_calls == 4 and rig.sleeps == [15.0] * 3
    assert result["writes"] == 0 and rig.writes() == [] and result["kill_switch"] == "CLEAR"
    assert result["requests_total"] <= 15


@pytest.mark.parametrize("stamps,kw,reason", [
    ([naive(-30)], {}, "future-dated"),                                   # future: no re-read
    ([naive(3)], {"quote_type": "delayed"}, "not realtime"),
    ([lambda now: "not-a-time"], {}, "invalid"),
])
def test_non_stale_quote_failures_abort_immediately(make, stamps, kw, reason):
    rig = make(stamps, **kw)
    result = rig.pilot.preflight()
    assert result["result"] == "ABORTED_PREFLIGHT" and reason in result["reason"]
    assert rig.rates_calls == 1 and rig.sleeps == [] and rig.writes() == []


def test_quote_time_moving_backwards_aborts(make):
    t0 = datetime.now(timezone.utc) - timedelta(seconds=70)
    rig = make([fixed(t0), fixed(t0 - timedelta(seconds=10))])
    result = rig.pilot.preflight()
    assert result["result"] == "ABORTED_PREFLIGHT" and "backwards" in result["reason"]
    assert rig.rates_calls == 2 and rig.writes() == []


def test_unchanged_snapshot_counts_as_stale_not_backwards(make):
    t0 = datetime.now(timezone.utc) - timedelta(seconds=70)
    rig = make([fixed(t0)] * 4)
    result = rig.pilot.preflight()
    assert result["result"] == "ABORTED_PREFLIGHT" and "stale" in result["reason"]
    assert rig.rates_calls == 4


def test_legacy_single_read_caps_never_reread(make):
    rig = make([naive(72), naive(3)], caps=SD044_CAPS)
    result = rig.pilot.preflight()
    assert result["result"] == "ABORTED_PREFLIGHT" and "stale" in result["reason"]
    assert rig.rates_calls == 1 and rig.sleeps == []


def test_quote_age_is_measured_after_the_response_arrives(make, monkeypatch):
    """A slow round trip must count against freshness (no free round trip)."""
    clock = {"now": datetime(2026, 10, 27, 14, 30, tzinfo=timezone.utc)}

    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"]

    stamp = clock["now"] - timedelta(seconds=59)       # 59 s old when the request is sent

    def slow(now):
        clock["now"] += timedelta(seconds=2)            # response arrives 2 s later: 61 s old
        return stamp.replace(tzinfo=None).isoformat(timespec="milliseconds")

    rig = make([slow], caps=SD044_CAPS)
    monkeypatch.setattr(sd046, "datetime", FakeDateTime)
    result = rig.pilot.preflight()
    assert result["result"] == "ABORTED_PREFLIGHT" and "age 61.0 s" in result["reason"]


def test_full_round_trip_with_rereads_stays_within_15_requests_and_2_writes(make):
    rig = make([naive(80), naive(80), naive(80), naive(2)])
    opened = rig.open()
    assert opened["result"] == "OPEN_FILLED_AWAITING_CLOSE_APPROVAL"
    done = rig.close()
    assert done["result"] == "COMPLETE"
    assert done["requests_total"] <= 15 and done["writes"] == 2
    assert len(rig.writes()) == 2


# ---- review follow-ups (Fable, 2026-10-26) ------------------------------------------------

def test_budget_exhausted_mid_reread_after_restart_aborts_without_write(make):
    rig = make([naive(72)] * 4)
    for _ in range(2):                       # two quote reads already recorded before a restart
        rig.budget.reserve("rates")
    result = rig.pilot.preflight()
    assert result["result"] == "ABORTED_PREFLIGHT" and "budget" in result["reason"]
    assert rig.rates_calls == 2 and rig.writes() == [] and result["requests_used"]["rates"] == 4


def test_shape_error_on_a_reread_stops_further_reads(make):
    rig = make([naive(72), lambda now: None])     # second read: response lacks a usable date
    original = rig.sim.send

    def broken(method, path, **kw):
        result = original(method, path, **kw)
        if path == MARKET_DATA_RATES_PATH and rig.rates_calls == 2:
            return {"results": "drift"}
        return result

    rig.sim.send = broken
    result = rig.pilot.preflight()
    assert result["result"] == "ABORTED_PREFLIGHT" and "stale" not in result["reason"]
    assert rig.rates_calls == 2 and rig.sleeps == [15.0] and rig.writes() == []


def test_kill_switch_tripped_between_rereads_aborts(make):
    rig = make([naive(72)] * 4)
    rig.pilot._sleep = lambda seconds: rig.controls.trip("test", "halt during re-read")
    result = rig.pilot.preflight()
    assert result["result"] == "ABORTED_PREFLIGHT" and "kill switch" in result["reason"]
    assert rig.rates_calls == 1 and rig.writes() == []


def test_open_rechecks_the_latest_quote_after_rereads(make):
    import dataclasses
    rig = make([naive(72), naive(72), naive(3)])
    assert rig.pilot.preflight()["result"] == "READY_FOR_OPEN_APPROVAL"
    _, scope = rig.pilot.open_approval_scope()
    rig.approve("pilot-open", scope)
    quote = rig.pilot._quote
    rig.pilot._quote = dataclasses.replace(quote, observed_at=quote.observed_at
                                           - timedelta(minutes=6))
    result = rig.pilot.open_phase(intent_id="pilot-open")
    assert result["result"] == "ABORTED_PREFLIGHT" and rig.writes() == []


def test_failed_reread_audit_row_records_the_rates_payload(make, tmp_path):
    from sidedeck.application.sd058_forensic_audit import PreflightAudit
    rig = make([naive(72)] * 4)
    audit = PreflightAudit(str(tmp_path / "audit.sqlite3"), "d" * 64)
    try:
        rig.pilot._audit = audit
        assert rig.pilot.preflight()["result"] == "ABORTED_PREFLIGHT"
        rows = audit.rows()
        assert [r["outcome"] for r in rows].count("QUOTE_STALE_REREAD") == 3
        final = rows[-1]
        assert final["outcome"] == "ABORTED_PREFLIGHT" and final["request_type"] == "rates"
        assert "quoteType" in final["schema_json"] and "eligibilities" not in final["schema_json"]
    finally:
        audit.close()


def test_transport_ledger_and_pilot_budget_enforce_the_same_signed_caps(tmp_path):
    """Both runtime counters are bound to the new intent's signed caps (rates 4, total 15)."""
    from sidedeck.application import sd053_msft_pilot_intent as sd053
    from sidedeck.infrastructure.etoro_demo_write_transport import (
        EtoroDemoTransportError, _ReleaseLedger,
    )
    intent = sd053.build_intent(PILOT_ID)
    assert dict(intent.request_caps) == CAPS_15
    release = SimpleNamespace(digest=intent.digest(), intent=intent)
    ledger = _ReleaseLedger(str(tmp_path / "ledger.sqlite3"), release)
    budget = PilotBudget(str(tmp_path / "budget.sqlite3"), pilot_id=PILOT_ID,
                         caps=dict(intent.request_caps))
    try:
        for _ in range(4):
            ledger.reserve("rates")
            budget.reserve("rates")
        with pytest.raises(EtoroDemoTransportError, match="CAP_EXHAUSTED"):
            ledger.reserve("rates")
        with pytest.raises(PilotBudgetExhausted):
            budget.reserve("rates")
        assert budget.total_cap == 15
    finally:
        ledger.close()
        budget.close()
