"""SD-036 eToro Demo order contract and offline desk. Synthetic data only; no network."""
import ast
import inspect
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sidedeck.application import sd036_etoro_demo_desk as desk_module
from sidedeck.application.sd032_durable_paper_intent import DurablePaperIntentStore, IntentError
from sidedeck.application.sd033_approval_killswitch import ApprovalKillSwitch, intent_digest
from sidedeck.application.sd036_etoro_demo_desk import (
    SYNTHETIC_BASELINE_ROWS, BrokerExecutionDisabled, DemoDeskPolicy, EtoroDemoDesk,
    EtoroDemoLineage, OfflineEtoroDemoSimulator, close_scope, open_scope, rehearse,
)
from sidedeck.domain import etoro_demo_orders as orders_module
from sidedeck.domain.etoro_demo import EtoroDemoDataError, parse_demo_portfolio
from sidedeck.domain.etoro_demo_books import BaselinePosition, EtoroDemoBookError
from sidedeck.domain.etoro_demo_orders import (
    CloseAcceptance, DemoCloseRequest, DemoOpenRequest, EtoroDemoOrderError,
    RealExecutionExcluded, parse_close_acceptance, parse_close_info, parse_open_acceptance,
    parse_order_lookup, require_demo_route,
)

BOOK = "etoro-demo:tradingagents"


def ref() -> str:
    return str(uuid.uuid4())


def verify(key, digest, signature):
    return signature == f"{key}:{digest}"


class Harness:
    def __init__(self, tmp_path, *, cap="500", max_open=2):
        self.tmp = tmp_path
        self.now = datetime.now(timezone.utc)
        self.sim = OfflineEtoroDemoSimulator(fill_price=Decimal("100"))
        self.baseline = tuple(BaselinePosition.of(p) for p in parse_demo_portfolio(
            self.sim.pnl_payload(SYNTHETIC_BASELINE_ROWS), observed_at=self.now).positions)
        self.cap, self.max_open = cap, max_open
        self.open_stores()

    def open_stores(self):
        self.controls = ApprovalKillSwitch(str(self.tmp / "controls.sqlite3"), verify)
        self.lineage = EtoroDemoLineage(
            str(self.tmp / "lineage.sqlite3"),
            baseline_position_ids=[b.position_id for b in self.baseline],
            baseline_order_ids=[b.order_id for b in self.baseline if b.order_id])
        self.outbox = DurablePaperIntentStore(str(self.tmp / "outbox.sqlite3"))
        self.desk = EtoroDemoDesk(outbox=self.outbox, controls=self.controls,
                                  lineage=self.lineage, transport=self.sim,
                                  policy=DemoDeskPolicy(Decimal(self.cap), frozenset({1001}),
                                                        self.max_open),
                                  baseline=self.baseline)

    def close_stores(self):
        self.outbox.close()
        self.controls.close()
        self.lineage.close()

    def approve(self, intent_id, scope):
        digest = intent_digest(intent_id, scope)
        self.controls.approve(f"a-{intent_id}", intent_id, scope, "requester", "owner", "pk",
                              f"pk:{digest}", self.now + timedelta(minutes=5))

    def open(self, intent_id="open-1", units="2", limit="101", approve=True):
        request = DemoOpenRequest(ref(), 1001, Decimal(units), Decimal(limit))
        if approve:
            self.approve(intent_id, open_scope(BOOK, request))
        return request, self.desk.submit_open(intent_id=intent_id, strategy="tradingagents",
                                              request=request)

    def snapshot(self, rows=None):
        payload = self.sim.pnl_payload(SYNTHETIC_BASELINE_ROWS + (rows or []))
        return parse_demo_portfolio(payload, observed_at=self.now)

    def posts(self):
        return [c for c in self.sim.calls if c[0] == "POST"]


@pytest.fixture
def h(tmp_path):
    harness = Harness(tmp_path)
    yield harness
    harness.close_stores()


# ---- contract --------------------------------------------------------------

@pytest.mark.parametrize("method,path", [
    ("POST", "/api/v2/trading/execution/orders"),
    ("GET", "/api/v1/trading/info/real/pnl"),
    ("POST", "/api/v1/trading/execution/market-close-orders/positions/5"),
    ("POST", "/api/v2/agent-portfolios"),
    ("GET", "/api/v1/agent-portfolios"),
])
def test_real_and_agent_portfolio_routes_permanently_refused(method, path):
    with pytest.raises(RealExecutionExcluded, match="permanently excluded"):
        require_demo_route(method, path)


@pytest.mark.parametrize("method,path", [
    ("DELETE", "/api/v2/trading/execution/demo/orders"),
    ("GET", "/api/v2/trading/execution/demo/orders"),
    ("POST", "/api/v1/trading/execution/demo/market-close-orders/positions/0"),
    ("POST", "/api/v1/trading/execution/demo/market-open-orders/by-amount"),
    ("PUT", "/api/v1/trading/execution/demo/positions/5/stop-loss"),
])
def test_unlisted_demo_routes_refused(method, path):
    with pytest.raises(RealExecutionExcluded, match="allowlist"):
        require_demo_route(method, path)


def test_documented_demo_routes_allowed():
    require_demo_route("POST", "/api/v2/trading/execution/demo/orders")
    require_demo_route("GET", "/api/v2/trading/info/demo/orders:lookup")
    require_demo_route("POST", "/api/v1/trading/execution/demo/market-close-orders/positions/12")
    require_demo_route("GET", "/api/v1/trading/info/demo/close-orders/77")
    require_demo_route("GET", "/api/v1/trading/info/demo/pnl")


def test_open_body_is_long_unleveraged_price_protected_usd():
    body = DemoOpenRequest(ref(), 1001, Decimal("2.5"), Decimal("101.25")).body()
    assert body == {"action": "open", "transaction": "buy", "instrumentId": 1001,
                    "orderType": "limitIOC", "limitRate": 101.25, "units": 2.5, "leverage": 1,
                    "orderCurrency": "usd"}


@pytest.mark.parametrize("kwargs", [
    {"reference_id": "not-a-uuid"}, {"instrument_id": 0}, {"units": Decimal("0")},
    {"limit_rate": Decimal("-1")}, {"units": Decimal("NaN")},
])
def test_open_request_validation(kwargs):
    values = {"reference_id": ref(), "instrument_id": 1001, "units": Decimal("1"),
              "limit_rate": Decimal("10")} | kwargs
    with pytest.raises(EtoroDemoOrderError):
        DemoOpenRequest(**values)


def test_inexact_decimal_is_not_silently_rounded():
    request = DemoOpenRequest(ref(), 1001, Decimal("0.1000000000000000000001"), Decimal("1"))
    with pytest.raises(EtoroDemoOrderError, match="exactly"):
        request.body()


def test_open_acceptance_requires_reference_echo():
    reference = ref()
    assert parse_open_acceptance({"orderId": 5, "referenceId": reference},
                                 reference_id=reference).order_id == 5
    with pytest.raises(EtoroDemoOrderError, match="echo"):
        parse_open_acceptance({"orderId": 5, "referenceId": ref()}, reference_id=reference)


def lookup(order_id=500, **changes):
    payload = {"orderId": order_id, "action": "open", "transaction": "buy",
               "status": {"id": 3, "errorCode": 0},
               "asset": {"instrumentId": 1001, "leverage": 1, "side": "long"},
               "positionExecutions": [{"positionId": 900, "state": "open", "remainingUnits": 2,
                                       "openingData": {"orderId": order_id, "units": 2,
                                                       "avgPrice": 100, "fees": 0}}]}
    payload.update(changes)
    return payload


REQUEST = DemoOpenRequest("6f1c1b2e-3c4d-4e5f-8a9b-0c1d2e3f4a5b", 1001, Decimal("2"),
                          Decimal("101"))


def test_lookup_lineage_is_verified():
    outcome = parse_order_lookup(lookup(), request=REQUEST, order_id=500)
    assert outcome.status == "FILLED" and outcome.executions[0].position_id == 900


def _exec(**opening):
    data = {"orderId": 500, "units": 2, "avgPrice": 100, "fees": 0} | opening
    return [{"positionId": 900, "state": "open", "remainingUnits": 2, "openingData": data}]


@pytest.mark.parametrize("payload,match", [
    (lookup(positionExecutions=_exec(orderId=499)), "different order"),
    (lookup(asset={"instrumentId": 1002, "leverage": 1, "side": "long"}), "instrument"),
    (lookup(asset={"instrumentId": 1001, "leverage": 2, "side": "long"}), "leverage"),
    (lookup(asset={"instrumentId": 1001, "leverage": 1, "side": "short"}), "direction"),
    (lookup(positionExecutions=_exec(avgPrice=102)), "limit rate"),
    (lookup(positionExecutions=_exec(units=3)), "inconsistent|exceed"),
    (lookup(status={"id": 4, "errorCode": 7}), "rejected"),
    (lookup(positionExecutions=_exec(units=1)), "inconsistent|FILLED"),
    (lookup(status={"id": 99, "errorCode": 0}), "documented"),
    (lookup(transaction="sellShort"), "long open"),
    (lookup(positionExecutions=_exec(units=True)), "numeric"),
    (lookup(positionExecutions=_exec() + _exec()), "duplicate"),
    (lookup(order_id=501), "different order"),
])
def test_lookup_adversarial(payload, match):
    with pytest.raises(EtoroDemoOrderError, match=match):
        parse_order_lookup(payload, request=REQUEST, order_id=500)


def test_close_parsers_refuse_foreign_positions():
    request = DemoCloseRequest(ref(), 900, 1001)
    assert request.body() == {"InstrumentID": 1001, "UnitsToDeduct": None}
    with pytest.raises(EtoroDemoOrderError, match="different position"):
        parse_close_acceptance({"orderForClose": {"positionID": 901, "instrumentID": 1001,
                                                  "orderID": 8}}, request=request)
    accepted = CloseAcceptance(8, 900)
    with pytest.raises(EtoroDemoOrderError, match="did not name"):
        parse_close_info({"orderID": 8, "statusID": 3,
                          "positions": [{"positionID": 11, "units": 1}]}, acceptance=accepted)
    with pytest.raises(EtoroDemoOrderError, match="different order"):
        parse_close_info({"orderID": 9, "statusID": 3, "positions": []}, acceptance=accepted)


# ---- desk gates ------------------------------------------------------------

class _LiveLooking:
    offline_simulation = False

    def send(self, *args, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("network transport must never be called")


@pytest.mark.parametrize("transport", [_LiveLooking(), object()])
def test_only_offline_simulator_may_be_attached(h, transport):
    with pytest.raises(BrokerExecutionDisabled, match="NO_GO"):
        EtoroDemoDesk(outbox=h.outbox, controls=h.controls, lineage=h.lineage,
                      transport=transport, policy=DemoDeskPolicy(Decimal(1), frozenset({1}), 1),
                      baseline=h.baseline)


def test_unapproved_or_mis_scoped_orders_refused(h):
    with pytest.raises(EtoroDemoOrderError, match="approval"):
        h.open(approve=False)
    request = DemoOpenRequest(ref(), 1001, Decimal("2"), Decimal("101"))
    h.approve("open-x", open_scope(BOOK, DemoOpenRequest(ref(), 1001, Decimal("3"),
                                                         Decimal("101"))))
    with pytest.raises(EtoroDemoOrderError, match="approval"):
        h.desk.submit_open(intent_id="open-x", strategy="tradingagents", request=request)
    assert h.sim.calls == []


@pytest.mark.parametrize("units,limit,instrument,strategy,match", [
    ("10", "101", 1001, "tradingagents", "cap"),
    ("1", "10", 1002, "tradingagents", "allowlist"),
    ("1", "10", 1001, "unknown", "strategy"),
])
def test_policy_limits(h, units, limit, instrument, strategy, match):
    request = DemoOpenRequest(ref(), instrument, Decimal(units), Decimal(limit))
    with pytest.raises((EtoroDemoOrderError, EtoroDemoBookError), match=match):
        h.desk.submit_open(intent_id="p", strategy=strategy, request=request)
    assert h.sim.calls == []


def test_max_open_positions_per_book(tmp_path):
    h = Harness(tmp_path, max_open=1)
    request, _ = h.open("o1")
    h.desk.refresh_open(request.reference_id)
    with pytest.raises(EtoroDemoOrderError, match="maximum"):
        h.open("o2")
    h.close_stores()


def test_happy_path_lineage_and_outbox(h):
    request, state = h.open()
    assert state == "ACCEPTED"
    outcome = h.desk.refresh_open(request.reference_id)
    assert outcome.status == "FILLED"
    assert h.outbox.get("open-1")["state"] == "FILLED_SIMULATED"
    owned = h.lineage.owned_positions()
    assert len(owned) == 1 and owned[0]["book_id"] == BOOK
    report = h.desk.reconcile(h.snapshot(), h.now)
    assert report["status"] == "MATCHED"
    assert report["books"] == {BOOK: 1, "etoro-demo:ai-trading": 0, "etoro-demo:unattributed": 4}
    assert report["broker_execution"] == "DISABLED"


def test_lost_response_halts_and_recovers_without_resubmission(h):
    h.sim.lose_next_response = True
    request, state = h.open()
    assert state == "OUTCOME_UNKNOWN" and h.controls.is_halted()
    with pytest.raises(EtoroDemoOrderError, match="kill-switch"):
        h.open("open-2", approve=False)
    assert h.desk.recover() == {request.reference_id: "FILLED"}
    assert len(h.posts()) == 1
    assert h.outbox.get("open-1")["state"] == "FILLED_SIMULATED"


def test_never_received_order_is_closed_out_not_resubmitted(h):
    h.sim.drop_next_request = True
    request, state = h.open()
    assert state == "OUTCOME_UNKNOWN"
    assert h.desk.recover() == {request.reference_id: "NOT_RECEIVED"}
    assert h.outbox.get("open-1")["state"] == "REJECTED_SIMULATED"
    assert h.posts() == [("POST", "/api/v2/trading/execution/demo/orders")]


def test_recovery_survives_restart(h):
    h.sim.lose_next_response = True
    request, _ = h.open()
    h.close_stores()
    h.open_stores()
    assert h.controls.is_halted()
    assert h.desk.recover() == {request.reference_id: "FILLED"}


def test_rejected_and_partial_outcomes(h):
    h.sim.mode = "REJECT"
    rejected, _ = h.open("r1")
    assert h.desk.refresh_open(rejected.reference_id).status == "REJECTED"
    assert h.outbox.get("r1")["state"] == "REJECTED_SIMULATED"
    h.sim.mode = "PARTIAL"
    partial, _ = h.open("p1")
    assert h.desk.refresh_open(partial.reference_id).status == "CANCELED_PARTIALLY_FILLED"
    assert h.outbox.get("p1")["state"] == "PARTIALLY_FILLED_SIMULATED"
    assert [Decimal(r["remaining_units"]) for r in h.lineage.owned_positions()] == [Decimal("1")]


def test_broker_reporting_a_baseline_position_halts(h):
    h.sim.force_position_id = 11
    request, _ = h.open()
    with pytest.raises(EtoroDemoBookError, match="baseline"):
        h.desk.refresh_open(request.reference_id)
    assert h.controls.is_halted() and h.lineage.owned_positions() == []


def test_reference_id_is_never_reused(h):
    request, _ = h.open()
    h.approve("open-2", open_scope(BOOK, request))
    with pytest.raises((EtoroDemoOrderError, IntentError)):
        h.desk.submit_open(intent_id="open-2", strategy="tradingagents", request=request)
    assert len(h.posts()) == 1


# ---- close protection ------------------------------------------------------

def _filled(h):
    request, _ = h.open()
    h.desk.refresh_open(request.reference_id)
    return h.lineage.owned_positions()[0]["position_id"]


def test_baseline_positions_can_never_be_closed(h):
    _filled(h)
    for baseline in h.baseline:
        close = DemoCloseRequest(ref(), baseline.position_id, 1001)
        h.approve(f"c-{baseline.position_id}", close_scope(BOOK, close))
        with pytest.raises(EtoroDemoBookError, match="baseline"):
            h.desk.submit_close(intent_id=f"c-{baseline.position_id}", request=close,
                                snapshot=h.snapshot(), now=h.now)
    assert len(h.posts()) == 1


def test_same_instrument_position_without_lineage_is_not_owned(h):
    _filled(h)
    manual = {"positionID": 555, "instrumentID": 1001, "orderID": 4444, "isBuy": True,
              "units": 2, "amount": 1, "leverage": 1, "openDateTime": "2026-10-21T14:30:00Z",
              "unrealizedPnL": {"pnL": 0}}
    close = DemoCloseRequest(ref(), 555, 1001)
    with pytest.raises(EtoroDemoBookError, match="lineage"):
        h.desk.submit_close(intent_id="c", request=close, snapshot=h.snapshot([manual]), now=h.now)
    report = h.desk.reconcile(h.snapshot([manual]), h.now)
    assert report["status"] == "DISCREPANCY" and report["books"]["etoro-demo:unattributed"] == 5


def test_close_requires_matching_live_lineage_and_fresh_snapshot(h):
    position_id = _filled(h)
    close = DemoCloseRequest(ref(), position_id, 1001)
    h.approve("c1", close_scope(BOOK, close))
    stale = parse_demo_portfolio(h.sim.pnl_payload(SYNTHETIC_BASELINE_ROWS),
                                 observed_at=h.now - timedelta(minutes=10))
    with pytest.raises(EtoroDemoDataError, match="stale"):
        h.desk.submit_close(intent_id="c1", request=close, snapshot=stale, now=h.now)
    tampered = h.sim.pnl_payload(SYNTHETIC_BASELINE_ROWS)
    for row in tampered["clientPortfolio"]["positions"]:
        if row["positionID"] == position_id:
            row["orderID"] = 1234
    with pytest.raises(EtoroDemoBookError, match="does not match"):
        h.desk.submit_close(intent_id="c1", request=close,
                            snapshot=parse_demo_portfolio(tampered, observed_at=h.now), now=h.now)
    assert h.controls.is_halted()


def test_close_over_units_and_unapproved_refused(h):
    position_id = _filled(h)
    with pytest.raises(EtoroDemoOrderError, match="exceeds"):
        h.desk.submit_close(intent_id="c", snapshot=h.snapshot(), now=h.now,
                            request=DemoCloseRequest(ref(), position_id, 1001, Decimal("3")))
    with pytest.raises(EtoroDemoOrderError, match="approval"):
        h.desk.submit_close(intent_id="c", snapshot=h.snapshot(), now=h.now,
                            request=DemoCloseRequest(ref(), position_id, 1001))


def test_partial_then_full_close_reconciles(h):
    position_id = _filled(h)
    part = DemoCloseRequest(ref(), position_id, 1001, Decimal("0.5"))
    h.approve("c1", close_scope(BOOK, part))
    h.desk.submit_close(intent_id="c1", request=part, snapshot=h.snapshot(), now=h.now)
    assert h.desk.refresh_close(part.reference_id) == "FILLED"
    assert h.desk.reconcile(h.snapshot(), h.now)["status"] == "MATCHED"
    rest = DemoCloseRequest(ref(), position_id, 1001)
    h.approve("c2", close_scope(BOOK, rest))
    h.desk.submit_close(intent_id="c2", request=rest, snapshot=h.snapshot(), now=h.now)
    h.desk.refresh_close(rest.reference_id)
    assert h.lineage.owned(position_id)["state"] == "CLOSED"
    assert h.desk.reconcile(h.snapshot(), h.now)["status"] == "MATCHED"


def test_lost_close_response_requires_operator_reconciliation(h):
    position_id = _filled(h)
    close = DemoCloseRequest(ref(), position_id, 1001)
    h.approve("c1", close_scope(BOOK, close))
    h.sim.lose_next_response = True
    assert h.desk.submit_close(intent_id="c1", request=close, snapshot=h.snapshot(),
                               now=h.now) == "OUTCOME_UNKNOWN"
    assert h.controls.is_halted()
    with pytest.raises(EtoroDemoOrderError, match="reconcile"):
        h.desk.refresh_close(close.reference_id)


def test_reconcile_flags_missing_sidedeck_position_and_halts(h):
    _filled(h)
    payload = h.sim.pnl_payload(SYNTHETIC_BASELINE_ROWS)
    payload["clientPortfolio"]["positions"] = list(SYNTHETIC_BASELINE_ROWS)
    report = h.desk.reconcile(parse_demo_portfolio(payload, observed_at=h.now), h.now)
    assert report["status"] == "DISCREPANCY" and report["kill_switch"] == "HALTED"


def test_mirror_child_position_is_a_discrepancy_not_a_direct_holding(h):
    mirrored = {"positionID": 556, "instrumentID": 1001, "orderID": 4445, "mirrorID": 31,
                "isBuy": True, "units": 1, "amount": 1, "leverage": 1,
                "openDateTime": "2026-10-21T14:30:00Z", "unrealizedPnL": {"pnL": 0}}
    snapshot = h.snapshot([mirrored])
    assert next(p for p in snapshot.positions if p.position_id == 556).mirror_id == 31
    report = h.desk.reconcile(snapshot, h.now)
    assert any("copy/mirror" in d for d in report["discrepancies"])
    assert all(p.mirror_id == 0 for p in h.snapshot().positions)


# ---- shared-control additions ----------------------------------------------

def test_is_approved_is_scope_exact_and_halt_aware(h):
    h.approve("i", "scope-a")
    assert h.controls.is_approved("i", "scope-a")
    assert not h.controls.is_approved("i", "scope-b")
    h.controls.trip("op", "test")
    assert not h.controls.is_approved("i", "scope-a")


def test_record_rejection_requires_reason_and_valid_state(h):
    with pytest.raises(IntentError, match="unknown"):
        h.outbox.record_rejection("missing", "reason")
    request, _ = h.open()
    h.desk.refresh_open(request.reference_id)
    with pytest.raises(IntentError, match="invalid transition"):
        h.outbox.record_rejection("open-1", "late")


# ---- structural safety -----------------------------------------------------

@pytest.mark.parametrize("module", [desk_module, orders_module])
def test_no_network_client_in_order_modules(module):
    tree = ast.parse(inspect.getsource(module))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree)
                if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.module}
    assert not imported & {"urllib", "http", "requests", "httpx", "socket", "aiohttp"}
    source = inspect.getsource(module)
    assert "/api/v2/trading/execution/orders" not in source
    assert "os.environ" not in source and "ETORO_API_KEY" not in source


def test_rehearsal_is_offline_and_labelled(tmp_path):
    result = rehearse(str(tmp_path))
    assert result["evidence"] == "OFFLINE_SIMULATED_NOT_BROKER_EVIDENCE"
    assert result["open_submit"] == "OUTCOME_UNKNOWN" and result["recovery"] == ["FILLED"]
    assert result["baseline_close_refused"] is True and result["close"] == "FILLED"
    assert result["reconciliation"]["status"] == "MATCHED"
    assert result["reconciliation"]["etoro_demo_execution_release"] == "NO_GO"
    assert result["reconciliation"]["etoro_real_execution"] == "PERMANENTLY_EXCLUDED"
    assert result["authenticated_requests"] == 0 and result["orders_sent_to_etoro"] == 0
