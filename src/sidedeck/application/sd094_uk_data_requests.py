"""SD-094 bounded UK data requests: three independent authorizations (none executed).

Part A — one public GET of ``https://www.gov.uk/bank-holidays.json`` (Open Government
Licence v3.0) to corroborate the XLON closure table. Runs **only** under an owner-
signed SD-077 ``DataAuthorization`` for provider ``GOV_UK_BANK_HOLIDAYS``: exactly one
request, no retries, no redirects, no credentials, 2 MB cap, raw bytes + SHA-256 kept
in the ignored output directory, one-time claim marker, fixed request ledger.

The feed covers England & Wales *bank holidays* only. It cannot corroborate LSE half
days (those need an LSE business-days notice), and it is not LSE-specific: a bank
holiday that the LSE treated differently would still need exchange evidence.

Parts B and C (eToro Demo instrument search and daily candles) are *templates only*.
They are authenticated broker-host requests, which the SD-077 data-authorization path
deliberately never allows; any run would need its own owner-signed, endpoint-specific
one-shot launcher like the SD-052 MSFT lookup, a new budget ledger, and — for C — a
recorded confirmation that the candle endpoint really supplies the required daily
history. Nothing here sends them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Protocol

from sidedeck.application.sd077_data_authorization import (
    DEFAULT_LEDGER,
    AuthorizationRefused,
    DataAuthorization,
    DataRequestLedger,
    claim_authorization,
    prepare,
    signing_command,
    verify_authorization,
)
from sidedeck.application.sd089_exchange_calendar import (
    UK_CLOSURES,
    UK_COVERED_YEARS,
    UK_HALF_DAYS,
    UK_UNCORROBORATED_HALF_DAYS,
)

PROVIDER_A = "GOV_UK_BANK_HOLIDAYS"
URL_A = "https://www.gov.uk/bank-holidays.json"
MAX_BYTES_A = 2_000_000
USER_AGENT = "SideDeck-research/1.0 (one owner-authorized bank-holiday calendar check)"
DIVISION = "england-and-wales"

# Exact scopes for owner review. B and C are never executable from this module.
REQUEST_TEMPLATES: dict[str, dict[str, Any]] = {
    "A": {
        "status": "PREPARED_NOT_AUTHORIZED", "provider": PROVIDER_A, "method": "GET",
        "urls": [URL_A], "max_requests": 1, "max_retries": 0, "credentials": "none",
        "purpose": "corroborate XLON England & Wales closures for the published years",
        "limits": "bank holidays only; LSE half days and exchange-specific closures still "
                  "need LSE evidence",
        "runner": "python -m sidedeck.application.sd094_uk_data_requests run-a ...",
    },
    "B": {
        "status": "TEMPLATE_ONLY_NOT_AUTHORIZED", "provider": "ETORO_DEMO_MARKET_DATA_UK",
        "method": "GET",
        "endpoint": "/api/v1/market-data/search?internalSymbolFull=<symbol>",
        "symbols": "five candidate LSE lines; owner confirms eToro's exact spelling first",
        "max_requests": 5, "max_retries": 0, "stop_on": "first non-200",
        "credentials": "eToro Demo key, read-only market data; never account/portfolio/order",
        "preconditions": ["separate owner-signed one-shot authorization (SD-052 pattern)",
                          "new budget ledger (never the MSFT pilot budget)",
                          "after the MSFT pilot window closes"],
    },
    "C": {
        "status": "TEMPLATE_ONLY_NOT_AUTHORIZED", "provider": "ETORO_DEMO_MARKET_DATA_UK",
        "method": "GET",
        "endpoint": "/api/v1/market-data/instruments/{instrumentId}/history/candles/"
                    "{direction}/{interval}/{candlesCount}",
        "max_requests": 5, "max_retries": 0, "candles": "<= 300 daily",
        "preconditions": ["B completed with verified instrument IDs",
                          "documented confirmation that this endpoint returns daily "
                          "historical OHLCV for LSE instruments (entitlement currently "
                          "NOT_VERIFIED in docs/M2_ETORO_MARKET_DATA_ENDPOINT_MATRIX.md)",
                          "separate owner-signed authorization and new budget ledger"],
    },
}


class CalendarCheckFailed(RuntimeError):
    pass


def verify_against_gov_uk(text: str) -> dict[str, Any]:
    """Compare a gov.uk ``bank-holidays.json`` document with the transcribed XLON table.

    Only years that the feed covers *and* the calendar covers are compared. Every
    mismatch is listed; nothing is corrected automatically.
    """
    try:
        data = json.loads(text)
        events = data[DIVISION]["events"]
        feed = {date.fromisoformat(str(e["date"])): str(e.get("title", "")) for e in events}
    except (ValueError, KeyError, TypeError) as exc:
        raise CalendarCheckFailed(f"unexpected gov.uk document structure: {exc}") from None
    years = sorted({d.year for d in feed} & set(UK_COVERED_YEARS))
    per_year: dict[str, Any] = {}
    for year in years:
        source = {d for d in feed if d.year == year}
        table = {d for d in UK_CLOSURES if d.year == year}
        missing = sorted(source - table)   # in the official feed but not in our table
        extra = sorted(table - source)     # in our table but not in the feed
        per_year[str(year)] = {
            "status": "MATCHED" if not missing and not extra else "MISMATCH",
            "missing_from_table": [d.isoformat() for d in missing],
            "not_in_feed": [d.isoformat() for d in extra],
        }
    uncovered = sorted(set(UK_COVERED_YEARS) - set(years))
    status = "MATCHED" if years and all(v["status"] == "MATCHED" for v in per_year.values()) \
        else ("NO_OVERLAPPING_YEARS" if not years else "MISMATCH")
    return {
        "status": status, "years_compared": years, "per_year": per_year,
        "years_not_in_feed": uncovered,
        "half_days": {
            "status": "NOT_IN_SOURCE",
            "uncorroborated": sorted(d.isoformat() for d in UK_HALF_DAYS),
            "rule_only": sorted(d.isoformat() for d in UK_UNCORROBORATED_HALF_DAYS),
            "note": "gov.uk lists bank holidays only; LSE half days need LSE evidence",
        },
    }


class _Response(Protocol):
    status: int

    def read(self, n: int = -1) -> bytes: ...
    def __enter__(self) -> "_Response": ...
    def __exit__(self, *args: object) -> None: ...


Opener = Callable[[urllib.request.Request, float], _Response]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        raise CalendarCheckFailed("redirect refused")


def default_opener(request: urllib.request.Request, timeout: float) -> _Response:
    if request.full_url != URL_A:
        raise CalendarCheckFailed("URL not allowlisted")
    response: _Response = urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout)
    return response


def draft_authorization_a(issued_at: datetime, *, hours: int = 24) -> DataAuthorization:
    """Unsigned draft for the owner to review, prepare and sign."""
    return DataAuthorization(
        authorization_id=f"sd094a-gov-uk-bank-holidays-{issued_at:%Y%m%d}", provider=PROVIDER_A,
        purpose="SD-094A corroborate XLON England & Wales closures (one public GET)",
        urls=(URL_A,), max_requests=1, max_retries=0, credentials_required=False,
        issued_at=issued_at, expires_at=issued_at + timedelta(hours=hours),
        owner_terms_reviewed=True,
        notes="public unauthenticated GET; Open Government Licence v3.0; no cookies/credentials",
    )


def run_part_a(
    auth: DataAuthorization, ledger: DataRequestLedger, out_dir: Path, *, now: datetime,
    opener: Opener = default_opener,
) -> dict[str, Any]:
    """Exactly one GET under a verified authorization; any failure stops (no retry)."""
    if auth.provider != PROVIDER_A or auth.urls != (URL_A,):
        raise AuthorizationRefused("authorization must cover exactly the gov.uk feed")
    if auth.max_requests != 1 or auth.max_retries != 0 or auth.credentials_required:
        raise AuthorizationRefused("part A allows exactly one unauthenticated request")
    raw_dir = out_dir / "raw" / auth.authorization_id
    if raw_dir.exists():
        raise CalendarCheckFailed("raw output already exists; refusing to overwrite evidence")
    raw_dir.mkdir(parents=True)
    request_id = ledger.reserve(URL_A, now)
    request = urllib.request.Request(URL_A, headers={"User-Agent": USER_AGENT,
                                                     "Accept": "application/json"})
    try:
        with opener(request, 30.0) as response:
            status = int(getattr(response, "status", 0))
            raw = response.read(MAX_BYTES_A + 1)
    except Exception as exc:  # noqa: BLE001 - any transport failure stops; never retried
        ledger.record(request_id, f"FAILED:{type(exc).__name__}")
        raise CalendarCheckFailed(f"request failed ({type(exc).__name__}); not retried") from None
    if status != 200 or len(raw) > MAX_BYTES_A:
        ledger.record(request_id, f"REFUSED_STATUS_{status}_BYTES_{len(raw)}")
        raise CalendarCheckFailed(f"HTTP {status} or oversized response; not retried")
    ledger.record(request_id, "OK")
    (raw_dir / "bank-holidays.json").write_bytes(raw)
    try:
        check = verify_against_gov_uk(raw.decode("utf-8"))
    except UnicodeDecodeError:
        raise CalendarCheckFailed("response is not UTF-8") from None
    summary = {
        "authorization_id": auth.authorization_id, "authorization_digest": auth.digest,
        "retrieved_at": now.astimezone(UTC).isoformat(), "url": URL_A,
        "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
        "requests_used": ledger.used(), "comparison": check,
    }
    (out_dir / f"summary-{auth.authorization_id}.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    from sidedeck.application.sd045_ssh_approval_verifier import SshSignatureVerifier
    from sidedeck.application.sd077_data_authorization import NAMESPACE

    parser = argparse.ArgumentParser(description="SD-094 bounded UK data requests")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("templates", help="print the A/B/C scopes; no network")
    prep = sub.add_parser("prepare-a", help="write the unsigned part-A authorization + digest")
    prep.add_argument("--out-dir", default="data/authorizations")
    check = sub.add_parser("check-a", help="compare a saved gov.uk JSON file offline")
    check.add_argument("file")
    run = sub.add_parser("run-a", help="verify the owner signature, then make exactly one GET")
    run.add_argument("--authorization", required=True)
    run.add_argument("--signature", required=True)
    run.add_argument("--allowed-signers", default="data/approval_allowed_signers")
    run.add_argument("--principal", default="owner@sidedeck")
    run.add_argument("--out-dir", default="data/uk-calendar")
    args = parser.parse_args(argv)
    now = datetime.now(UTC)
    if args.command == "templates":
        print(json.dumps(REQUEST_TEMPLATES, indent=2))
        print("NETWORK_REQUESTS=0")
        return 0
    if args.command == "prepare-a":
        auth = draft_authorization_a(now)
        _, digest_path = prepare(auth, Path(args.out_dir))
        print(f"AUTHORIZATION_DIGEST={auth.digest}")
        print("OWNER_SIGNING_COMMAND=" + signing_command(digest_path, auth.digest))
        print("NETWORK_REQUESTS=0")
        return 0
    if args.command == "check-a":
        print(json.dumps(verify_against_gov_uk(Path(args.file).read_text(encoding="utf-8")),
                         indent=2))
        print("NETWORK_REQUESTS=0")
        return 0
    auth = DataAuthorization.from_json(Path(args.authorization).read_text(encoding="utf-8"))
    verifier = SshSignatureVerifier(args.allowed_signers, args.principal, namespace=NAMESPACE)
    verify_authorization(auth, Path(args.signature).read_text(encoding="ascii"),
                         verifier=verifier, principal=args.principal, now=now)
    claim_authorization(Path(args.authorization), auth)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    DEFAULT_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    summary = run_part_a(auth, DataRequestLedger(DEFAULT_LEDGER, auth), out, now=now)
    print(json.dumps({"requests_used": summary["requests_used"],
                      "comparison_status": summary["comparison"]["status"]}, indent=2))
    print("BROKER_REQUESTS=0; ORDERS=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
