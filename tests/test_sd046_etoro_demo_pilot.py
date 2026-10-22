"""SD-046 pilot runner against the offline simulator only. Synthetic IDs; no network."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sidedeck.application.sd032_durable_paper_intent import DurablePaperIntentStore
from sidedeck.application.sd033_approval_killswitch import ApprovalKillSwitch, intent_digest
from sidedeck.application.sd036_etoro_demo_desk import (
    SYNTHETIC_BASELINE_ROWS, BrokerExecutionDisabled, DemoDeskPolicy, DemoRateBudget,
    EtoroDemoDesk, EtoroDemoLineage, OfflineEtoroDemoSimulator, open_scope,
)
from sidedeck.application.sd046_etoro_demo_pilot import (
    UNRESOLVED, EtoroDemoPilot, PilotBudget, PilotBudgetExhausted, PilotError, PilotScope,
    PilotTransport,
)
from sidedeck.domain.etoro_demo import parse_demo_portfolio
from sidedeck.domain.etoro_demo_books import BaselinePosition
from sidedeck.domain.etoro_demo_orders import DEMO_PNL_PATH, DemoOpenRequest

BOOK = "etoro-demo:tradingagents"
PILOT_INSTRUMENT = 2002          # not in the synthetic baseline (all 1001)
SCOPE = PilotScope("tradingagents", PILOT_INSTRUMENT, Decimal("0.4"), Decimal("100.5"),
                   Decimal("100"))


def verify(key, digest, signature):
    return signature == f"{key}:{digest}"


class Rig:
    def __init__(self, tmp_path, scope=SCOPE):
        self.tmp, self.scope = tmp_path, scope
        self.sim = OfflineEtoroDemoSimulator(fill_price=Decimal("100.25"))
        self.sim.baseline_rows = [dict(r) for r in SYNTHETIC_BASELINE_ROWS]
        self.baseline = tuple(BaselinePosition.of(p) for p in parse_demo_portfolio(
            self.sim.pnl_payload(SYNTHETIC_BASELINE_ROWS),
            observed_at=datetime.now(timezone.utc)).positions)
        self.controls = ApprovalKillSwitch(str(tmp_path / "controls.sqlite3"), verify)
        self.lineage = EtoroDemoLineage(str(tmp_path / "lineage.sqlite3"),
                                        baseline_position_ids=[b.position_id for b in self.baseline],
                                        baseline_order_ids=[b.order_id for b in self.baseline])
        self.outbox = DurablePaperIntentStore(str(tmp_path / "outbox.sqlite3"))
        self.rate = DemoRateBudget(str(tmp_path / "rate.sqlite3"))
        self.budget = PilotBudget(str(tmp_path / "pilot.sqlite3"))
        self.transport = PilotTransport(self.sim, self.budget)
        self.desk = EtoroDemoDesk(outbox=self.outbox, controls=self.controls, lineage=self.lineage,
                                  transport=self.transport,
                                  policy=DemoDeskPolicy(Decimal("50"),
                                                        frozenset({PILOT_INSTRUMENT}), 1),
                                  baseline=self.baseline, budget=self.rate)
        try:
            self.pilot = EtoroDemoPilot(desk=self.desk, transport=self.transport,
                                        budget=self.budget, controls=self.controls,
                                        lineage=self.lineage, baseline=self.baseline, scope=scope)
        except Exception:
            self.shutdown()
            raise

    def approve(self, intent_id, scope):
        digest = intent_digest(intent_id, scope)
        self.controls.approve(f"a-{intent_id}", intent_id, scope, "sidedeck", "owner", "pk",
                              f"pk:{digest}", datetime.now(timezone.utc) + timedelta(minutes=10))

    def open(self):
        request = DemoOpenRequest(str(uuid.uuid4()), PILOT_INSTRUMENT, self.scope.units,
                                  self.scope.limit_rate)
        self.approve("pilot-open", open_scope(BOOK, request))
        return self.pilot.open_phase(intent_id="pilot-open", request=request)

    def close(self):
        request, scope = self.pilot.close_request(str(uuid.uuid4()))
        if not self.controls.is_halted():
            self.approve("pilot-close", scope)
        return self.pilot.close_phase(intent_id="pilot-close", request=request)

    def shutdown(self):
        for store in (self.outbox, self.controls, self.lineage, self.rate, self.budget):
            store.close()

    def writes(self):
        return [c for c in self.sim.calls if c[0] == "POST"]


@pytest.fixture
def rig(tmp_path):
    r = Rig(tmp_path)
    yield r
    r.shutdown()


def test_complete_pilot_within_caps(rig):
    opened = rig.open()
    assert opened["result"] == "OPEN_FILLED_AWAITING_CLOSE_APPROVAL"
    assert opened["sidedeck_open_positions"] == 1
    result = rig.close()
    assert result["result"] == "COMPLETE" and result["sidedeck_open_positions"] == 0
    assert result["writes"] == 2 and result["requests_total"] <= 11
    assert result["requests_used"]["pnl"] == 3 and result["kill_switch"] == "CLEAR"
    assert result["baseline_matched"] == 4 and result["execution_release"] == "NO_GO"
    assert len(rig.writes()) == 2


@pytest.mark.parametrize("scope,match", [
    (PilotScope("tradingagents", 2002, Decimal("1"), Decimal("100.5"), Decimal("100")), "USD 50"),
    (PilotScope("tradingagents", 2002, Decimal("0.4"), Decimal("100.6"), Decimal("100")), "0.5"),
    (PilotScope("tradingagents", 1001, Decimal("0.4"), Decimal("100.5"), Decimal("100")),
     "baseline"),
    (PilotScope("unknown", 2002, Decimal("0.4"), Decimal("100.5"), Decimal("100")), "strategy"),
])
def test_scope_violations_refused_before_any_request(tmp_path, scope, match):
    with pytest.raises(PilotError, match=match):
        Rig(tmp_path, scope)


def test_open_request_must_equal_scope(rig):
    request = DemoOpenRequest(str(uuid.uuid4()), PILOT_INSTRUMENT, Decimal("0.3"),
                              SCOPE.limit_rate)
    with pytest.raises(PilotError, match="scope"):
        rig.pilot.open_phase(intent_id="x", request=request)
    assert rig.sim.calls == []


def test_changed_baseline_aborts_preflight_without_writes(rig):
    rig.sim.baseline_rows[0]["units"] = 3
    result = rig.open()
    assert result["result"] == "ABORTED_PREFLIGHT" and result["writes"] == 0
    assert rig.writes() == []


def test_rejected_open_is_clean_and_never_closes(rig):
    rig.sim.mode = "REJECT"
    result = rig.open()
    assert result["result"] == "OPEN_REJECTED_CLEAN" and result["writes"] == 1
    assert result["sidedeck_open_positions"] == 0
    with pytest.raises(PilotError, match="no verified"):
        rig.pilot.close_request(str(uuid.uuid4()))


def test_lost_open_response_recovered_by_lookup_and_stays_halted(rig):
    rig.sim.lose_next_response = True
    result = rig.open()
    assert result["result"] == "OPEN_FILLED_AWAITING_CLOSE_APPROVAL"
    assert result["kill_switch"] == "HALTED" and len(rig.writes()) == 1
    blocked = rig.close()                       # halted: close refused, unresolved
    assert blocked["result"] == UNRESOLVED and len(rig.writes()) == 1
    assert blocked["sidedeck_open_positions"] == 1


def test_open_not_terminal_within_budget_is_unresolved(rig):
    rig.sim.mode = "PENDING"
    result = rig.open()
    assert result["result"] == UNRESOLVED and result["kill_switch"] == "HALTED"
    assert result["requests_used"]["lookup"] == 3


@pytest.mark.parametrize("setup,reason", [
    (lambda s: setattr(s, "lose_next_response", True), "close response lost"),
    (lambda s: setattr(s, "close_mode", "PENDING"), "close status PLACED"),
    (lambda s: setattr(s, "close_mode", "PARTIAL"), "close status CANCELED_PARTIALLY_FILLED"),
])
def test_unconfirmed_close_is_never_complete(rig, setup, reason):
    rig.open()
    setup(rig.sim)
    result = rig.close()
    assert result["result"] == UNRESOLVED and result["reason"] == reason
    assert result["kill_switch"] == "HALTED"
    assert result["sidedeck_open_positions"] == 1          # kept OPEN for the operator
    assert result["writes"] == 2 and result["requests_total"] <= 11


def test_final_reconciliation_mismatch_is_unresolved(rig):
    rig.open()
    original = rig.sim.pnl_payload
    calls = {"n": 0}

    def tampered(rows):
        calls["n"] += 1
        payload = original(rows)
        if calls["n"] >= 2:                     # the final snapshot shows a manual extra position
            payload["clientPortfolio"]["positions"].append(
                {**SYNTHETIC_BASELINE_ROWS[0], "positionID": 999, "orderID": 9999})
        return payload
    rig.sim.pnl_payload = tampered
    result = rig.close()
    assert result["result"] == UNRESOLVED


def test_shape_drift_on_lookup_is_a_kill_criterion(rig):
    real_send = rig.sim.send

    def drifting(method, path, **kw):
        result = real_send(method, path, **kw)
        if path.endswith("orders:lookup"):
            result = dict(result)
            result["orderID"] = result.pop("orderId")
        return result
    rig.sim.send = drifting
    result = rig.open()
    assert result["result"] == UNRESOLVED and result["reason"] == "PilotShapeError"


def test_budget_is_persistent_and_capped(tmp_path):
    budget = PilotBudget(str(tmp_path / "b.sqlite3"))
    budget.reserve("open")
    with pytest.raises(PilotBudgetExhausted):
        budget.reserve("open")
    budget.close()
    again = PilotBudget(str(tmp_path / "b.sqlite3"))
    with pytest.raises(PilotBudgetExhausted):
        again.reserve("open")
    for _ in range(3):
        again.reserve("pnl")
    with pytest.raises(PilotBudgetExhausted):
        again.reserve("pnl")
    assert sum(again.usage().values()) == 4
    again.close()


def test_wrapper_never_upgrades_a_live_transport(tmp_path):
    class Live:
        offline_simulation = False

        def send(self, *a, **k):  # pragma: no cover
            raise AssertionError("must not be called")

    budget = PilotBudget(str(tmp_path / "b.sqlite3"))
    transport = PilotTransport(Live(), budget)
    assert transport.offline_simulation is False
    stores = (DurablePaperIntentStore(str(tmp_path / "o.sqlite3")),
              ApprovalKillSwitch(str(tmp_path / "c.sqlite3"), verify),
              EtoroDemoLineage(str(tmp_path / "l.sqlite3"), baseline_position_ids=[],
                               baseline_order_ids=[]),
              DemoRateBudget(str(tmp_path / "r.sqlite3")))
    with pytest.raises(BrokerExecutionDisabled):
        EtoroDemoDesk(outbox=stores[0], controls=stores[1], lineage=stores[2],
                      transport=transport, policy=DemoDeskPolicy(Decimal("50"), frozenset({1}), 1),
                      baseline=(), budget=stores[3])
    with pytest.raises(PermissionError, match="allowlist"):   # refused before the budget
        transport.send("GET", "/api/v1/trading/info/demo/portfolio", reference_id="r")
    assert sum(budget.usage().values()) == 0
    for store in (*stores, budget):
        store.close()


def test_portfolio_reads_are_budgeted(rig):
    for _ in range(3):
        rig.transport.send("GET", DEMO_PNL_PATH, reference_id=str(uuid.uuid4()))
    with pytest.raises(PilotBudgetExhausted):
        rig.transport.send("GET", DEMO_PNL_PATH, reference_id=str(uuid.uuid4()))
