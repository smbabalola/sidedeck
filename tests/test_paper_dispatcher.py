"""Guarded Alpaca PAPER dispatcher: zero actual account calls, mocked only."""

from dataclasses import replace
from datetime import timedelta
import json

import pytest

from sidedeck.domain import alpaca_paper_http_post as http
from sidedeck.domain.paper_desk import PaperDeskError
from sidedeck.domain.paper_dispatcher import GuardedPaperDispatcher
from sidedeck.paper import PaperCredentials
from tests.test_paper_submission import NOW, new_draft, order_ack
from sidedeck.domain.paper_outbox import DurablePaperDesk


def setup(tmp_path):
    desk = DurablePaperDesk(tmp_path / "paper.sqlite3")
    desk.initialize(opened_at=NOW - timedelta(minutes=1))
    draft = new_draft(desk)
    dispatcher = GuardedPaperDispatcher(
        desk, PaperCredentials("FAKE_A", "SECRET_A"),
        PaperCredentials("FAKE_B", "SECRET_B"),
    )
    permit = http.PaperOrderPermit(
        draft.client_order_id, draft.key_slot, NOW + timedelta(seconds=30),
        verified_account_slot=True, owner_confirmed=True,
    )
    return desk, draft, dispatcher, permit


def patched_accounts_and_post(monkeypatch, *, same_account=False, blocked=False,
                              post_result=None):
    calls = {"get": [], "post": []}

    def get(self, path, params):
        key = self._credentials.api_key
        calls["get"].append((key, path))
        if path == "/v2/account":
            account_id = ("COMMON" if same_account else key)
            return 200, json.dumps({
                "id": account_id, "status": "ACTIVE",
                "cash": "100000", "equity": "100000",
                "buying_power": "100000", "multiplier": "2",
                "account_blocked": blocked, "trading_blocked": False,
            }).encode()
        if path == "/v2/orders:by_client_order_id":
            return 200, json.dumps(post_result).encode()
        raise AssertionError("non-allowed paper GET")

    def send(self, draft, *, permit, now):
        calls["post"].append((self._auth.api_key, draft.client_order_id))
        if isinstance(post_result, Exception):
            raise post_result
        return 200, post_result if post_result is not None else order_ack(draft)

    monkeypatch.setattr("sidedeck.paper.AlpacaPaperHttpTransport.get", get)
    monkeypatch.setattr(http.AlpacaPaperPostTransport, "send", send)
    return calls


def test_dispatch_default_disabled_no_keys_used_no_broker_get_or_post(tmp_path, monkeypatch):
    desk, draft, client, permit = setup(tmp_path)
    monkeypatch.setattr(http, "NETWORK_PAPER_WRITES_ENABLED", False)
    calls = patched_accounts_and_post(monkeypatch)
    with pytest.raises(PaperDeskError, match="disabled"):
        client.dispatch(draft.client_order_id, key_slot=draft.key_slot,
                        permit=permit, now=NOW)
    assert calls == {"get": [], "post": []}
    assert desk.paper_submission_status(draft.client_order_id) == "NOT_SENT"


def test_one_mock_post_routes_only_first_key_and_ack_survives_restart(tmp_path, monkeypatch):
    desk, draft, client, permit = setup(tmp_path)
    monkeypatch.setattr(http, "NETWORK_PAPER_WRITES_ENABLED", True)
    calls = patched_accounts_and_post(monkeypatch)
    result = client.dispatch(draft.client_order_id, key_slot=draft.key_slot,
                             permit=permit, now=NOW)
    assert result.outcome == "ACKNOWLEDGED"
    assert result.write_transport == "ALPACA_PAPER_ONLY"
    assert calls["get"] == [("FAKE_A", "/v2/account"), ("FAKE_B", "/v2/account")]
    assert calls["post"] == [("FAKE_A", draft.client_order_id)]
    restarted = DurablePaperDesk(desk.path)
    assert restarted.paper_submission_status(draft.client_order_id) == "ACKNOWLEDGED"
    assert restarted.order_binding(draft.client_order_id)[1] is not None
    assert restarted.snapshot()["strategies"]["tradingagents"]["cash"] == "1000"
    with pytest.raises(PaperDeskError):
        client.dispatch(draft.client_order_id, key_slot=draft.key_slot,
                        permit=permit, now=NOW)
    assert len(calls["post"]) == 1


def test_mock_timeout_keeps_uncertain_and_refuses_retry(tmp_path, monkeypatch):
    desk, draft, client, permit = setup(tmp_path)
    monkeypatch.setattr(http, "NETWORK_PAPER_WRITES_ENABLED", True)
    calls = patched_accounts_and_post(monkeypatch, post_result=TimeoutError("ambiguous"))
    result = client.dispatch(draft.client_order_id, key_slot=draft.key_slot,
                             permit=permit, now=NOW)
    assert result.outcome == "UNCERTAIN_CHECK_BY_CLIENT_ORDER_ID"
    assert DurablePaperDesk(desk.path).paper_submission_status(draft.client_order_id) == "UNCERTAIN"
    with pytest.raises(PaperDeskError, match="already attempted"):
        client.dispatch(draft.client_order_id, key_slot=draft.key_slot,
                        permit=permit, now=NOW)
    assert len(calls["post"]) == 1


def test_readonly_recovery_after_original_permit_expired(tmp_path, monkeypatch):
    desk, draft, client, permit = setup(tmp_path)
    monkeypatch.setattr(http, "NETWORK_PAPER_WRITES_ENABLED", True)
    calls = patched_accounts_and_post(monkeypatch, post_result=TimeoutError("lost"))
    client.dispatch(draft.client_order_id, key_slot=draft.key_slot,
                    permit=permit, now=NOW)
    assert desk.paper_submission_status(draft.client_order_id) == "UNCERTAIN"
    monkeypatch.setattr(http, "NETWORK_PAPER_WRITES_ENABLED", False)
    patched_accounts_and_post(monkeypatch, post_result=order_ack(draft))
    with pytest.raises(PaperDeskError, match="permission"):
        client.recover_uncertain(draft.client_order_id, key_slot=draft.key_slot)
    out = client.recover_uncertain(
        draft.client_order_id, key_slot=draft.key_slot,
        read_only_authorized=True,
    )
    assert out.outcome == "ACKNOWLEDGED"
    assert desk.paper_submission_status(draft.client_order_id) == "ACKNOWLEDGED"
    assert len(calls["post"]) == 1


@pytest.mark.parametrize("invalid", [
    {"owner_confirmed": False}, {"verified_account_slot": False},
    {"key_slot": "ALPACA_API_KEY2"},
    {"client_order_id": "wrong"},
    {"expires_at": NOW - timedelta(seconds=1)},
])
def test_no_paper_reads_or_writes_without_permit(tmp_path, monkeypatch, invalid):
    desk, draft, client, permit = setup(tmp_path)
    monkeypatch.setattr(http, "NETWORK_PAPER_WRITES_ENABLED", True)
    calls = patched_accounts_and_post(monkeypatch)
    with pytest.raises(PaperDeskError, match="permit"):
        client.dispatch(draft.client_order_id, key_slot=draft.key_slot,
                        permit=replace(permit, **invalid), now=NOW)
    assert calls == {"get": [], "post": []}
    assert desk.paper_submission_status(draft.client_order_id) == "NOT_SENT"


@pytest.mark.parametrize("same,blocked", [(True, False), (False, True)])
def test_same_or_blocked_accounts_cannot_dispatch(tmp_path, monkeypatch, same, blocked):
    desk, draft, client, permit = setup(tmp_path)
    monkeypatch.setattr(http, "NETWORK_PAPER_WRITES_ENABLED", True)
    calls = patched_accounts_and_post(monkeypatch, same_account=same, blocked=blocked)
    with pytest.raises(PaperDeskError):
        client.dispatch(draft.client_order_id, key_slot=draft.key_slot,
                        permit=permit, now=NOW)
    assert calls["post"] == []
    assert desk.paper_submission_status(draft.client_order_id) == "NOT_SENT"


def test_wrong_strategy_slot_cannot_touch_any_broker(tmp_path, monkeypatch):
    desk, draft, client, permit = setup(tmp_path)
    monkeypatch.setattr(http, "NETWORK_PAPER_WRITES_ENABLED", True)
    calls = patched_accounts_and_post(monkeypatch)
    with pytest.raises(PaperDeskError):
        client.dispatch(draft.client_order_id, key_slot="ALPACA_API_KEY2",
                        permit=permit, now=NOW)
    assert calls == {"get": [], "post": []}


def test_recovery_404_does_not_clear_uncertainty_or_repeat_post(tmp_path, monkeypatch):
    desk, draft, client, permit = setup(tmp_path)
    monkeypatch.setattr(http, "NETWORK_PAPER_WRITES_ENABLED", True)
    calls = patched_accounts_and_post(monkeypatch, post_result=TimeoutError("lost"))
    client.dispatch(draft.client_order_id, key_slot=draft.key_slot,
                    permit=permit, now=NOW)
    def denied_get(self, path, params):
        return 404, b""
    monkeypatch.setattr("sidedeck.paper.AlpacaPaperHttpTransport.get", denied_get)
    with pytest.raises(Exception):
        client.recover_uncertain(draft.client_order_id, key_slot=draft.key_slot,
                                 read_only_authorized=True)
    assert desk.paper_submission_status(draft.client_order_id) == "UNCERTAIN"
    assert len(calls["post"]) == 1
