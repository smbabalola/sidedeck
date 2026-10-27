from pathlib import Path
from decimal import Decimal

import pytest

from sidedeck.application.sd114_day_trader_runs import main
from sidedeck.modules.day_trader.research import load_owner_csv, orb_backtest


def test_owner_csv_keeps_unverified_provenance_and_hashes_input(tmp_path: Path) -> None:
    source = tmp_path / "bars.csv"
    source.write_text(
        "timestamp,open,high,low,close,volume\n"
        "2026-10-27T13:30:00Z,100,101,99,100.5,1200\n"
        "2026-10-27T13:35:00Z,100.5,102,100,101,1400\n",
        encoding="utf-8",
    )
    bars, provenance = load_owner_csv(source, source_label="Owner supplied", licence_reference="owner note")
    assert len(bars) == 2
    assert bars[0].start.isoformat() == "2026-10-27T13:30:00+00:00"
    assert provenance["basis"] == "OWNER_SUPPLIED_UNVERIFIED_NOT_ADMISSION_EVIDENCE"
    assert provenance["strategy_admission_eligible"] is False
    assert provenance["rows"] == 2 and len(provenance["sha256"]) == 64


@pytest.mark.parametrize("rows, message", [
    ("2026-10-27T13:30:00,100,101,99,100,1", "UTC offset"),
    ("2026-10-27T14:30:00+01:00,100,101,99,100,1", "expressed in UTC"),
    ("2026-10-27T13:30:00Z,100,99,98,100,1", "OHLC"),
    ("2026-10-27T13:30:00Z,100,101,99,100,1\n2026-10-27T13:30:00Z,100,101,99,100,1", "increasing"),
])
def test_owner_csv_fails_closed(rows: str, message: str, tmp_path: Path) -> None:
    source = tmp_path / "bad.csv"
    source.write_text("timestamp,open,high,low,close,volume\n" + rows + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_owner_csv(source, source_label="local", licence_reference="unverified")


def test_owner_csv_requires_traceability(tmp_path: Path) -> None:
    source = tmp_path / "bars.csv"
    source.write_text("timestamp,open,high,low,close,volume\n2026-10-27T13:30:00Z,1,1,1,1,0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="traceability"):
        load_owner_csv(source, source_label="", licence_reference="")


def test_local_csv_backtest_is_reported_as_unverified_research(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "bars.csv"
    source.write_text(
        "timestamp,open,high,low,close,volume\n"
        "2026-10-27T13:30:00Z,100,101,99,100,100\n"
        "2026-10-27T13:35:00Z,100,101,99,100,100\n", encoding="utf-8",
    )
    assert main(["backtest-csv", "--csv", str(source), "--source-label", "local",
                 "--licence-reference", "operator-note"]) == 0
    output = capsys.readouterr().out
    assert "OWNER_SUPPLIED_UNVERIFIED_NOT_ADMISSION_EVIDENCE" in output
    assert '"strategy_admission":"BLOCKED"' in output
    assert '"broker_execution":"DISABLED"' in output


def test_backtest_rejects_non_positive_target() -> None:
    with pytest.raises(ValueError, match="target R"):
        orb_backtest([], target_r=Decimal("0"))
