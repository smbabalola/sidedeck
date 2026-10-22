"""SD-075A bounded Nasdaq Trader symbol-directory import (owner-signed, max 2 GETs).

Fetches ``nasdaqlisted.txt`` and ``otherlisted.txt`` **only** under a verified
SD-077 ``DataAuthorization`` for provider ``NASDAQ_TRADER_SYMBOL_DIRECTORY``.
One request per file, no retries unless the signed authorization allows them,
no redirects, HTTPS host allowlist, size limit, no credentials or cookies.

Raw bytes are kept under the caller's ignored local directory with SHA-256
hashes; the returned/committable summary holds only sanitized statistics.
These files are *current* symbol lists: every record is SNAPSHOT basis, never
point-in-time membership, tradability or data coverage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Protocol

from sidedeck.application.sd065_market_universe import (
    MarketUniverseRegistry,
    SnapshotParseReport,
    UniverseError,
    merge_snapshots,
    parse_nasdaq_symbol_directory,
)
from sidedeck.application.sd077_data_authorization import (
    DEFAULT_LEDGER,
    AuthorizationRefused,
    claim_authorization,
    DataAuthorization,
    DataRequestLedger,
    verify_authorization,
)

PROVIDER = "NASDAQ_TRADER_SYMBOL_DIRECTORY"
BASE = "https://www.nasdaqtrader.com/dynamic/SymDir/"
FILES = {"nasdaqlisted": BASE + "nasdaqlisted.txt", "otherlisted": BASE + "otherlisted.txt"}
MAX_BYTES = 5_000_000
USER_AGENT = "SideDeck-research/1.0 (bounded owner-authorized symbol directory import)"


class ImportFailed(RuntimeError):
    pass


class _Response(Protocol):
    status: int

    def read(self, n: int = -1) -> bytes: ...
    def __enter__(self) -> "_Response": ...
    def __exit__(self, *args: object) -> None: ...


Opener = Callable[[urllib.request.Request, float], _Response]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        raise ImportFailed("redirect refused")


def default_opener(request: urllib.request.Request, timeout: float) -> _Response:
    if not request.full_url.startswith(BASE):
        raise ImportFailed("host not allowlisted")
    opener = urllib.request.build_opener(_NoRedirect)
    response: _Response = opener.open(request, timeout=timeout)
    return response


@dataclass(frozen=True)
class FileEvidence:
    kind: str
    url: str
    http_status: int
    bytes: int
    sha256: str
    footer: str | None
    accepted: int
    rejected: dict[str, int]
    by_exchange: dict[str, int]
    by_asset_type: dict[str, int]


def _stats(kind: str, url: str, status: int, raw: bytes, report: SnapshotParseReport) -> FileEvidence:
    rejected: dict[str, int] = {}
    for _, reason in report.rejected:
        rejected[reason] = rejected.get(reason, 0) + 1
    by_exchange: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for record in report.records:
        ex = record.tickers[-1].exchange
        by_exchange[ex] = by_exchange.get(ex, 0) + 1
        by_type[record.asset_type] = by_type.get(record.asset_type, 0) + 1
    return FileEvidence(kind, url, status, len(raw), hashlib.sha256(raw).hexdigest(),
                        report.file_creation_line, len(report.records), dict(sorted(rejected.items())),
                        dict(sorted(by_exchange.items())), dict(sorted(by_type.items())))


def run_import(
    auth: DataAuthorization, ledger: DataRequestLedger, out_dir: Path, *, now: datetime,
    opener: Opener = default_opener, snapshot_date: date | None = None,
) -> dict[str, Any]:
    """Fetch both files once each; any failure stops the import (no silent retry)."""
    if auth.provider != PROVIDER:
        raise AuthorizationRefused("authorization is for a different provider")
    if set(auth.urls) != set(FILES.values()):
        raise AuthorizationRefused("authorization must cover exactly the two directory files")
    if auth.max_requests > 2:
        raise AuthorizationRefused("the directory import allows at most 2 requests")
    snapshot_date = snapshot_date or now.astimezone(UTC).date()
    raw_dir = out_dir / "raw" / auth.authorization_id
    if raw_dir.exists():
        raise ImportFailed("raw output already exists; refusing to overwrite evidence")
    raw_dir.mkdir(parents=True)
    status_file = out_dir / f"import-status-{auth.authorization_id}.json"
    status_file.write_text(json.dumps({"status": "IN_PROGRESS"}), encoding="utf-8")
    try:
        return _fetch_all(auth, ledger, out_dir, raw_dir, now, opener, snapshot_date, status_file)
    except Exception as exc:
        status_file.write_text(json.dumps({"status": "FAILED_PARTIAL",
                                           "error": type(exc).__name__}), encoding="utf-8")
        raise


def _fetch_all(
    auth: DataAuthorization, ledger: DataRequestLedger, out_dir: Path, raw_dir: Path,
    now: datetime, opener: Opener, snapshot_date: date, status_file: Path,
) -> dict[str, Any]:
    reports: list[SnapshotParseReport] = []
    evidence: list[FileEvidence] = []
    for kind, url in FILES.items():
        request_id = ledger.reserve(url, now)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                       "Accept": "text/plain"})
        try:
            with opener(request, 30.0) as response:
                status = int(getattr(response, "status", 0))
                raw = response.read(MAX_BYTES + 1)
        except Exception as exc:  # noqa: BLE001 - any transport failure stops the import
            ledger.record(request_id, f"FAILED:{type(exc).__name__}")
            raise ImportFailed(f"{kind}: request failed ({type(exc).__name__}); not retried") from None
        if status != 200 or len(raw) > MAX_BYTES:
            ledger.record(request_id, f"REFUSED_STATUS_{status}_BYTES_{len(raw)}")
            raise ImportFailed(f"{kind}: HTTP {status} or oversized response; not retried")
        ledger.record(request_id, "OK")
        (raw_dir / f"{kind}.txt").write_bytes(raw)
        try:
            report = parse_nasdaq_symbol_directory(
                raw.decode("utf-8"), kind=kind,  # type: ignore[arg-type]
                snapshot_date=snapshot_date,
                provenance=f"{url} retrieved {now.astimezone(UTC).isoformat()} "
                           f"sha256={hashlib.sha256(raw).hexdigest()}",
            )
        except (UnicodeDecodeError, UniverseError) as exc:
            raise ImportFailed(f"{kind}: schema validation failed: {exc}") from None
        reports.append(report)
        evidence.append(_stats(kind, url, status, raw, report))
    records, conflicts = merge_snapshots(*reports)
    registry = MarketUniverseRegistry(1, now, f"SD-075A {auth.authorization_id}", records)
    (out_dir / f"universe-{auth.authorization_id}.json").write_text(registry.to_json(),
                                                                      encoding="utf-8")
    summary: dict[str, Any] = {
        "authorization_id": auth.authorization_id,
        "authorization_digest": auth.digest,
        "retrieved_at": now.astimezone(UTC).isoformat(),
        "snapshot_date": snapshot_date.isoformat(),
        "requests_used": ledger.used(),
        "history_basis": "SNAPSHOT (current listings only; not point-in-time membership)",
        "files": [e.__dict__ for e in evidence],
        "merged_instruments": len(records),
        "cross_file_conflicts_excluded": len(conflicts),
        "registry_digest": registry.digest,
        "tradability": "NOT_ASSESSED (no broker mapping implied)",
        "price_coverage": "UNAVAILABLE (no price data acquired)",
    }
    (out_dir / f"summary-{auth.authorization_id}.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    status_file.write_text(json.dumps({"status": "COMPLETE"}), encoding="utf-8")
    return summary


def draft_authorization(issued_at: datetime, *, hours: int = 24) -> DataAuthorization:
    """Unsigned draft; the owner prepares and signs it (see docs/SD075_REAL_DATA_ACQUISITION.md)."""
    return DataAuthorization(
        authorization_id=f"sd075a-nasdaq-directory-{issued_at:%Y%m%d}", provider=PROVIDER,
        purpose="SD-075A first genuine US symbol-directory snapshot (current listings only)",
        urls=tuple(FILES.values()), max_requests=2, max_retries=0, credentials_required=False,
        issued_at=issued_at, expires_at=issued_at + timedelta(hours=hours),
        owner_terms_reviewed=True,
        notes="public unauthenticated GET; no cookies or credentials; owner reviewed source terms",
    )


def main(argv: list[str] | None = None) -> int:
    from sidedeck.application.sd045_ssh_approval_verifier import SshSignatureVerifier
    from sidedeck.application.sd077_data_authorization import NAMESPACE

    parser = argparse.ArgumentParser(description="SD-075A owner-authorized Nasdaq Trader import")
    sub = parser.add_subparsers(dest="command", required=True)
    draft = sub.add_parser("draft", help="write an unsigned 24-hour draft; no network")
    draft.add_argument("--out", required=True)
    run = sub.add_parser("run", help="verify the owner signature, then make exactly two GETs")
    run.add_argument("--authorization", required=True)
    run.add_argument("--signature", required=True)
    run.add_argument("--allowed-signers", default="data/approval_allowed_signers")
    run.add_argument("--principal", default="owner@sidedeck")
    run.add_argument("--out-dir", default="data/universe")
    args = parser.parse_args(argv)
    now = datetime.now(UTC)
    if args.command == "draft":
        target = Path(args.out)
        if target.exists():
            parser.error("refusing to overwrite draft")
        target.write_text(draft_authorization(now).canonical(), encoding="utf-8")
        print(f"DRAFT_WRITTEN={target}; NETWORK_REQUESTS=0")
        return 0
    auth = DataAuthorization.from_json(Path(args.authorization).read_text(encoding="utf-8"))
    verifier = SshSignatureVerifier(args.allowed_signers, args.principal, namespace=NAMESPACE)
    verify_authorization(auth, Path(args.signature).read_text(encoding="ascii"),
                         verifier=verifier, principal=args.principal, now=now)
    claim_authorization(Path(args.authorization), auth)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    DEFAULT_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    summary = run_import(auth, DataRequestLedger(DEFAULT_LEDGER, auth), out, now=now)
    print(json.dumps({k: summary[k] for k in ("requests_used", "merged_instruments",
                                              "registry_digest", "history_basis")}, indent=2))
    print("BROKER_REQUESTS=0; ORDERS=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
