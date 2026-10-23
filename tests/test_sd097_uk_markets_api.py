"""SD-097 read-only UK markets summary: provenance never upgraded, values bounded."""
from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

import pytest

from sidedeck.application.sd096_uk_acceptance import run_acceptance
from sidedeck.application.sd097_uk_markets_api import MAX_TEXT, uk_markets_summary
from uk_import_helpers import NOW, build_uk_dir


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_: Any, **__: Any) -> None:
        raise AssertionError("network access attempted in an offline UK test")
    monkeypatch.setattr(socket.socket, "connect", refuse)


def _report(tmp_path: Path) -> Path:
    path = tmp_path / "uk-acceptance.json"
    path.write_text(json.dumps(run_acceptance(tmp_path / "none", tmp_path / "work", now=NOW),
                               default=str), encoding="utf-8")
    return path


def test_without_data_everything_genuine_is_unavailable(tmp_path: Path) -> None:
    out = uk_markets_summary(None, None, now=NOW)
    assert out["execution_enabled"] is False and out["broker_execution"] == "DISABLED_FOR_UK"
    assert out["genuine"]["provenance"] == "UNAVAILABLE"
    assert out["genuine"]["identities"] == [] and out["genuine"]["memberships"] == []
    assert {c["result"] for c in out["genuine"]["candidates"]} == {"ABSTAIN"}
    assert out["fixture"] is None and out["report_reason"] == "no saved SD-096 report configured"
    assert out["authorizations"] == {"A": "NOT_AUTHORIZED", "B": "NOT_AUTHORIZED",
                                     "C": "NOT_AUTHORIZED"}
    assert out["evidence"]["provenance"] == "NO_DATA"
    assert out["calendar"]["id"] == "XLON" and len(out["tracks"]) == 3
    assert all(t["execution"] == "DISABLED" for t in out["tracks"])


def test_licensed_import_is_shown_as_owner_declared_real_data(tmp_path: Path) -> None:
    root = build_uk_dir(tmp_path / "uk")
    out = uk_markets_summary(str(root), None, now=NOW)
    g = out["genuine"]
    assert g["provenance"] == "REAL_DATA" and g["data_basis_attestation"] == "OWNER_DECLARED"
    assert len(g["identities"]) == 3 and all(i["source_unit"] == "GBX" for i in g["identities"])
    assert {m["index_id"] for m in g["memberships"]} == {"FTSE100"}
    assert g["scan"]["scanned"] == 3 and "scan_exclusions" in g["scan"]


def test_fixture_manifest_never_becomes_real_data(tmp_path: Path) -> None:
    root = build_uk_dir(tmp_path / "uk", basis="SYNTHETIC_FIXTURE")
    g = uk_markets_summary(str(root), None, now=NOW)["genuine"]
    assert g["provenance"] == "UNAVAILABLE" and g["status"] == "FIXTURE_MANIFEST_NOT_GENUINE"
    assert g["memberships"] == []


def test_saved_report_is_accepted_only_with_fixture_and_simulation_labels(tmp_path: Path) -> None:
    path = _report(tmp_path)
    out = uk_markets_summary(None, str(path), now=NOW)
    assert out["fixture"]["provenance"] == "SYNTHETIC_FIXTURE"
    assert out["simulation"]["provenance"] == "SIMULATION"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["fixture_scan"]["data_basis"] = "REAL_DATA"                  # relabelling attempt
    path.write_text(json.dumps(data), encoding="utf-8")
    refused = uk_markets_summary(None, str(path), now=NOW)
    assert refused["fixture"] is None and refused["simulation"] is None
    assert refused["report_reason"] == "report provenance invalid; refused"
    path.write_text("{not json", encoding="utf-8")
    assert uk_markets_summary(None, str(path), now=NOW)["report_reason"] == \
        "report unreadable or malformed"


def test_text_from_files_is_length_bounded(tmp_path: Path) -> None:
    root = build_uk_dir(tmp_path / "uk")
    listings = root / "listings.csv"
    text = listings.read_text(encoding="utf-8").replace("BP p.l.c.", "B" * 5000)
    listings.write_text(text, encoding="utf-8")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    import hashlib
    manifest["listings"]["sha256"] = hashlib.sha256(listings.read_bytes()).hexdigest()
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    out = uk_markets_summary(str(root), None, now=NOW)
    names = [i["name"] for i in out["genuine"]["identities"] if i["name"]]
    assert names and max(len(n) for n in names) <= MAX_TEXT
