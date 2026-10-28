"""SD-138 actual composition tests; the only broker route is an in-process fake."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from uuid import UUID

import pytest

from sidedeck.application.sd036_etoro_demo_desk import (
    EtoroDemoLineage, OfflineEtoroDemoSimulator, SYNTHETIC_BASELINE_ROWS,
)
from sidedeck.application.sd107_demo_gateway import GatewayRefused
from sidedeck.application.sd063_autonomous_demo_policy import EntryProposal
from sidedeck.application.sd129_etoro_demo_order_port import (
    EtoroDemoOrderPort,
)
from sidedeck.application.sd138_autonomous_order_adapter import (
    AutonomousEtoroDemoOrderAdapter, SD138Refused,
)
from sidedeck.domain.etoro_demo_orders import DEMO_OPEN_PATH, DEMO_ORDER_LOOKUP_PATH

from test_sd063_autonomous_demo_policy import (
    _Env, _offline_gateway, _policy,
)


@pytest.fixture
def env(tmp_path):
    current = _Env(tmp_path)
    yield current
    current.ledger.close()


def _composed(env: _Env, tmp_path: Path, *, loses_post: bool = False):
    gateway, quote, signer = _offline_gateway(env, close_price="498")
    route = OfflineEtoroDemoSimulator(fill_price=Decimal("500"),
                                      first_position_id=880_001, first_order_id=770_001)
    route.baseline_rows = list(SYNTHETIC_BASELINE_ROWS)
    route.lose_next_response = loses_post
    lineage_path = tmp_path / "sd138-lineage.sqlite3"
    lineage = EtoroDemoLineage(
        str(lineage_path), baseline_position_ids=(11, 12, 13, 14),
        baseline_order_ids=(9011, 9012, 9013, 9014),
    )
    port = EtoroDemoOrderPort(route, lineage=lineage)
    adapter = AutonomousEtoroDemoOrderAdapter(policy_gateway=gateway, order_port=port)
    return gateway, quote, signer, route, lineage, lineage_path, adapter


def test_sd138_composes_signed_policy_grant_quote_anchor_and_durable_port(env, tmp_path):
    gateway, quote, _signer, route, lineage, _path, adapter = _composed(env, tmp_path)
    proposal = env.entry()
    result = adapter.submit_entry(proposal, quote=quote)

    assert result.classification == "BROKER_CONFIRMED_OPEN"
    assert result.position is not None
    assert result.position.order_id == result.acceptance_order_id
    assert lineage.owned(result.position.position_id)["book_id"] == "etoro-demo:tradingagents"
    assert env.ledger.state().entries[proposal.reference_id].outcome == "FILLED"
    assert route.calls == [
        ("POST", DEMO_OPEN_PATH),
        ("GET", DEMO_ORDER_LOOKUP_PATH),
    ]
    events = [record.event_type for record in gateway._audit_journal.records()]
    assert "ORDER_RESERVATION" in events and "SEND" in events and "RECONCILIATION" in events
    assert {"POLICY", "GRANT", "GRANT_USE"}.issubset(set(events))
    assert env.authority._ledger.events()

    plan = env.rt.plan_exits(bids=env.bids("400"))
    assert len(plan.exits) == 1
    close_quote = _signer.seal({
        "canonical_id": proposal.canonical_id, "bid": "400", "ask": "401",
        "quote_time": env.clock.now.isoformat(),
    })
    close_read = adapter.submit_exit(plan.exits[0], quote=close_quote)
    assert close_read.outcome.status == "FILLED"
    assert close_read.realised_pnl_status == "UNAVAILABLE_WITHOUT_BROKER_CLOSE_PRICE"
    assert close_read.position_status == "BROKER_REPORTS_FULL_CLOSE_PENDING_PORTFOLIO_RECONCILIATION"
    assert env.ledger.kill_switch_engaged()
    assert lineage.order(str(UUID(hex=plan.exits[0].reference_id)))["state"] == "ACCEPTED"
    assert route.calls[-2][0] == "POST" and route.calls[-1][0] == "GET"


def test_sd138_revoked_grant_stale_quote_and_audit_outage_send_nothing(env, tmp_path):
    gateway, quote, _signer, route, _lineage, _path, adapter = _composed(env, tmp_path)
    proposal = env.entry()
    env.authority.revoke(env.grant_document["grant_id"], "offline integration test")
    with pytest.raises((GatewayRefused, SD138Refused)):
        adapter.submit_entry(proposal, quote=quote)
    assert not route.calls

    # A fresh policy fixture plus authenticated but stale input fails the send-time gate.
    stale_root = tmp_path / "stale"
    stale_root.mkdir()
    env2 = _Env(stale_root, _policy())
    gateway2, _q, signer2, route2, _lin2, _path2, adapter2 = _composed(env2, tmp_path / "stale")
    proposal2 = env2.entry()
    assert isinstance(proposal2, EntryProposal)
    stale = signer2.seal({
        "canonical_id": proposal.canonical_id, "bid": "499", "ask": "500",
        "quote_time": (env2.clock.now - timedelta(
            seconds=env2.policy.max_quote_age_seconds + 2)).isoformat(),
    })
    with pytest.raises(GatewayRefused):
        adapter2.submit_entry(proposal2, quote=stale)
    assert not route2.calls
    assert not env2.ledger.kill_switch_engaged()

    gateway2._audit_journal._anchor.unavailable = True
    fresh = signer2.seal({
        "canonical_id": proposal.canonical_id, "bid": "499.9", "ask": "500",
        "quote_time": env2.clock.now.isoformat(),
    })
    with pytest.raises((GatewayRefused, SD138Refused)):
        adapter2.submit_entry(proposal2, quote=fresh)
    assert not route2.calls
    assert env2.ledger.kill_switch_engaged()


def test_sd138_lost_post_ack_recovers_by_get_after_port_restart(env, tmp_path):
    gateway, quote, _signer, route, lineage, path, adapter = _composed(
        env, tmp_path, loses_post=True)
    proposal = env.entry()
    with pytest.raises(SD138Refused, match="stopped for reconciliation"):
        adapter.submit_entry(proposal, quote=quote)
    assert [method for method, _ in route.calls].count("POST") == 1
    assert env.ledger.kill_switch_engaged()
    assert lineage.order(str(UUID(hex=proposal.reference_id)))["state"] == "OUTCOME_UNKNOWN"
    lineage.close()

    # New port/adapter process; the fake broker retains its accepted order and SD-036 DB persists.
    restarted_lineage = EtoroDemoLineage(
        str(path), baseline_position_ids=(11, 12, 13, 14),
        baseline_order_ids=(9011, 9012, 9013, 9014),
    )
    restarted_port = EtoroDemoOrderPort(route, lineage=restarted_lineage)
    restarted = AutonomousEtoroDemoOrderAdapter(policy_gateway=gateway,
                                                 order_port=restarted_port)
    result = restarted.recover_entry(proposal)
    assert result.classification == "BROKER_CONFIRMED_OPEN"
    assert [method for method, _ in route.calls].count("POST") == 1
    assert env.ledger.state().entries[proposal.reference_id].outcome == "FILLED"
    assert restarted_lineage.owned(result.position.position_id) is not None


def test_sd138_two_workers_cannot_reserve_the_same_port_reference(env, tmp_path):
    gateway, quote, _signer, route, lineage, path, adapter = _composed(env, tmp_path)
    proposal = env.entry()
    barrier = Barrier(2)

    def worker() -> str:
        local_lineage = EtoroDemoLineage(
            str(path), baseline_position_ids=(11, 12, 13, 14),
            baseline_order_ids=(9011, 9012, 9013, 9014),
        )
        port = EtoroDemoOrderPort(route, lineage=local_lineage)
        barrier.wait()
        try:
            port.submit_open(
                adapter._open_request(proposal), intent_id=proposal.reference_id,
                book_id="etoro-demo:tradingagents")
            return "reserved"
        except Exception:
            return "refused"
        finally:
            local_lineage.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _n: worker(), range(2)))
    assert sorted(results) == ["refused", "reserved"]
    assert [method for method, _ in route.calls].count("POST") == 1
    assert route.calls[0][1] == DEMO_OPEN_PATH
    lineage.close()


def test_sd138_adapter_rejects_missing_lineage_and_nonfake_route(env, tmp_path):
    gateway, _quote, _signer, route, _lineage, _path, _adapter = _composed(env, tmp_path)
    with pytest.raises(SD138Refused, match="durable SD-036"):
        AutonomousEtoroDemoOrderAdapter(
            policy_gateway=gateway, order_port=EtoroDemoOrderPort(route))
    with pytest.raises(SD138Refused, match="offline fake"):
        AutonomousEtoroDemoOrderAdapter(
            policy_gateway=gateway,
            order_port=EtoroDemoOrderPort(object(), lineage=EtoroDemoLineage(
                str(tmp_path / "wrong-route.sqlite3"), baseline_position_ids=(11, 12, 13, 14),
                baseline_order_ids=(9011, 9012, 9013, 9014))))


def test_sd138_changed_or_protected_instrument_never_reaches_fake_route(env, tmp_path):
    _gateway, quote, _signer, route, _lineage, _path, adapter = _composed(env, tmp_path)
    proposal = env.entry()
    changed = replace(proposal, etoro_instrument_id=1001)
    with pytest.raises((GatewayRefused, SD138Refused)):
        adapter.submit_entry(changed, quote=quote)
    assert route.calls == []
