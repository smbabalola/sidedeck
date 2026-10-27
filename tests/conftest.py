from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import pytest


@pytest.fixture(autouse=True)
def _no_real_open_lookup_waits(monkeypatch):
    """Pilot rigs that use the real ``time.sleep`` must not wait 3-8 s per open lookup.

    Tests that check the spacing set ``OPEN_LOOKUP_DELAYS`` themselves.
    """
    from sidedeck.application import sd046_etoro_demo_pilot
    monkeypatch.setattr(sd046_etoro_demo_pilot, "OPEN_LOOKUP_DELAYS", (0.0, 0.0, 0.0))
