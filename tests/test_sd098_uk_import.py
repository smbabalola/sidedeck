"""SD-098 owner-supplied UK import: validation, provenance, units, actions and scanner hookup.

All prices are synthetic and live only in pytest temporary directories (see uk_import_helpers).
"""
from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

import pytest

from sidedeck.application.sd096_uk_acceptance import genuine_data_inventory
from sidedeck.application.sd098_uk_import import (
    adjust_for_share_actions,
    import_uk_directory,
    parse_corporate_actions,
    parse_daily_bars,
)
from uk_import_helpers import NOW, build_uk_dir


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_: Any, **__: Any) -> None:
        raise AssertionError("network access attempted in an offline UK test")
    monkeypatch.setattr(socket.socket, "connect", refuse)


def _manifest(root: Path) -> dict[str, Any]:
    return json.loads((root / "manifest.json").read_text(encoding="utf-8"))


def _write_manifest(root: Path, manifest: dict[str, Any]) -> None:
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_licensed_import_feeds_the_real_data_scan(tmp_path: Path) -> None:
    root = build_uk_dir(tmp_path / "uk")
    imported = import_uk_directory(root, now=NOW)
    summary = imported.summary()
    assert (summary["status"], summary["instruments"], summary["bar_series"]) == ("IMPORTED", 3, 3)
    assert summary["data_basis_attestation"] == "OWNER_DECLARED"
    assert summary["rejected"] == [] and len(summary["files"]) == 6
    assert all(r.memberships and r.memberships[0].index_id == "FTSE100"
               for r in imported.registry.records)                       # type: ignore[union-attr]
    series = next(iter(imported.series.values()))
    assert series.source_unit_label == "GBX" and "price-only" in series.provenance
    assert "licence: Owner-licensed test fixture" in series.provenance
    inv = genuine_data_inventory(root, NOW)
    assert inv["status"] == "GENUINE_UK_SCAN_COMPLETED_REVIEW_REQUIRED"
    assert inv["real_scan"]["data_basis"] == "REAL_DATA" and inv["real_scan"]["scanned"] == 3
    gbp = [i["last_close_gbp"] for i in inv["real_scan"]["identities"]]
    assert all(float(g) < 10 for g in gbp)                     # pence normalised to pounds


def test_missing_manifest_is_no_genuine_data(tmp_path: Path) -> None:
    assert import_uk_directory(tmp_path, now=NOW).status == "NO_GENUINE_UK_DATA"


@pytest.mark.parametrize("change, reason", [
    (lambda m: m.update(licence=""), "LICENCE_AND_SOURCE_REQUIRED"),
    (lambda m: m.update(schema="other"), "UNSUPPORTED_MANIFEST_SCHEMA"),
    (lambda m: m.update(data_basis="MAYBE"), "UNKNOWN_DATA_BASIS"),
    (lambda m: m["listings"].update(file="../outside.csv"), "UNSAFE_PATH"),
    (lambda m: m["listings"].update(file="C:/x.csv"), "UNSAFE_PATH"),
    (lambda m: m["listings"].update(sha256="0" * 64), "SHA256_MISMATCH"),
])
def test_manifest_level_failures_are_refused_not_repaired(tmp_path: Path, change: Any,
                                                          reason: str) -> None:
    root = build_uk_dir(tmp_path / "uk")
    manifest = _manifest(root)
    change(manifest)
    _write_manifest(root, manifest)
    result = import_uk_directory(root, now=NOW)
    assert result.status == "MANIFEST_INVALID"
    assert any(reason in r[1] for r in result.rejected), result.rejected


def test_tampered_bar_file_rejects_only_that_series(tmp_path: Path) -> None:
    root = build_uk_dir(tmp_path / "uk", tamper="bars/GB0007980591.csv")
    result = import_uk_directory(root, now=NOW)
    assert result.status == "IMPORTED" and len(result.series) == 2
    assert ("GB0007980591", "SHA256_MISMATCH:bars/GB0007980591.csv") in result.rejected


def test_future_retrieval_and_missing_source_are_rejected(tmp_path: Path) -> None:
    root = build_uk_dir(tmp_path / "uk")
    manifest = _manifest(root)
    manifest["bars"][0]["retrieved_at"] = "2027-01-01T00:00:00+00:00"
    manifest["bars"][1]["source_id"] = ""
    manifest["bars"][2]["unit"] = "gbp"                       # ambiguous unit label
    _write_manifest(root, manifest)
    reasons = dict(import_uk_directory(root, now=NOW).rejected)
    assert reasons["GB0007980591"] == "INVALID_RETRIEVED_AT"
    assert reasons["GB00BP6MXD84"] == "SOURCE_ID_REQUIRED"
    assert "UNKNOWN_OR_AMBIGUOUS_UNIT" in reasons["GB0005405286"]


def test_synthetic_isins_are_refused_in_a_real_import(tmp_path: Path) -> None:
    root = build_uk_dir(tmp_path / "uk")
    listings = (root / "listings.csv").read_text(encoding="utf-8")
    from sidedeck.application.sd096_uk_acceptance import fixture_isin
    row = f"ZZZ,{fixture_isin(1)},Synthetic,ORDINARY_SHARE,GBX,GBP,2001-01-02,,2001-01-02,,x,2026-10-23\n"
    (root / "listings.csv").write_text(listings + row, encoding="utf-8")
    manifest = _manifest(root)
    import hashlib
    manifest["listings"]["sha256"] = hashlib.sha256((root / "listings.csv").read_bytes()).hexdigest()
    _write_manifest(root, manifest)
    result = import_uk_directory(root, now=NOW)
    assert (fixture_isin(1), "SYNTHETIC_ISIN_IN_REAL_IMPORT") in result.rejected


def test_fixture_manifest_is_never_scanned_as_genuine(tmp_path: Path) -> None:
    root = build_uk_dir(tmp_path / "uk", basis="SYNTHETIC_FIXTURE")
    inv = genuine_data_inventory(root, NOW)
    assert inv["status"] == "FIXTURE_MANIFEST_NOT_GENUINE" and inv["real_scan"] is None
    assert all(c["result"] == "ABSTAIN" for c in inv["candidates"])


def test_declared_split_back_adjusts_raw_prices_without_review_flags(tmp_path: Path) -> None:
    adjusted = import_uk_directory(build_uk_dir(tmp_path / "a", split=True), now=NOW)
    assert not [w for w in adjusted.warnings if w[0] == "GB0005405286"]
    hsba = adjusted.series["UK:GB0005405286"].bars
    assert hsba[-61].close < hsba[-59].close * 2                     # continuity restored
    assert any(a.kind == "SPLIT" for a in adjusted.actions)


def test_undeclared_split_is_flagged_for_review(tmp_path: Path) -> None:
    root = build_uk_dir(tmp_path / "uk", split=True)
    (root / "actions.csv").write_text(
        (root / "actions.csv").read_text(encoding="utf-8").splitlines()[0] + "\n",
        encoding="utf-8")
    manifest = _manifest(root)
    import hashlib
    manifest["corporate_actions"]["sha256"] = hashlib.sha256(
        (root / "actions.csv").read_bytes()).hexdigest()
    _write_manifest(root, manifest)
    result = import_uk_directory(root, now=NOW)
    assert any(w[0] == "GB0005405286" and w[1].startswith("REVIEW_LARGE_MOVE")
               for w in result.warnings)


def test_stale_or_gapped_series_are_excluded_by_the_scanner(tmp_path: Path) -> None:
    stale = genuine_data_inventory(build_uk_dir(tmp_path / "s", drop_last=10), NOW)
    assert len(stale["real_scan"]["excluded"]) == 3
    gapped = genuine_data_inventory(build_uk_dir(tmp_path / "g", gap=True), NOW)
    assert gapped["real_scan"]["scan_exclusions"] == {"MISSING_OR_NON_SESSION_BARS": 1}
    assert gapped["real_scan"]["scanned"] == 2


def test_bar_and_action_parsers_refuse_contradictions() -> None:
    from sidedeck.application.sd098_uk_import import UkImportError
    header = "date,open,high,low,close,volume\n"
    for body, reason in [("2026-10-22,1,1,1,1,1\n2026-10-22,1,1,1,1,1\n", "DUPLICATE_DATE"),
                         ("2026-10-22,2,1,1,2,1\n", "INCONSISTENT_OHLC"),
                         ("2026-10-22,NaN,1,1,1,1\n", "NON_FINITE"),
                         ("2026-10-22,0,1,0,1,1\n", "NON_POSITIVE"), ("", "NO_BARS")]:
        with pytest.raises(UkImportError, match=reason):
            parse_daily_bars(header + body)
    with pytest.raises(UkImportError, match="BAR_HEADER"):
        parse_daily_bars("day,o,h,l,c,v\n")
    actions, rejected = parse_corporate_actions(
        "isin,effective_date,kind,ratio_from,ratio_to,amount,currency,source\n"
        "GB0007980591,2026-01-02,SPLIT,2,1,,,src\n"                     # ratio contradicts kind
        "GB0007980591,2026-01-02,MERGER,1,1,,,src\n"
        "GB0007980591,2026-01-02,DIVIDEND,,,5,GBX,\n")
    assert actions == ()
    assert [r[1] for r in rejected] == ["RATIO_CONTRADICTS_KIND", "UNSUPPORTED_ACTION:MERGER",
                                        "MISSING_SOURCE"]
    assert adjust_for_share_actions((), ()) == ()
