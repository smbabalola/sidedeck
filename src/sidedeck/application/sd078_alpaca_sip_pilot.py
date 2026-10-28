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
import urllib.parse
import urllib.request
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



def collect_signed_spy_five_minute(
    auth: DataAuthorization, ledger: DataRequestLedger, *, key_id: str,
    secret: str, now: Callable[[], datetime], opener: Opener = _safe_urlopen,
    checkpoint_dir: Path | None = None,
) -> dict[str, Any]:
    """Offline-testable historical collection; caller must verify owner signature.

    This function never grants research admission or execution permission.
    It requires the separate ALPACA_SIP_INTRADAY scope and reserves each page
    before network access. The existing DAILY pilot is unaffected.
    """
    import re
    from sidedeck.application.sd068_track_scheduler import NEW_YORK, session_for

    url = ENDPOINT.format(symbol="SPY")
    if (auth.provider != "ALPACA_SIP_INTRADAY" or auth.urls != (url,)
            or auth.max_retries != 0 or auth.max_requests > 20
            or auth.scope.get("timeframe") != "5Min"):
        raise AuthorizationRefused("SPY 5Min acquisition requires a separate bounded grant")
    if not key_id or not secret:
        raise AuthorizationRefused("missing intraday data credentials")
    begin = datetime.fromisoformat(auth.scope["start"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(auth.scope["end"].replace("Z", "+00:00"))
    if (begin.tzinfo is None or end.tzinfo is None
            or begin.utcoffset() is None or end.utcoffset() is None):
        raise AuthorizationRefused("signed intraday range must be timezone-aware")
    token: str | None = None
    seen: set[str] = set()
    bars: list[dict[str, str]] = []
    excluded_extended_hours = 0
    pages = 0
    page_counts: list[dict[str, int]] = []
    if checkpoint_dir is not None:
        checkpoint_dir.mkdir(parents=True, exist_ok=False)
    while pages < auth.max_requests:
        params = dict(auth.scope)
        if token is not None:
            params["page_token"] = token
        request = urllib.request.Request(
            url + "?" + urllib.parse.urlencode(params),
            headers={"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret,
                     "Accept": "application/json"},
        )
        request_id = ledger.reserve(request.full_url, now())
        pages += 1
        try:
            with opener(request, timeout=20) as response:
                status = getattr(response, "status", 200)
                ledger.record(request_id, f"SENT_HTTP_{status}_BODY_UNCHECKED")
                if status != 200:
                    raise MarketDataUnavailable("Alpaca intraday HTTP status not OK")
                raw = response.read(8_000_001)
                if len(raw) > 8_000_000:
                    raise MarketDataUnavailable("Alpaca intraday response exceeds limit")
                payload = json.loads(raw)
        except Exception as exc:
            if not isinstance(exc, MarketDataUnavailable):
                try:
                    ledger.record(request_id, f"FAILED:{type(exc).__name__}")
                except AuthorizationRefused:
                    pass  # HTTP status already durably recorded.
            raise MarketDataUnavailable("Alpaca intraday request failed") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("bars"), list):
            raise MarketDataUnavailable("invalid Alpaca intraday response")
        page_first = len(bars)
        for row in payload["bars"]:
            if not isinstance(row, dict) or not isinstance(row.get("t"), str):
                raise MarketDataUnavailable("invalid five-minute timestamp")
            stamp = row["t"]
            try:
                dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError:
                raise MarketDataUnavailable("invalid five-minute timestamp") from None
            if dt.tzinfo is None or dt.utcoffset() is None:
                raise MarketDataUnavailable("naive five-minute timestamp")
            dt = dt.astimezone(UTC)
            if dt.second or dt.microsecond or dt.minute % 5:
                raise MarketDataUnavailable("off-grid five-minute timestamp")
            if not begin <= dt < end:
                raise MarketDataUnavailable("intraday bar outside signed date window")
            session = session_for(dt.astimezone(NEW_YORK).date())
            if (session is None or dt < session.open_utc
                    or dt + timedelta(minutes=5) > session.close_utc):
                excluded_extended_hours += 1
                continue  # Pre/post-market bars are not part of the ORB session.
            numeric = {}
            for key in ("o", "h", "l", "c", "v"):
                try:
                    val = Decimal(str(row[key]))
                except (KeyError, ValueError, ArithmeticError):
                    raise MarketDataUnavailable("invalid five-minute OHLCV") from None
                if not val.is_finite() or val <= 0:
                    raise MarketDataUnavailable("invalid five-minute OHLCV")
                numeric[key] = val
            if (numeric["h"] < max(numeric["o"], numeric["c"])
                    or numeric["l"] > min(numeric["o"], numeric["c"])):
                raise MarketDataUnavailable("inconsistent five-minute OHLC")
            bars.append({"timestamp_utc": dt.isoformat(),
                         **{key: str(value) for key, value in numeric.items()}})
        page_counts.append({"page": pages, "raw_bars": len(payload["bars"]),
                            "accepted_regular_bars": len(bars) - page_first})
        if checkpoint_dir is not None:
            page_file = checkpoint_dir / f"page-{pages:03d}.json"
            page_bytes = json.dumps(bars[page_first:], sort_keys=True).encode("utf-8")
            page_file.write_bytes(page_bytes)
            checkpoint = {"pages": pages, "raw_count": len(payload["bars"]),
                          "page_sha256": hashlib.sha256(page_bytes).hexdigest(),
                          "accepted_count": len(bars), "page_accepted_count": len(bars) - page_first,
                          "complete": False,
                          "strategy_admission_eligible": False}
            pending = checkpoint_dir / "progress.tmp"
            pending.write_text(json.dumps(checkpoint), encoding="utf-8")
            pending.replace(checkpoint_dir / "progress.json")
        nxt = payload.get("next_page_token")
        if nxt is None:
            break
        if not isinstance(nxt, str) or not re.fullmatch(r"[A-Za-z0-9_+/=-]{1,512}", nxt) or nxt in seen:
            raise MarketDataUnavailable("invalid intraday pagination token")
        seen.add(nxt)
        token = nxt
    else:
        raise MarketDataUnavailable("intraday page budget exhausted; no completed dataset")
    stamps = [bar["timestamp_utc"] for bar in bars]
    if not stamps or stamps != sorted(set(stamps)):
        raise MarketDataUnavailable("missing, duplicate or out-of-order intraday bars")
    return {"schema": "sidedeck-alpaca-five-minute-raw/1",
            "symbol": "SPY", "feed": "sip", "timeframe": "5Min",
            "authorization_digest": auth.digest, "pages": pages,
            "bars": bars, "excluded_extended_hours": excluded_extended_hours,
            "data_rights": "UNVERIFIED",
            "strategy_admission_eligible": False, "broker_execution": "DISABLED"}


def inspect_saved_spy_orb(path: Path) -> dict[str, Any]:
    """Inspect a saved, real-data five-minute sample offline; NEVER admit signals."""
    from sidedeck.application.sd068_track_scheduler import NEW_YORK, session_for
    from sidedeck.application.sd069_day_trader_methods import (
        IntradayBar, opening_range_breakout,
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    if (payload.get("schema") != "sidedeck-alpaca-five-minute-raw/1"
            or payload.get("symbol") != "SPY"
            or payload.get("feed") != "sip"
            or payload.get("timeframe") != "5Min"
            or payload.get("strategy_admission_eligible") is not False):
        raise MarketDataUnavailable("not an unadmitted SPY five-minute research file")
    rows = payload.get("bars")
    if not isinstance(rows, list) or not rows:
        raise MarketDataUnavailable("no saved five-minute bars")
    by_day: dict[date, list[IntradayBar]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise MarketDataUnavailable("malformed saved bar")
        try:
            stamp = datetime.fromisoformat(row["timestamp_utc"])
            vals = [Decimal(row[key]) for key in ("o", "h", "l", "c", "v")]
        except (KeyError, TypeError, ValueError, ArithmeticError):
            raise MarketDataUnavailable("malformed saved OHLCV or timestamp") from None
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise MarketDataUnavailable("saved timestamp must be timezone-aware")
        stamp = stamp.astimezone(UTC)
        if (stamp.second or stamp.microsecond or stamp.minute % 5
                or any(not v.is_finite() or v <= 0 for v in vals)
                or vals[1] < max(vals[0], vals[3])
                or vals[2] > min(vals[0], vals[3])):
            raise MarketDataUnavailable("invalid saved five-minute bar")
        day = stamp.astimezone(NEW_YORK).date()
        by_day.setdefault(day, []).append(IntradayBar(stamp, *vals))
    findings = []
    for day, day_bars in sorted(by_day.items()):
        session = session_for(day)
        if session is None:
            raise MarketDataUnavailable("bars on a non-trading day")
        expected = [session.open_utc + timedelta(minutes=5 * i)
                    for i in range(int((session.close_utc - session.open_utc).total_seconds() // 300))]
        actual = [bar.start for bar in day_bars]
        if actual != expected:
            raise MarketDataUnavailable(f"incomplete or nonconsecutive SPY session {day}")
        hit = opening_range_breakout(day_bars, session.close_utc)
        # Research-only fill convention: signal is known at the hit bar CLOSE;
        # enter at the NEXT bar OPEN; stop at the opening-range LOW.
        # If there is no next regular bar, no trade is counted.
        trade: dict[str, Any] | None = None
        if hit is not None:
            next_index = next((i for i, bar in enumerate(day_bars)
                               if bar.start == hit.hit_at), None)
            if next_index is not None:
                entry = day_bars[next_index].open
                stop = hit.range_low
                if entry > stop:
                    exit_price = day_bars[-1].open
                    exit_reason = "EOD_LAST_BAR_OPEN_PROXY"
                    for future in day_bars[next_index:]:
                        if future.low <= stop:
                            exit_price = min(stop, future.open)
                            exit_reason = "STOP"
                            break
                    risk = entry - stop
                    slip = Decimal("0.0002")
                    fee = Decimal("0.0001")
                    stressed_entry = entry * (1 + slip)
                    stressed_exit = exit_price * (1 - slip)
                    stressed_net_r = (stressed_exit - stressed_entry - fee * (stressed_entry + stressed_exit)) / risk
                    trade = {"entry_at": day_bars[next_index].start.isoformat(),
                             "entry": str(entry), "stop": str(stop),
                             "exit": str(exit_price), "exit_reason": exit_reason,
                             "gross_r": str((exit_price - entry) / risk),
                             "stressed_net_r": str(stressed_net_r)}
        findings.append({
            "trade": trade,
            "date": day.isoformat(), "bars": len(actual),
            "opening_high": str(max(b.high for b in day_bars[:3])),
            "opening_low": str(min(b.low for b in day_bars[:3])),
            "orb_breakout": hit is not None,
            "first_hit_at": hit.hit_at.isoformat() if hit else None,
        })
    trades = [d["trade"] for d in findings if d["trade"] is not None]
    gross = [Decimal(t["gross_r"]) for t in trades]
    net = [Decimal(t["stressed_net_r"]) for t in trades]
    equity = peak = drawdown = Decimal(0)
    for result in net:
        equity += result
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    split = max(1, (len(findings) * 3) // 5)
    oos = [Decimal(d["trade"]["stressed_net_r"]) for d in findings[split:] if d["trade"] is not None]
    performance = {"train_sessions": split, "oos_sessions": len(findings) - split,
                   "oos_completed_trades": len(oos),
                   "oos_stressed_net_total_r": str(sum(oos, Decimal(0))),
                   "oos_qualification": "INSUFFICIENT_DATA" if len(oos) < 30 else "UNVERIFIED",
                   "completed": len(net), "gross_total_r": str(sum(gross, Decimal(0))),
                   "stressed_net_total_r": str(sum(net, Decimal(0))),
                   "stressed_max_drawdown_r": str(drawdown),
                   "stressed_average_r": str(sum(net, Decimal(0)) / len(net)) if net else None,
                   "cost_model": "2 bps adverse slippage each side; 1 bp fee each side",
                   "qualification": "INSUFFICIENT_DATA" if len(net) < 30 else "UNVERIFIED"}
    return {
        "performance": performance,
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "sessions": len(findings), "total_bars": len(rows),
        "orb_breakout_sessions": sum(1 for finding in findings if finding["orb_breakout"]),
        "completed_research_trades": sum(1 for finding in findings if finding["trade"] is not None),
        "assumptions": "next-bar open; opening-range-low stop; EOD exit; gross R excluding costs; research only",
        "days": findings, "research_only": True,
        "strategy_admission_eligible": False, "broker_execution": "DISABLED",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SD-075B Alpaca SIP pilot (owner-signed)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("proposal")
    inspect = sub.add_parser("inspect-spy-orb")
    inspect.add_argument("--input", required=True)
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
    intraday_draft = sub.add_parser("draft-intraday")
    intraday_draft.add_argument("--out", required=True)
    intraday_draft.add_argument("--owner-confirms-terms-reviewed", action="store_true")
    intraday_draft.add_argument("--short-probe", action="store_true", help="one-week 5-request SPY evidence probe")
    intraday = sub.add_parser("run-intraday")
    intraday.add_argument("--authorization", required=True)
    intraday.add_argument("--signature", required=True)
    intraday.add_argument("--allowed-signers", default="data/approval_allowed_signers")
    intraday.add_argument("--env-file", default=".env")
    intraday.add_argument("--key-id-env", required=True)
    intraday.add_argument("--secret-env", required=True)
    intraday.add_argument("--out-dir", default="data/sd156")
    args = parser.parse_args(argv)
    if args.command == "inspect-spy-orb":
        print(json.dumps(inspect_saved_spy_orb(Path(args.input)), indent=2))
        return 0
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
    if args.command == "draft-intraday":
        if not args.owner_confirms_terms_reviewed:
            parser.error("owner must review data-use terms before preparing intraday grant")
        target = Path(args.out)
        if target.exists():
            parser.error("refusing to overwrite intraday draft")
        issued = datetime.now(UTC)
        auth = DataAuthorization(
            authorization_id=f"sd156-spy-5min-{issued:%Y%m%d%H%M%S}",
            provider="ALPACA_SIP_INTRADAY",
            purpose="One-year SPY five-minute SIP historical research collection only",
            urls=(ENDPOINT.format(symbol="SPY"),),
            max_requests=5 if args.short_probe else 20, max_retries=0, credentials_required=True,
            issued_at=issued, expires_at=issued + timedelta(hours=24),
            owner_terms_reviewed=True,
            scope={"timeframe": "5Min", "feed": "sip", "adjustment": "split",
                   "start": "2026-10-19T00:00:00Z" if args.short_probe else "2025-10-27T00:00:00Z",
                   "end": "2026-10-24T00:00:00Z",
                   "limit": "10000"},
            notes="research only, no data purchase or broker orders",
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(auth.canonical(), encoding="utf-8")
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
    if args.command == "run-intraday":
        if (auth.provider != "ALPACA_SIP_INTRADAY"
                or auth.urls != (ENDPOINT.format(symbol="SPY"),)
                or auth.max_requests > 20 or auth.max_retries != 0):
            raise AuthorizationRefused("intraday SPY authorization scope refused")
    else:
        check_scope(auth)
    key_id = _credential(args.env_file, args.key_id_env)
    secret = _credential(args.env_file, args.secret_env)
    claim_authorization(Path(args.authorization), auth)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    DEFAULT_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    if args.command == "run-intraday":
        target = out / f"raw-spy-5min-{auth.authorization_id}.json"
        if target.exists():
            raise AuthorizationRefused("intraday raw output already exists")
        summary = collect_signed_spy_five_minute(
            auth, DataRequestLedger(DEFAULT_LEDGER, auth),
            key_id=key_id, secret=secret, now=lambda: datetime.now(UTC),
            checkpoint_dir=out / f"checkpoint-{auth.authorization_id}",
        )
        target.write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")
        print(json.dumps({"bars": len(summary["bars"]), "pages": summary["pages"],
                          "strategy_admission_eligible": False,
                          "broker_execution": "DISABLED"}, indent=2))
    else:
        summary = run_pilot(auth, DataRequestLedger(DEFAULT_LEDGER, auth), out, key_id=key_id,
                            secret=secret, now=lambda: datetime.now(UTC))
        print(json.dumps({k: summary[k] for k in ("requests_used", "stopped_early", "coverage_counts",
                                                  "benchmark_status")}, indent=2))
    print("BROKER_REQUESTS=0; ORDERS=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
