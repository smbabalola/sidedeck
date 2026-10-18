import pytest

from sidedeck import data_probe


def test_probe_requires_explicit_read_only_opt_in(monkeypatch):
    monkeypatch.setattr("sys.argv", ["data_probe", "--provider", "etoro"])
    with pytest.raises(SystemExit):
        data_probe.main()


def test_probe_does_not_start_without_credentials(monkeypatch):
    monkeypatch.setattr("sys.argv", ["data_probe", "--provider", "etoro", "--market-data-only", "--allow-read-network", "--confirm-owner-read-only"])
    monkeypatch.delenv("ETORO_API_KEY", raising=False)
    monkeypatch.delenv("ETORO_USER_KEY", raising=False)
    with pytest.raises(SystemExit):
        data_probe.main()
