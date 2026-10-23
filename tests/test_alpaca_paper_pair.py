"""Two PAPER API credentials do not necessarily mean two paper accounts."""

from dataclasses import asdict
import json

import pytest

from sidedeck import paper_pair
from sidedeck.domain.alpaca_paper import AlpacaPaperAccessBlocked, AlpacaPaperError
from sidedeck.domain.alpaca_paper_pair import DualPaperAccountInspector


class MockPaper:
    def __init__(self, account_id, status="ACTIVE", multiplier="1", account_blocked=False):
        self.account_id = account_id
        self.status = status
        self.multiplier = multiplier
        self.account_blocked = account_blocked
        self.calls = []

    def get(self, path, params):
        self.calls.append((path, dict(params)))
        assert path == "/v2/account"
        assert dict(params) == {}
        return 200, json.dumps({
            "id": self.account_id,
            "status": self.status,
            "cash": "1000", "equity": "1000", "buying_power": "1000",
            "multiplier": self.multiplier,
            "account_blocked": self.account_blocked, "trading_blocked": False,
        }).encode()


def test_different_paper_account_ids_map_two_strategies_without_disclosure():
    left, right = MockPaper("SECRET-A"), MockPaper("SECRET-B")
    status = DualPaperAccountInspector(left, right).inspect()
    assert status.two_accounts_verified is True
    assert status.outcome == "DISTINCT_ACCOUNTS"
    assert status.broker_order_submission_enabled is False
    assert status.both_active and status.both_unblocked
    assert status.first_strategy == "tradingagents"
    assert status.second_strategy == "ai-trading"
    assert left.calls == right.calls == [("/v2/account", {})]
    assert "SECRET-A" not in repr(status) + str(asdict(status))
    assert "SECRET-B" not in repr(status) + str(asdict(status))


def test_two_key_pairs_for_same_broker_paper_account_cannot_be_separated():
    status = DualPaperAccountInspector(MockPaper("SAME"), MockPaper("SAME")).inspect()
    assert not status.two_accounts_verified
    assert status.outcome == "SAME_ACCOUNT"
    assert not status.broker_order_submission_enabled


def test_account_restrictions_and_paper_margin_are_reported_without_enabling_orders():
    status = DualPaperAccountInspector(
        MockPaper("A", multiplier="2"), MockPaper("B", status="SUSPENDED")
    ).inspect()
    assert status.two_accounts_verified
    assert status.margin_possible
    assert not status.both_active
    assert status.outcome == "ACCOUNTS_NOT_READY"
    assert not status.broker_order_submission_enabled


@pytest.mark.parametrize("bad_id", [None, "", [], {}, " "])
def test_missing_or_malformed_account_id_stops_before_claiming_separation(bad_id):
    with pytest.raises(AlpacaPaperError):
        DualPaperAccountInspector(MockPaper(bad_id), MockPaper("B")).inspect()


def test_errors_stop_before_second_account():
    class Denied:
        def __init__(self):
            self.calls = 0
        def get(self, path, params):
            self.calls += 1
            return 403, b'{"detail":"private"}'
    left, right = Denied(), MockPaper("B")
    with pytest.raises(AlpacaPaperAccessBlocked):
        DualPaperAccountInspector(left, right).inspect()
    assert left.calls == 1
    assert not right.calls


def test_offline_dual_account_dry_run_does_not_touch_credentials(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["paper_pair", "--dry-run"])
    monkeypatch.setattr(
        paper_pair, "_paper_pair_credentials",
        lambda: pytest.fail("dry-run must not load private credentials")
    )
    assert paper_pair.main() == 0
    data = json.loads(capsys.readouterr().out)
    assert data["two_accounts_verified"] is True
    assert data["source"] == "FIXTURE_NOT_REAL"
    assert data["broker_order_submission_enabled"] is False
    assert "FIXTURE-PAPER" not in str(data)


def test_network_blocked_without_explicit_owner_opt_in(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "KEY1")
    monkeypatch.setenv("ALPACA_API_KEY2", "KEY2")
    monkeypatch.setattr("sys.argv", ["paper_pair"])
    with pytest.raises(SystemExit):
        paper_pair.main()


def test_local_credential_pairs_require_both_secrets(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "KEY1")
    monkeypatch.setenv("ALPACA_API_KEY2", "KEY2")
    for name in ("ALPACA_SECRET_KEY", "ALPACA_API_SECRET_KEY", "APCA_API_SECRET_KEY",
                 "ALPACA_SECRET_KEY2", "ALPACA_API_SECRET_KEY2", "APCA_API_SECRET_KEY2"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="secret missing"):
        paper_pair._paper_pair_credentials()
    monkeypatch.setenv("ALPACA_SECRET_KEY", "SECRET1")
    monkeypatch.setenv("ALPACA_SECRET_KEY2", "SECRET2")
    left, right = paper_pair._paper_pair_credentials()
    assert left.api_key == "KEY1"
    assert right.api_key == "KEY2"
    assert "SECRET1" not in repr(left)
    assert "SECRET2" not in repr(right)


def test_duplicate_key_ids_or_secrets_are_rejected(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "KEY1")
    monkeypatch.setenv("ALPACA_API_KEY2", "KEY1")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "SECRET1")
    monkeypatch.setenv("ALPACA_SECRET_KEY2", "SECRET2")
    with pytest.raises(ValueError, match="identical"):
        paper_pair._paper_pair_credentials()
    monkeypatch.setenv("ALPACA_API_KEY2", "KEY2")
    monkeypatch.setenv("ALPACA_SECRET_KEY2", "SECRET1")
    with pytest.raises(ValueError, match="identical"):
        paper_pair._paper_pair_credentials()


def test_secret_alias_conflicts_are_rejected_without_values(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "KEY1")
    monkeypatch.setenv("ALPACA_API_KEY2", "KEY2")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "S1")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "S1-MISMATCH")
    monkeypatch.setenv("ALPACA_SECRET_KEY2", "S2")
    with pytest.raises(ValueError, match="conflicting"):
        paper_pair._paper_pair_credentials()


def test_alpaca_api_secret_aliases_are_accepted_for_both_slots(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "KEY1")
    monkeypatch.setenv("ALPACA_API_KEY2", "KEY2")
    for name in ("ALPACA_SECRET_KEY", "ALPACA_API_SECRET_KEY", "APCA_API_SECRET_KEY",
                 "ALPACA_API_SECRET", "ALPACA_SECRET_KEY2", "ALPACA_API_SECRET_KEY2",
                 "APCA_API_SECRET_KEY2", "ALPACA_API_SECRET2"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ALPACA_API_SECRET", "SECRET1")
    monkeypatch.setenv("ALPACA_API_SECRET2", "SECRET2")
    left, right = paper_pair._paper_pair_credentials()
    assert (left.secret_key, right.secret_key) == ("SECRET1", "SECRET2")
    assert "SECRET1" not in repr(left)
    monkeypatch.setenv("ALPACA_SECRET_KEY2", "DIFFERENT")
    with pytest.raises(ValueError, match="conflicting"):
        paper_pair._paper_pair_credentials()
