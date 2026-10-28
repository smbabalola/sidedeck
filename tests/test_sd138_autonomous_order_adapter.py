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
    TransportNotFound,
)
from sidedeck.application.sd107_demo_gateway import GatewayRefused
from sidedeck.application.sd063_autonomous_demo_policy import EntryProposal
from sidedeck.application.sd129_etoro_demo_order_port import (
    EtoroDemoOrderPort,
)
from sidedeck.application.sd138_autonomous_order_adapter import (
    AutonomousEtoroDemoOrderAdapter, SD138Refused,
)
from sidedeck.domain.etoro_demo_orders import (
    DEMO_CLOSE_INFO_PATH, DEMO_CLOSE_PATH, DEMO_OPEN_PATH, DEMO_ORDER_LOOKUP_PATH,
    DEMO_PNL_PATH,
    DemoCloseRequest,
    EtoroDemoOrderError,
)

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
    route.baseline_rows = [dict(row) for row in SYNTHETIC_BASELINE_ROWS]
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

    assert result.classification == "SIMULATED_POSITION_OPEN"
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

    plan = env.rt.plan_exits(bids=env.bids("455"))
    assert len(plan.exits) == 1
    close_quote = _signer.seal({
        "canonical_id": proposal.canonical_id, "bid": "455", "ask": "456",
        "quote_time": env.clock.now.isoformat(),
    })
    close_result = adapter.submit_exit(plan.exits[0], quote=close_quote)
    assert close_result.outcome.status == "FILLED"
    assert close_result.realised_pnl_status == "SIMULATED_ONLY_NOT_BROKER_PNL"
    assert close_result.position_status == "FLAT_CONFIRMED_BY_SIMULATED_CLOSE_AND_FINAL_PNL"
    assert close_result.baseline_position_ids == (11, 12, 13, 14)
    assert env.ledger.open_positions() == ()
    close_ref = str(UUID(hex=plan.exits[0].reference_id))
    assert lineage.order(close_ref)["state"] == "FILLED"
    assert lineage.owned(close_result.close_read.acceptance.position_id)["state"] == "CLOSED"
    assert not env.ledger.kill_switch_engaged()
    assert route.calls[-3:] == [
        ("POST", DEMO_CLOSE_PATH.format(position_id=close_result.close_read.acceptance.position_id)),
        ("GET", DEMO_CLOSE_INFO_PATH.format(order_id=close_result.close_read.acceptance.order_id)),
        ("GET", DEMO_PNL_PATH),
    ]
    expected_refs = [
        str(UUID(hex=proposal.reference_id)),
        f"lookup:{UUID(hex=proposal.reference_id)}",
        str(UUID(hex=plan.exits[0].reference_id)),
        f"close-lookup:{UUID(hex=plan.exits[0].reference_id)}",
        f"close-pnl:{UUID(hex=plan.exits[0].reference_id)}",
    ]
    assert route.call_references == expected_refs
    grant_uses = [(event, detail) for _grant, event, detail in env.authority._ledger.events()
                  if event in {"USE_READ", "USE_WRITE"}]
    assert grant_uses == list(zip(
        ("USE_WRITE", "USE_READ", "USE_WRITE", "USE_READ", "USE_READ"), expected_refs))
    assert any(record.payload.get("action") == "FINAL_PNL_SIMULATION"
               for record in gateway._audit_journal.records())


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


def test_sd138_expired_grant_refuses_fresh_quote_before_any_fake_request(tmp_path):
    env = _Env(tmp_path)
    gateway, _quote, signer, route, lineage, _path, adapter = _composed(env, tmp_path)
    proposal = env.entry()
    assert isinstance(proposal, EntryProposal)
    env.clock.now = env.policy.expires_at
    fresh = signer.seal({
        "canonical_id": proposal.canonical_id, "bid": "499.9", "ask": "500",
        "quote_time": env.clock.now.isoformat(),
    })
    with pytest.raises(GatewayRefused, match="outside its signed window"):
        adapter.submit_entry(proposal, quote=fresh)
    assert route.calls == []
    assert not env.ledger.kill_switch_engaged()
    lineage.close()
    env.ledger.close()


def test_sd139_partial_close_never_claims_flat_or_sends_final_pnl(env, tmp_path):
    gateway, quote, signer, route, lineage, _path, adapter = _composed(env, tmp_path)
    proposal = env.entry()
    adapter.submit_entry(proposal, quote=quote)
    plan = env.rt.plan_exits(bids=env.bids("455"))
    close_quote = signer.seal({
        "canonical_id": proposal.canonical_id, "bid": "455", "ask": "456",
        "quote_time": env.clock.now.isoformat(),
    })
    route.close_mode = "PARTIAL"
    with pytest.raises(SD138Refused, match="close stopped for reconciliation") as refused:
        adapter.submit_exit(plan.exits[0], quote=close_quote)
    assert isinstance(refused.value.__cause__, SD138Refused)
    assert "full owned position closed" in str(refused.value.__cause__)
    close_reference = str(UUID(hex=plan.exits[0].reference_id))
    assert lineage.order(close_reference)["state"] == "ACCEPTED"
    assert lineage.owned(880_001)["state"] == "OPEN"
    assert env.ledger.kill_switch_engaged()
    assert route.calls[-1][1] == DEMO_CLOSE_INFO_PATH.format(order_id=770_002)
    assert all(path != DEMO_PNL_PATH for _, path in route.calls)
    assert [method for method, _ in route.calls].count("POST") == 2


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
    assert result.classification == "SIMULATED_POSITION_OPEN"
    assert [method for method, _ in route.calls].count("POST") == 1
    assert env.ledger.state().entries[proposal.reference_id].outcome == "FILLED"
    assert restarted_lineage.owned(result.position.position_id) is not None
    recovery_ref = f"recovery:{UUID(hex=proposal.reference_id)}"
    assert route.call_references[-1] == recovery_ref
    assert any(event == "USE_READ" and detail == recovery_ref
               for _grant, event, detail in env.authority._ledger.events())


def test_sd141_accepted_open_404_falls_back_by_orderid_only_after_signed_get(env, tmp_path):
    gateway, quote, _signer, route, lineage, path, adapter = _composed(env, tmp_path)
    proposal = env.entry()
    route.lookup_not_visible = 1
    with pytest.raises(SD138Refused, match="stopped for reconciliation"):
        adapter.submit_entry(proposal, quote=quote)
    open_reference = str(UUID(hex=proposal.reference_id))
    assert lineage.order(open_reference)["state"] == "ACCEPTED"
    assert lineage.order(open_reference)["order_id"] == 770_001
    assert env.ledger.kill_switch_engaged()
    lineage.close()

    # A broker 404 on the *first recovery GET* may fall back to the durable
    # accepted orderId, but never a second POST or fabricated position.
    restarted_lineage = EtoroDemoLineage(
        str(path), baseline_position_ids=(11, 12, 13, 14),
        baseline_order_ids=(9011, 9012, 9013, 9014),
    )
    try:
        restarted = AutonomousEtoroDemoOrderAdapter(
            policy_gateway=gateway,
            order_port=EtoroDemoOrderPort(route, lineage=restarted_lineage))
        route.lookup_not_visible = 1
        before = len(route.calls)
        result = restarted.recover_entry(proposal)
        assert result.classification == "SIMULATED_POSITION_OPEN"
        assert result.position is not None
        assert result.position.order_id == 770_001
        assert route.calls[before:] == [
            ("GET", DEMO_ORDER_LOOKUP_PATH),
            ("GET", DEMO_ORDER_LOOKUP_PATH),
        ]
        fallback = f"recovery-orderid:{open_reference}"
        assert route.call_references[-1] == fallback
        assert any(event == "USE_READ" and detail == fallback
                   for _grant, event, detail in env.authority._ledger.events())
        assert [method for method, _ in route.calls].count("POST") == 1
        assert restarted_lineage.owned(result.position.position_id) is not None
        assert env.ledger.kill_switch_engaged()  # Recovery cannot clear owner HALT.
    finally:
        restarted_lineage.close()


def test_sd141_double_404_on_accepted_open_remains_halted_after_two_gets(env, tmp_path):
    gateway, quote, _signer, route, lineage, path, adapter = _composed(env, tmp_path)
    proposal = env.entry()
    route.lookup_not_visible = 1
    with pytest.raises(SD138Refused, match="stopped for reconciliation"):
        adapter.submit_entry(proposal, quote=quote)
    lineage.close()

    restarted_lineage = EtoroDemoLineage(
        str(path), baseline_position_ids=(11, 12, 13, 14),
        baseline_order_ids=(9011, 9012, 9013, 9014),
    )
    try:
        restarted = AutonomousEtoroDemoOrderAdapter(
            policy_gateway=gateway,
            order_port=EtoroDemoOrderPort(route, lineage=restarted_lineage))
        route.lookup_not_visible = 2
        before = len(route.calls)
        with pytest.raises(SD138Refused, match="failed closed"):
            restarted.recover_entry(proposal)
        assert route.calls[before:] == [
            ("GET", DEMO_ORDER_LOOKUP_PATH),
            ("GET", DEMO_ORDER_LOOKUP_PATH),
        ]
        assert [method for method, _ in route.calls].count("POST") == 1
        assert env.ledger.kill_switch_engaged()
        reference = str(UUID(hex=proposal.reference_id))
        assert restarted_lineage.order(reference)["state"] == "ACCEPTED"
    finally:
        restarted_lineage.close()


def test_sd141_grant_revoked_between_404_and_fallback_blocks_second_get(env, tmp_path):
    gateway, quote, _signer, route, lineage, path, adapter = _composed(env, tmp_path)
    proposal = env.entry()
    route.lookup_not_visible = 1
    with pytest.raises(SD138Refused, match="stopped for reconciliation"):
        adapter.submit_entry(proposal, quote=quote)
    lineage.close()

    restarted_lineage = EtoroDemoLineage(
        str(path), baseline_position_ids=(11, 12, 13, 14),
        baseline_order_ids=(9011, 9012, 9013, 9014),
    )
    try:
        restarted = AutonomousEtoroDemoOrderAdapter(
            policy_gateway=gateway,
            order_port=EtoroDemoOrderPort(route, lineage=restarted_lineage))
        route.lookup_not_visible = 1
        send = route.send
        def revoke_after_first_404(method, request_path, **kwargs):
            try:
                return send(method, request_path, **kwargs)
            except TransportNotFound:
                env.authority.revoke(env.grant_document["grant_id"], "synthetic revocation")
                raise
        route.send = revoke_after_first_404
        before = len(route.calls)
        with pytest.raises(SD138Refused, match="failed closed"):
            restarted.recover_entry(proposal)
        assert route.calls[before:] == [("GET", DEMO_ORDER_LOOKUP_PATH)]
        assert [m for m, _ in route.calls].count("POST") == 1
        assert env.ledger.kill_switch_engaged()
        assert restarted_lineage.order(str(UUID(hex=proposal.reference_id)))["state"] == "ACCEPTED"
    finally:
        restarted_lineage.close()


def test_sd141_unknown_open_404_has_no_orderid_fallback_or_repost(env, tmp_path):
    gateway, quote, _signer, route, lineage, path, adapter = _composed(
        env, tmp_path, loses_post=True)
    proposal = env.entry()
    with pytest.raises(SD138Refused, match="stopped for reconciliation"):
        adapter.submit_entry(proposal, quote=quote)
    open_reference = str(UUID(hex=proposal.reference_id))
    assert lineage.order(open_reference)["state"] == "OUTCOME_UNKNOWN"
    assert lineage.order(open_reference)["order_id"] is None
    lineage.close()

    restarted_lineage = EtoroDemoLineage(
        str(path), baseline_position_ids=(11, 12, 13, 14),
        baseline_order_ids=(9011, 9012, 9013, 9014),
    )
    try:
        restarted = AutonomousEtoroDemoOrderAdapter(
            policy_gateway=gateway,
            order_port=EtoroDemoOrderPort(route, lineage=restarted_lineage))
        route.lookup_not_visible = 1
        before = len(route.calls)
        with pytest.raises(SD138Refused, match="failed closed"):
            restarted.recover_entry(proposal)
        assert route.calls[before:] == [("GET", DEMO_ORDER_LOOKUP_PATH)]
        assert [method for method, _ in route.calls].count("POST") == 1
        assert restarted_lineage.order(open_reference)["state"] == "OUTCOME_UNKNOWN"
        assert env.ledger.kill_switch_engaged()
    finally:
        restarted_lineage.close()


def test_sd138_final_pnl_baseline_drift_keeps_close_unresolved_and_halts(env, tmp_path):
    gateway, quote, signer, route, lineage, _path, adapter = _composed(env, tmp_path)
    proposal = env.entry()
    adapter.submit_entry(proposal, quote=quote)
    plan = env.rt.plan_exits(bids=env.bids("455"))
    close_quote = signer.seal({
        "canonical_id": proposal.canonical_id, "bid": "455", "ask": "456",
        "quote_time": env.clock.now.isoformat(),
    })
    route.baseline_rows.append({
        "positionID": 99, "instrumentID": 1001, "orderID": 9099, "isBuy": True,
        "units": 1, "amount": 100, "leverage": 1,
        "openDateTime": "2026-09-01T14:30:00Z", "unrealizedPnL": {"pnL": 0},
    })
    with pytest.raises(SD138Refused, match="stopped for reconciliation") as refused:
        adapter.submit_exit(plan.exits[0], quote=close_quote)
    assert isinstance(refused.value.__cause__, SD138Refused)
    assert "protected four-position baseline" in str(refused.value.__cause__)
    close_ref = str(UUID(hex=plan.exits[0].reference_id))
    assert lineage.order(close_ref)["state"] == "ACCEPTED"
    assert lineage.owned(880_001)["state"] == "OPEN"
    assert env.ledger.kill_switch_engaged()
    assert [method for method, _ in route.calls].count("POST") == 2
    assert route.calls[-1] == ("GET", DEMO_PNL_PATH)


def test_sd138_final_pnl_detects_changed_baseline_facts_with_same_ids(env, tmp_path):
    gateway, quote, signer, route, lineage, _path, adapter = _composed(env, tmp_path)
    proposal = env.entry()
    adapter.submit_entry(proposal, quote=quote)
    plan = env.rt.plan_exits(bids=env.bids("455"))
    close_quote = signer.seal({
        "canonical_id": proposal.canonical_id, "bid": "455", "ask": "456",
        "quote_time": env.clock.now.isoformat(),
    })
    route.baseline_rows[0]["units"] = 2
    with pytest.raises(SD138Refused, match="stopped for reconciliation") as refused:
        adapter.submit_exit(plan.exits[0], quote=close_quote)
    assert isinstance(refused.value.__cause__, SD138Refused)
    assert "protected four-position baseline" in str(refused.value.__cause__)
    close_ref = str(UUID(hex=plan.exits[0].reference_id))
    assert lineage.order(close_ref)["state"] == "ACCEPTED"
    assert lineage.owned(880_001)["state"] == "OPEN"
    assert env.ledger.kill_switch_engaged()
    assert route.calls[-1] == ("GET", DEMO_PNL_PATH)


def test_sd138_restart_refuses_changed_original_baseline_even_when_ids_match(env, tmp_path):
    gateway, quote, _signer, route, lineage, path, adapter = _composed(env, tmp_path)
    proposal = env.entry()
    adapter.submit_entry(proposal, quote=quote)
    assert not env.ledger.kill_switch_engaged()
    lineage.close()

    # Simulate a broker-side change occurring before the process comes back up:
    # original four position/order IDs are identical, but one unit count differs.
    # Reconstructing the baseline from the now-mutated fixture must NOT rebase it.
    route.baseline_rows[0]["units"] = 2
    restarted_lineage = EtoroDemoLineage(
        str(path), baseline_position_ids=(11, 12, 13, 14),
        baseline_order_ids=(9011, 9012, 9013, 9014),
    )
    try:
        restarted_port = EtoroDemoOrderPort(route, lineage=restarted_lineage)
        with pytest.raises(SD138Refused, match="original protected baseline facts") as exc:
            AutonomousEtoroDemoOrderAdapter(
                policy_gateway=gateway, order_port=restarted_port)
        assert exc.value.__cause__ is not None
        assert "differ from durable original" in str(exc.value.__cause__)
        assert env.ledger.kill_switch_engaged()
        assert [method for method, _ in route.calls].count("POST") == 1
        assert restarted_lineage.owned(880_001)["state"] == "OPEN"
    finally:
        restarted_lineage.close()


def test_sd138_missing_audit_anchor_blocks_final_pnl_get_after_close(env, tmp_path):
    gateway, quote, signer, route, lineage, _path, adapter = _composed(env, tmp_path)
    proposal = env.entry()
    adapter.submit_entry(proposal, quote=quote)
    plan = env.rt.plan_exits(bids=env.bids("455"))
    close_quote = signer.seal({
        "canonical_id": proposal.canonical_id, "bid": "455", "ask": "456",
        "quote_time": env.clock.now.isoformat(),
    })
    original_send = route.send

    def lose_anchor_after_close_lookup(method, path, **kwargs):
        result = original_send(method, path, **kwargs)
        if path == DEMO_CLOSE_INFO_PATH.format(order_id=770_002):
            gateway._audit_journal._anchor.unavailable = True
        return result

    route.send = lose_anchor_after_close_lookup
    with pytest.raises(SD138Refused, match="close stopped for reconciliation"):
        adapter.submit_exit(plan.exits[0], quote=close_quote)
    assert route.calls[-1][1] == DEMO_CLOSE_INFO_PATH.format(order_id=770_002)
    assert all(path != DEMO_PNL_PATH for _, path in route.calls)
    assert [method for method, _ in route.calls].count("POST") == 2
    assert lineage.order(str(UUID(hex=plan.exits[0].reference_id)))["state"] == "ACCEPTED"
    assert env.ledger.kill_switch_engaged()


def test_sd138_lost_close_ack_persists_fence_and_restart_cannot_repost(env, tmp_path):
    gateway, quote, signer, route, lineage, path, adapter = _composed(env, tmp_path)
    proposal = env.entry()
    adapter.submit_entry(proposal, quote=quote)
    plan = env.rt.plan_exits(bids=env.bids("455"))
    close_quote = signer.seal({
        "canonical_id": proposal.canonical_id, "bid": "455", "ask": "456",
        "quote_time": env.clock.now.isoformat(),
    })
    route.lose_next_response = True
    with pytest.raises(SD138Refused, match="close stopped for reconciliation"):
        adapter.submit_exit(plan.exits[0], quote=close_quote)
    close_reference = str(UUID(hex=plan.exits[0].reference_id))
    assert lineage.order(close_reference)["state"] == "OUTCOME_UNKNOWN"
    assert env.ledger.kill_switch_engaged()
    assert [method for method, _ in route.calls].count("POST") == 2
    lineage.close()

    restarted_lineage = EtoroDemoLineage(
        str(path), baseline_position_ids=(11, 12, 13, 14),
        baseline_order_ids=(9011, 9012, 9013, 9014),
    )
    restarted_port = EtoroDemoOrderPort(route, lineage=restarted_lineage)
    open_request = adapter._open_request(proposal)
    _outcome, owner, _payload = restarted_port.lookup_open_with_payload(
        open_request, reference_id=f"recovery:{open_request.reference_id}")
    assert owner is not None
    close_request = DemoCloseRequest(
        close_reference, owner.position_id, proposal.etoro_instrument_id, None)
    with pytest.raises(EtoroDemoOrderError, match="reference or intent already used"):
        restarted_port.submit_owned_close(
            close_request, owner=owner, intent_id=plan.exits[0].reference_id,
            book_id="etoro-demo:tradingagents",
        )
    assert [method for method, _ in route.calls].count("POST") == 2
    assert restarted_lineage.order(close_reference)["state"] == "OUTCOME_UNKNOWN"
    restarted_lineage.close()


def test_sd139_restart_recovers_accepted_close_and_settles_both_ledgers(env, tmp_path):
    gateway, quote, signer, route, lineage, path, adapter = _composed(env, tmp_path)
    proposal = env.entry()
    adapter.submit_entry(proposal, quote=quote)
    plan = env.rt.plan_exits(bids=env.bids("455"))
    close_quote = signer.seal({
        "canonical_id": proposal.canonical_id, "bid": "455", "ask": "456",
        "quote_time": env.clock.now.isoformat(),
    })
    original_send = route.send
    fail_once = True

    def delayed_close_lookup(method, request_path, **kwargs):
        nonlocal fail_once
        if request_path == DEMO_CLOSE_INFO_PATH.format(order_id=770_002) and fail_once:
            fail_once = False
            route.calls.append((method, request_path))
            route.call_references.append(kwargs["reference_id"])
            raise TransportNotFound("simulated close-info visibility delay")
        return original_send(method, request_path, **kwargs)

    route.send = delayed_close_lookup
    with pytest.raises(SD138Refused, match="close stopped for reconciliation"):
        adapter.submit_exit(plan.exits[0], quote=close_quote)
    close_reference = str(UUID(hex=plan.exits[0].reference_id))
    assert lineage.order(close_reference)["state"] == "ACCEPTED"
    assert env.ledger.kill_switch_engaged()
    lineage.close()

    restarted_lineage = EtoroDemoLineage(
        str(path), baseline_position_ids=(11, 12, 13, 14),
        baseline_order_ids=(9011, 9012, 9013, 9014),
    )
    restarted_port = EtoroDemoOrderPort(route, lineage=restarted_lineage)
    restarted = AutonomousEtoroDemoOrderAdapter(
        policy_gateway=gateway, order_port=restarted_port)
    route.send = original_send
    result = restarted.recover_exit(plan.exits[0])

    assert result.classification == "SIMULATED_ROUND_TRIP_CLOSED"
    assert result.realised_pnl_status == "SIMULATED_ONLY_NOT_BROKER_PNL"
    assert env.ledger.state().exits[plan.exits[0].reference_id].outcome == "FILLED"
    assert env.ledger.open_positions() == ()
    assert restarted_lineage.order(close_reference)["state"] == "FILLED"
    assert restarted_lineage.owned(880_001)["state"] == "CLOSED"
    assert [method for method, _ in route.calls].count("POST") == 2
    assert env.ledger.kill_switch_engaged()  # Recovery never clears HALT.
    assert route.call_references[-2:] == [
        f"close-recovery-info:{close_reference}",
        f"close-recovery-pnl:{close_reference}",
    ]
    restarted_lineage.close()


def test_sd139_replays_anchored_close_evidence_after_lineage_ledger_crash(env, tmp_path):
    gateway, quote, signer, route, lineage, path, adapter = _composed(env, tmp_path)
    proposal = env.entry()
    adapter.submit_entry(proposal, quote=quote)
    plan = env.rt.plan_exits(bids=env.bids("455"))
    close_quote = signer.seal({
        "canonical_id": proposal.canonical_id, "bid": "455", "ask": "456",
        "quote_time": env.clock.now.isoformat(),
    })
    original_resolve = gateway._runtime.resolve

    def crash_after_lineage_reconcile(_evidence):
        raise RuntimeError("simulated process stop between durable ledgers")

    gateway._runtime.resolve = crash_after_lineage_reconcile
    with pytest.raises(SD138Refused, match="close stopped for reconciliation"):
        adapter.submit_exit(plan.exits[0], quote=close_quote)
    close_reference = str(UUID(hex=plan.exits[0].reference_id))
    assert lineage.order(close_reference)["state"] == "FILLED"
    assert lineage.owned(880_001)["state"] == "CLOSED"
    assert env.ledger.state().exits[plan.exits[0].reference_id].outcome is None
    assert env.ledger.kill_switch_engaged()
    lineage.close()

    gateway._runtime.resolve = original_resolve
    restarted_lineage = EtoroDemoLineage(
        str(path), baseline_position_ids=(11, 12, 13, 14),
        baseline_order_ids=(9011, 9012, 9013, 9014),
    )
    restarted = AutonomousEtoroDemoOrderAdapter(
        policy_gateway=gateway,
        order_port=EtoroDemoOrderPort(route, lineage=restarted_lineage),
    )
    result = restarted.recover_exit(plan.exits[0])
    assert result.classification == "SIMULATED_ROUND_TRIP_CLOSED"
    assert env.ledger.state().exits[plan.exits[0].reference_id].outcome == "FILLED"
    assert env.ledger.open_positions() == ()
    assert [method for method, _ in route.calls].count("POST") == 2
    assert restarted_lineage.order(close_reference)["state"] == "FILLED"
    assert env.ledger.kill_switch_engaged()
    restarted_lineage.close()


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
