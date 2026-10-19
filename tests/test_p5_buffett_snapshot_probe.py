import json
import sys
import types

from sidedeck.application.p5_buffett_snapshot_probe import snapshot_probe


def test_no_llm_snapshot_probe_uses_only_local_data(monkeypatch, tmp_path):
    path = tmp_path / "verified.json"
    path.write_text(json.dumps({"ticker": "SOFI", "records": [
        {"report_period": f"2025-0{i}-28", "filing_date": f"2025-0{i}-28",
         "period": "ttm", "source_url": "https://data.sec.gov/api/xbrl/filing"}
        for i in range(1, 5)
    ]}), encoding="utf-8")
    calls = []

    class FakeAgent:
        def build_snapshot(self, ticker, as_of, client):
            calls.append((ticker, as_of))
            return {"local": True}

    monkeypatch.setitem(sys.modules, "hedge_fund.signals.buffett",
                        types.SimpleNamespace(BuffettAgent=FakeAgent))
    result = snapshot_probe(str(path), "SOFI", "2025-05-01")
    assert result["snapshot_status"] == "CONSTRUCTED_UNVERIFIED"
    assert result["approved"] is False
    assert result["broker_execution"] == "DISABLED"
    assert calls == [("SOFI", "2025-05-01")]


def test_snapshot_probe_reports_failure_without_claiming_approval(monkeypatch, tmp_path):
    path = tmp_path / "verified.json"
    path.write_text(json.dumps({"ticker": "SOFI", "records": [
        {"report_period": f"2025-0{i}-28", "filing_date": f"2025-0{i}-28",
         "period": "ttm", "source_url": "https://data.sec.gov/api/xbrl/filing"}
        for i in range(1, 5)
    ]}), encoding="utf-8")

    class FakeAgent:
        def build_snapshot(self, ticker, as_of, client):
            raise RuntimeError("upstream incompatible")

    monkeypatch.setitem(sys.modules, "hedge_fund.signals.buffett",
                        types.SimpleNamespace(BuffettAgent=FakeAgent))
    result = snapshot_probe(str(path), "SOFI", "2025-05-01")
    assert result["snapshot_status"] == "UNAVAILABLE"
    assert result["error_type"] == "RuntimeError"
    assert result["error_detail"] == "upstream incompatible"
    assert "build_snapshot:" in result["error_location"]
    assert result["buffett_ready"] is False
