import pytest

from sidedeck.infrastructure.saxo_account_scope import (
    SaxoAccountScope, verified_scope, _path,
)
from sidedeck.infrastructure.saxo_sim import SaxoSimClient
from sim_gateway_fake import SyntheticGateway, synthetic_gateway


class OfflineClient(SaxoSimClient):
    """A subclass can override get(); it must not be able to mint a verified scope."""

    def user(self):
        return {"ClientKey": "client=="}

    def accounts(self):
        return {"Data": [{"AccountId": "22866064", "AccountKey": "account==",
                          "Active": True, "Currency": "EUR"}]}


GATEWAY = SyntheticGateway("22866064", client_key="client==", account_key="account==")


def test_account_scope_derived_from_confirmed_identity():
    with synthetic_gateway(GATEWAY):
        scope = verified_scope(SaxoSimClient(), "22866064")
    assert scope.account_id == "22866064" and scope.is_authenticated()
    assert _path("balances", scope) == (
        "/port/v1/balances?ClientKey=client%3D%3D&AccountKey=account%3D%3D"
    )
    assert all(url.startswith("https://gateway.saxobank.com/sim/openapi/port/v1/")
               for url in GATEWAY.urls)


def test_mismatched_identity_is_blocked():
    with synthetic_gateway(GATEWAY):
        with pytest.raises(ValueError):
            verified_scope(SaxoSimClient(), "wrong")
        with pytest.raises(ValueError):
            verified_scope(SaxoSimClient(), "")


def test_only_the_real_sim_gateway_client_can_verify_a_scope():
    with pytest.raises(ValueError, match="Saxo SIM gateway client"):
        verified_scope(OfflineClient(), "22866064")


def test_fx_reads_are_limited_to_eurusd():
    client = SaxoSimClient()
    with synthetic_gateway(SyntheticGateway()):
        for uic in (22, 210, 2):
            with pytest.raises(PermissionError):
                client.get(f"/trade/v1/infoprices?AccountKey=a&AssetType=FxSpot&Uic={uic}")


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
