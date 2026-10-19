import pytest

from sidedeck.application.saxo_order_audit import audit_path, summarize_audit
from sidedeck.infrastructure.saxo_account_scope import SaxoAccountScope
from sidedeck.infrastructure.saxo_sim import SaxoSimClient


def test_account_scoped_audit_path_and_strict_sim_only(monkeypatch):
    scope = SaxoAccountScope("22866064", "acct==", "client==")
    p = audit_path(scope)
    assert p == ("/cs/v1/audit/orderactivities?AccountKey=acct%3D%3D"
                 "&ClientKey=client%3D%3D&EntryType=Last"
                 "&IncludeSubAccounts=false&%24top=100")
    monkeypatch.delenv("SAXO_SIM_ACCESS_TOKEN", raising=False)
    with pytest.raises(PermissionError):
        SaxoSimClient().get("/cs/v1/audit/orderactivities?AccountKey=a")


def test_counts_are_evidence_only():
    result = summarize_audit(
        {"Data": [{"AccountId": "22866064", "ExternalReference": "agent-one"}],
         "__count": 1}, account_id="22866064")
    assert result == (1, 1)


@pytest.mark.parametrize("data", [
    {}, {"Data": {}, "__count": 0},
    {"Data": [], "__next": "/another-page"},
    {"Data": [], "__nextPoll": "/poll"},
    {"Data": [], "__count": 1},
    {"Data": [{"AccountId": "different"}]},
    {"Data": [None]},
])
def test_refuse_incomplete_or_cross_account_audit(data):
    with pytest.raises(ValueError):
        summarize_audit(data, account_id="22866064")
