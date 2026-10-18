import pytest
from urllib.error import HTTPError
from email.message import Message
from uuid import uuid4

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


def test_four_instrument_dry_run_is_network_free(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["data_probe", "--provider", "etoro", "--dry-run"])
    assert data_probe.main() == 0
    output = capsys.readouterr().out
    assert '"mode": "dry-run"' in output
    assert output.count('"status": "INSUFFICIENT_DEPTH"') == 4


def test_urllib_transport_normalizes_http_error_without_exposing_body(monkeypatch):
    headers = Message()
    headers["Retry-After"] = "1"

    class Opener:
        def open(self, request, timeout):
            raise HTTPError(request.full_url, 429, "rate limited", headers, __import__("io").BytesIO(b"private response"))

    monkeypatch.setattr(data_probe, "build_opener", lambda handler: Opener())
    status, returned_headers, body = data_probe.UrllibReadOnlyTransport({"x-api-key": "redacted"}).get("/market-data/search", {}, uuid4())
    assert status == 429
    assert returned_headers["Retry-After"] == "1"
    assert body == b"private response"
