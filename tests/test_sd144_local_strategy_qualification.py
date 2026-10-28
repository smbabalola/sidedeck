"""SD-144 genuine-data qualification command refuses missing/fixture inputs."""
from datetime import date
from pathlib import Path
import json

import pytest

from sidedeck.application.sd103_trading_pipeline import PipelineError, synthetic_bundle
from sidedeck.application.sd144_local_strategy_qualification import assess_local_bundles, main


def test_no_bundles_cannot_create_strategy_admission():
    with pytest.raises(PipelineError, match="at least one"):
        assess_local_bundles([], through=date(2026, 4, 30))


def test_missing_bundle_returns_blocked_input(tmp_path: Path, capsys):
    result = main(["--bundles", str(tmp_path / "missing.json"),
                   "--out", str(tmp_path / "decision.json")])
    assert result == 5
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED_INPUT"
    assert not (tmp_path / "decision.json").exists()


def test_synthetic_history_never_promoted_into_genuine_admission(tmp_path: Path):
    payload = synthetic_bundle("SPY", start=date(2022, 1, 3),
                               end=date(2026, 10, 23))
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PipelineError, match="no admissible market data"):
        assess_local_bundles([path], through=date(2026, 4, 30))
