"""SD-053: the exact MSFT eToro Demo pilot intent (C8 schema v2) for the owner to sign.

Offline only: no network, no credentials. Writes the canonical intent bytes and their
SHA-256 digest once (the pilot id is generated once and then fixed; the file is never
overwritten, so the digest the owner signs stays stable).

Fixed parameters (owner configuration 2026-10-22):
* eToro Demo, book ``etoro-demo:tradingagents``, MSFT instrument ID **1004** (SD-052);
* buy, 1x, ``limitIOC``; **0.09 units**; signed maximum limit **552.56** USD;
  0.09 x 552.56 = 49.73 <= USD 50;
* the actual limit is derived at preflight: min(552.56, fresh realtime ask x 1.005);
* ``reference_price`` 526.25 is the SD-052 search ``currentRate``: a **planning**
  reference that bounds the signed maximum (+5 %); it is never used as an executable ask;
* window Friday 2026-10-23 15:15-15:50 America/New_York (EDT) = 19:15-19:50 UTC
  (third attempt: 55d66780 reached open approval but was not signed; fresh id and digest);
* request caps: the reviewed 12-request / 2-write plan (``ROUTE_CAPS``).

Usage::

    .venv\\Scripts\\python.exe -m sidedeck.application.sd053_msft_pilot_intent
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

from sidedeck.application import sd050_msft_instrument_lookup as lookup
from sidedeck.application.sd046_etoro_demo_pilot import MAX_PLANNING_HEADROOM
from sidedeck.application.sd048_pilot_release import PILOT_NAMESPACE, PilotIntent, _check_intent

STRATEGY = "tradingagents"
INSTRUMENT_ID = 1004                         # SD-052, RESOLVED_PARTIALLY_VERIFIED
UNITS = Decimal("0.09")
REFERENCE_PRICE = Decimal("526.25")          # planning reference only (SD-052 currentRate)
MAX_LIMIT_RATE = (REFERENCE_PRICE * (1 + MAX_PLANNING_HEADROOM)).quantize(
    Decimal("0.01"), rounding=ROUND_DOWN)    # 552.56
MAX_NOTIONAL_USD = Decimal("50")
NOT_BEFORE = datetime(2026, 10, 23, 19, 15, tzinfo=timezone.utc)  # 15:15 EDT
EXPIRES_AT = datetime(2026, 10, 23, 19, 50, tzinfo=timezone.utc)  # 15:50 EDT
# Preserve all prior signed intents (incl. the consumed urgent b0be3fe2 pilot); this
# retry has its own file and digest.
INTENT_PATH = lookup.DATA_DIR / "sd053-msft-pilot-intent-20261023-retry3.json"


class IntentRefused(RuntimeError):
    pass


def build_intent(pilot_id: str) -> PilotIntent:
    return PilotIntent(pilot_id=pilot_id, strategy=STRATEGY, instrument_id=INSTRUMENT_ID,
                       units=UNITS, max_limit_rate=MAX_LIMIT_RATE,
                       reference_price=REFERENCE_PRICE, max_notional_usd=MAX_NOTIONAL_USD,
                       not_before=NOT_BEFORE, expires_at=EXPIRES_AT)


def offline_checks(intent: PilotIntent, protected_ids: frozenset[int]) -> None:
    """Same intent bounds the release applies, evaluated at the window start."""
    _check_intent(intent, intent.not_before)
    if intent.instrument_id in protected_ids:
        raise IntentRefused("pilot instrument is a protected baseline instrument")
    if intent.units * intent.max_limit_rate > MAX_NOTIONAL_USD:
        raise IntentRefused("units x max limit exceeds USD 50")


def prepare(path: Path, protected_ids: frozenset[int]) -> dict[str, str]:
    """Create the intent once; afterwards reload it and re-verify its digest."""
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        intent = build_intent(saved["pilot_id"])
        if intent.canonical().decode("utf-8") != saved["canonical"] or \
                intent.digest() != saved["digest"]:
            raise IntentRefused("saved intent does not match the reviewed parameters")
    else:
        intent = build_intent(str(uuid.uuid4()))
    offline_checks(intent, protected_ids)
    record = {"pilot_id": intent.pilot_id, "canonical": intent.canonical().decode("utf-8"),
              "digest": intent.digest(), "namespace": PILOT_NAMESPACE}
    if not path.exists():
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        path.with_suffix(".digest").write_bytes(intent.digest().encode("ascii"))  # no newline
    return record


def main() -> int:
    protected = lookup.baseline_instrument_ids(str(lookup.DATA_DIR / "etoro_demo.sqlite3"))
    record = prepare(INTENT_PATH, protected)
    print(json.dumps({**record, "digest_file": str(INTENT_PATH.with_suffix(".digest")),
                      "execution_release": "NO_GO"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
