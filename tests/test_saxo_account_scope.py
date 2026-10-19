import pytest

from sidedeck.infrastructure.saxo_account_scope import (
    SaxoAccountScope, verified_scope, _path,
)
from sidedeck.infrastructure.saxo_sim import SaxoSimClient


class OfflineClient(SaxoSimClient):
    def user(self):
        return {"ClientKey": "client=="}
    def accounts(self):
        return {"Data": [{"AccountId": "22866064", "AccountKey": "account==",
                          "Active": True, "Currency": "EUR"}]}


def test_account_scope_derived_from_confirmed_identity():
    scope = verified_scope(OfflineClient(), "22866064")
    assert scope.account_id == "22866064"
    assert _path("balances", scope) == (
        "/port/v1/balances?ClientKey=client%3D%3D&AccountKey=account%3D%3D"
    )


def test_mismatched_identity_is_blocked():
    with pytest.raises(ValueError):
        verified_scope(OfflineClient(), "wrong")
    with pytest.raises(ValueError):
        verified_scope(OfflineClient(), "")


def test_no_arbitrary_url_or_order_submission(monkeypatch):
    monkeypatch.delenv("SAXO_SIM_ACCESS_TOKEN", raising=False)
    client = SaxoSimClient()
    for path in ("https://gateway.saxobank.com/live/openapi/port/v1/balances",
                 "/trade/v2/orders",
                 "/port/v1/balances?ClientKey=x&AccountKey=y&extra=1"):
        with pytest.raises(PermissionError):
            client.get(path)
    scope = SaxoAccountScope("22866064", "account==", "client==")
    with pytest.raises(PermissionError):
        _path("trade", scope)
