import pytest
from sidedeck.application.saxo_preflight import check
from sidedeck.infrastructure.saxo_sim import SaxoSimClient, SaxoSimError


def test_sim_only_configuration():
    with pytest.raises(ValueError):
        SaxoSimClient(base_url="https://gateway.saxobank.com/live/openapi")
    with pytest.raises(ValueError):
        SaxoSimClient(token_env="SAXO_LIVE_ACCESS_TOKEN")


def test_order_endpoints_rejected_before_credentials(monkeypatch):
    monkeypatch.delenv("SAXO_SIM_ACCESS_TOKEN", raising=False)
    client = SaxoSimClient()
    for path in ("/trade/v2/orders", "/port/v1/accounts/me?x=1",
                 "https://gateway.saxobank.com/live/openapi/port/v1/users/me"):
        with pytest.raises(PermissionError):
            client.get(path)
    with pytest.raises(SaxoSimError, match="unavailable"):
        client.user()


class OfflineSaxo(SaxoSimClient):
    def user(self):
        return {"UserKey": "synthetic-user"}
    def accounts(self):
        return {"Data": [{"AccountId": "SIM-USD", "AccountKey": "synthetic-key", "Active": True}]}


def test_preflight_accepts_only_matching_active_sim_account():
    assert check(OfflineSaxo(), expected_account_id="SIM-USD") == (
        True, "sim_readonly_identity_verified"
    )
    assert check(OfflineSaxo(), expected_account_id="WRONG")[0] is False
    assert check(OfflineSaxo(), expected_account_id="")[0] is False


class InactiveSaxo(OfflineSaxo):
    def accounts(self):
        return {"Data": [{"AccountId": "SIM-USD", "AccountKey": "synthetic-key", "Active": False}]}


def test_inactive_account_blocks():
    assert check(InactiveSaxo(), expected_account_id="SIM-USD") == (
        False, "sim_account_inactive"
    )
