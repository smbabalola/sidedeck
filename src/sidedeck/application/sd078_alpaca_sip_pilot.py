"""SD-078 (SD-075B) bounded Alpaca SIP daily-bar pilot for ~20 liquid US instruments.

Dormant until the owner signs an SD-077 ``DataAuthorization`` for provider
``ALPACA_SIP_DAILY`` whose URLs are exactly the pilot symbols' bar endpoints.
Earlier SD-021 authorizations are exhausted and are never reused; this pilot
has its own ledger and digest. Credentials are read only *after* the signature
verifies, are sent only to ``data.alpaca.markets`` (market data; never a
trading endpoint) and are never logged. Every HTTP attempt is reserved in the
ledger before transmission; retries are 0; the first failure stops the run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from sidedeck.application.p5_alpaca_history import (
    MarketDataUnavailable,
    _credential,
    _safe_urlopen,
    fetch_alpaca_history,
)
from sidedeck.application.sd014_strategy_engine import StrategyBar
from sidedeck.application.sd077_data_authorization import (
    DEFAULT_LEDGER,
    AuthorizationRefused,
    claim_authorization,
    DataAuthorization,
    DataRequestLedger,
    verify_authorization,
)
from sidedeck.application.sd080_coverage_acceptance import coverage_report

PROVIDER = "ALPACA_SIP_DAILY"
ENDPOINT = "https://data.alpaca.markets/v2/stocks/{symbol}/bars"
# 4 broad ETFs + 16 large, liquid US stocks across sectors (SPY/QQQ/MSFT allow a
# consistency cross-check against the earlier SD-021 bundles).
PILOT_SYMBOLS: tuple[str, ...] = (
    "SPY", "QQQ", "IWM", "DIA",
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "BAC",
    "XOM", "CVX", "JNJ", "UNH", "PG", "KO", "HD", "WMT",
)
PILOT_START = date(2022, 1, 3)
PILOT_END = date(2026, 10, 23)   # last completed XNYS session before the 2026-10-26 draft
PRINCIPAL = "owner@sidedeck"
# SHA-256 of the owner's ssh-ed25519 key blob (same pinned key as the SD-054/SD-064 paths).
PINNED_SIGNER_KEY_SHA256 = "600a7f7e6597cfa2f87b1f3f9891de224c4e2a18b9d534da62888158ebbae0f3"
MAX_REQUESTS = 24  # 20 first pages + 4 contingency pages; 0 retries
# Daily bars are stamped at 04:00/05:00 UTC; a date-only end would drop the final session.
END_PARAM = f"{PILOT_END.isoformat()}T23:59:59Z"
EST_BYTES_PER_BAR = 170


def proposal() -> dict[str, Any]:
    from sidedeck.application.us_equity_calendar import expected_regular_sessions

    sessions = len(expected_regular_sessions(PILOT_START, PILOT_END))
    bars = sessions * len(PILOT_SYMBOLS)
    return {
        "endpoint": "GET " + ENDPOINT + "?timeframe=1Day&feed=sip&adjustment=split&limit=10000",
        "entitlement": "Alpaca market-data SIP historical bars (HTTP 200 observed for SIP in "
                       "SD-021 on 2026-10-21; current entitlement unverified until the run)",
        "instruments": list(PILOT_SYMBOLS), "instrument_count": len(PILOT_SYMBOLS),
        "period": f"{PILOT_START.isoformat()}..{PILOT_END.isoformat()}",
        "granularity": "1Day, regular-session daily bars, split-adjusted",
        "expected_sessions_per_symbol": sessions, "estimated_bars": bars,
        "estimated_storage_bytes": bars * EST_BYTES_PER_BAR,
        "max_authenticated_requests": MAX_REQUESTS, "retries": 0,
        "pagination": "limit=10000 per page; one page expected per symbol "
                      f"({sessions} bars); repeated or invalid cursor aborts",
        "expected_completion": "under 2 minutes (sequential, 0.5 s spacing)",
        "limitations": [
            "split-adjusted only; dividends/total return not included or corroborated",
            "SIP consolidated daily bars per provider; independent corroboration still required",
            "current constituents chosen today: survivorship bias applies to this pilot set",
            "no intraday, quotes or spreads (DAY track remains research-only)",
        ],
        "broker_requests": 0, "orders": 0, "paid_model_calls": 0,
    }


def draft_authorization(issued_at: datetime, *, hours: int = 48,
                        owner_terms_reviewed: bool = False) -> DataAuthorization:
    """``owner_terms_reviewed`` must be set by the owner explicitly (CLI flag); SideDeck
    never asserts it on the owner's behalf, and an unconfirmed draft is refused."""
    return DataAuthorization(
        authorization_id=f"sd075b-alpaca-sip-pilot-{issued_at:%Y%m%d}", provider=PROVIDER,
        purpose="SD-075B first genuine daily-price pilot, 20 liquid US instruments",
        urls=tuple(ENDPOINT.format(symbol=s) for s in PILOT_SYMBOLS),
        max_requests=MAX_REQUESTS, max_retries=0, credentials_required=True,
        issued_at=issued_at, expires_at=issued_at + timedelta(hours=hours),
        owner_terms_reviewed=owner_terms_reviewed,
        notes=f"period {PILOT_START}..{PILOT_END}; feed=sip; adjustment=split; read-only",
    )


Opener = Callable[..., Any]


def check_scope(auth: DataAuthorization) -> None:
    """The pilot's fixed scope. Checked before the single-use claim and again in run_pilot."""
    if auth.provider != PROVIDER:
        raise AuthorizationRefused("authorization is for a different provider")
    if set(auth.urls) != {ENDPOINT.format(symbol=s) for s in PILOT_SYMBOLS}:
        raise AuthorizationRefused("authorization URLs do not match the pilot symbol set")
    if auth.max_retries != 0:
        raise AuthorizationRefused("pilot runs with zero retries")
    if auth.max_requests > MAX_REQUESTS:
        raise AuthorizationRefused(f"pilot allows at most {MAX_REQUESTS} requests")


def run_pilot(
    auth: DataAuthorization, ledger: DataRequestLedger, out_dir: Path, *, key_id: str,
    secret: str, now: Callable[[], datetime], opener: Opener = _safe_urlopen,
    pause: Callable[[], None] = lambda: time.sleep(0.5),
) -> dict[str, Any]:
    check_scope(auth)
    raw_dir = out_dir / "raw" / auth.authorization_id
    if raw_dir.exists():
        raise AuthorizationRefused("pilot output already exists; refusing to overwrite")
    raw_dir.mkdir(parents=True)

    def ledgered(request: Any, timeout: float = 20) -> Any:
        request_id = ledger.reserve(request.full_url, now())
        try:
            response = opener(request, timeout=timeout)
        except Exception as exc:
            ledger.record(request_id, f"FAILED:{type(exc).__name__}")
            raise
        # Recorded before the body is read: a later parse failure still stops the run.
        status = getattr(response, "status", "UNKNOWN")
        ledger.record(request_id, f"SENT_HTTP_{status}_BODY_UNCHECKED")
        return response

    bars_by_id: dict[str, list[StrategyBar] | None] = {}
    manifest: dict[str, Any] = {}
    stopped: str | None = None
    for index, symbol in enumerate(PILOT_SYMBOLS):
        cid = "US:" + symbol
        if stopped:
            bars_by_id[cid] = None
            continue
        if index:
            pause()  # polite sequential pacing between symbols
        try:
            result = fetch_alpaca_history(
                symbol, PILOT_START.isoformat(), END_PARAM, key_id=key_id,
                secret=secret, feed="sip", adjustment="split", open_url=ledgered,
                max_retries=0, cutoff=PILOT_END,
            )
        except (MarketDataUnavailable, AuthorizationRefused) as exc:
            stopped = f"{symbol}: {type(exc).__name__}"
            bars_by_id[cid] = None
            continue
        text = json.dumps(result, sort_keys=True)
        (raw_dir / f"{symbol}.json").write_text(text, encoding="utf-8")
        manifest[symbol] = {"sha256": hashlib.sha256(text.encode()).hexdigest(),
                            "bars": len(result["records"]),
                            "pages": result["pagination_pages"]}
        bars_by_id[cid] = [
            StrategyBar(date.fromisoformat(r["date"]), Decimal(r["open"]), Decimal(r["high"]),
                        Decimal(r["low"]), Decimal(r["close"]), Decimal(r["volume"]))
            for r in result["records"]
        ]
    report = coverage_report(bars_by_id, PILOT_START, PILOT_END,
                             data_basis="ALPACA_SIP_DAILY (split-adjusted)", benchmark_id="US:SPY")
    summary = {
        "authorization_id": auth.authorization_id, "authorization_digest": auth.digest,
        "requests_used": ledger.used(), "stopped_early": stopped,
        "coverage_counts": report.counts, "benchmark_status": report.benchmark_status,
        "instruments": [i.__dict__ for i in report.instruments], "files": manifest,
        "acceptance": "RESEARCH_DATA_ONLY; not G1 accepted until independently corroborated",
    }
    (out_dir / f"summary-{auth.authorization_id}.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SD-075B Alpaca SIP pilot (owner-signed)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("proposal")
    draft = sub.add_parser("draft")
    draft.add_argument("--out", required=True)
    draft.add_argument("--owner-confirms-terms-reviewed", action="store_true",
                       help="the owner states they reviewed Alpaca's market-data terms")
    run = sub.add_parser("run")
    run.add_argument("--authorization", required=True)
    run.add_argument("--signature", required=True)
    run.add_argument("--allowed-signers", default="data/approval_allowed_signers")
    run.add_argument("--env-file", default=".env")
    # No defaults: the owner names the exact credential variables (never their values).
    run.add_argument("--key-id-env", required=True)
    run.add_argument("--secret-env", required=True)
    run.add_argument("--out-dir", default="data/sd075b")
    args = parser.parse_args(argv)
    if args.command == "proposal":
        print(json.dumps(proposal(), indent=2))
        return 0
    if args.command == "draft":
        target = Path(args.out)
        if target.exists():
            parser.error("refusing to overwrite draft")
        if not args.owner_confirms_terms_reviewed:
            parser.error("the owner must pass --owner-confirms-terms-reviewed; nothing written")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(draft_authorization(datetime.now(UTC),
                                              owner_terms_reviewed=True).canonical(),
                          encoding="utf-8")
        print(f"DRAFT_WRITTEN={target}; NETWORK_REQUESTS=0")
        return 0
    from sidedeck.application.sd045_ssh_approval_verifier import SshSignatureVerifier
    from sidedeck.application.sd064_unlock_grant import require_pinned_signer
    from sidedeck.application.sd077_data_authorization import NAMESPACE

    auth = DataAuthorization.from_json(Path(args.authorization).read_text(encoding="utf-8"))
    require_pinned_signer(Path(args.allowed_signers), PRINCIPAL, PINNED_SIGNER_KEY_SHA256)
    verifier = SshSignatureVerifier(args.allowed_signers, PRINCIPAL, namespace=NAMESPACE)
    verify_authorization(auth, Path(args.signature).read_text(encoding="ascii"),
                         verifier=verifier, principal=PRINCIPAL, now=datetime.now(UTC))
    # Scope and credentials are checked before the single-use claim, so a misscoped
    # authorization or a missing/misnamed variable never burns it.
    check_scope(auth)
    key_id = _credential(args.env_file, args.key_id_env)
    secret = _credential(args.env_file, args.secret_env)
    claim_authorization(Path(args.authorization), auth)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    DEFAULT_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    summary = run_pilot(auth, DataRequestLedger(DEFAULT_LEDGER, auth), out, key_id=key_id,
                        secret=secret, now=lambda: datetime.now(UTC))
    print(json.dumps({k: summary[k] for k in ("requests_used", "stopped_early", "coverage_counts",
                                              "benchmark_status")}, indent=2))
    print("BROKER_REQUESTS=0; ORDERS=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
