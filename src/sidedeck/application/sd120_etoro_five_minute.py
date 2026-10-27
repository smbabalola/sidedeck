"""SD-120: single-use, owner-signed eToro five-minute discovery collector.

The collector is dormant until an SD-077 signature verifies.  It is GET-only,
uses the existing persistent request ledger, reads credentials only after all
scope checks pass, and never imports or touches the Demo trading transport.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from sidedeck.application.sd077_data_authorization import (
    DEFAULT_LEDGER,
    AuthorizationRefused,
    DataAuthorization,
    DataRequestLedger,
    NAMESPACE,
    claim_authorization,
    verify_authorization,
)
from sidedeck.application.sd119_etoro_market_data import (
    CANDLES_PATH,
    COVERAGE_PATH,
    LOCAL_PAGE_LIMIT,
    SEARCH_PATH,
    SUPPORTED_SYMBOLS,
    parse_candles,
    parse_coverage,
    parse_instrument_search,
)

PROVIDER = "ETORO_DEMO_MARKET_DATA"
HOST = "https://public-api.etoro.com"
PRINCIPAL = "owner@sidedeck"
PINNED_SIGNER_KEY_SHA256 = "600a7f7e6597cfa2f87b1f3f9891de224c4e2a18b9d534da62888158ebbae0f3"
SAMPLE_FROM = "2026-10-23T14:00:00Z"
SAMPLE_TO = "2026-10-23T15:00:00Z"
MAX_REQUESTS = 9
DIAGNOSTIC_MAX_REQUESTS = 1
DIAGNOSTIC_SYMBOL = "AAPL"
# Only the reviewed eToro Demo key names; no arbitrary inherited secret sources.
_ALLOWED_CREDENTIAL_PAIRS = frozenset({
    ("ETORO_API_KEY", "ETORO_USER_KEY"),
    ("ETORO_DEMO_TRADE_API_KEY", "ETORO_DEMO_TRADE_USER_KEY"),
})


def _require_credential_pair(api_key_env: str, user_key_env: str) -> None:
    if (api_key_env, user_key_env) not in _ALLOWED_CREDENTIAL_PAIRS:
        raise EtoroDiscoveryError("credential environment-name pair is not approved")


class EtoroDiscoveryError(ValueError):
    pass


class EtoroHttpError(EtoroDiscoveryError):
    """Sanitized HTTP failure; body and headers are intentionally discarded."""

    def __init__(self, status: int, classification: str) -> None:
        super().__init__(f"HTTP_{status}:{classification}")
        self.status = status
        self.classification = classification


def _classify_http_status(status: int) -> str:
    if status == 401:
        return "AUTHENTICATION_FAILURE"
    if status == 403:
        return "ACCESS_OR_ENTITLEMENT_DENIED"
    if status == 404:
        return "ENDPOINT_NOT_FOUND"
    if status == 429:
        return "RATE_LIMITED"
    if 500 <= status <= 599:
        return "UPSTREAM_SERVER_FAILURE"
    return "HTTP_FAILURE"


def draft_authorization(issued_at: datetime, *, hours: int = 48,
                        owner_terms_reviewed: bool = False,
                        api_key_env: str = "ETORO_API_KEY",
                        user_key_env: str = "ETORO_USER_KEY") -> DataAuthorization:
    _require_credential_pair(api_key_env, user_key_env)
    if issued_at.tzinfo is None:
        raise EtoroDiscoveryError("issued_at must be timezone-aware")
    return DataAuthorization(
        authorization_id=f"sd120-etoro-5m-{issued_at:%Y%m%d%H%M%S}",
        provider=PROVIDER,
        purpose="SD-120 bounded eToro Demo five-minute market-data discovery",
        urls=(
            f"{HOST}{SEARCH_PATH}",
            f"{HOST}{COVERAGE_PATH}",
            f"{HOST}{CANDLES_PATH}",
        ),
        max_requests=MAX_REQUESTS,
        max_retries=0,
        credentials_required=True,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(hours=hours),
        owner_terms_reviewed=owner_terms_reviewed,
        notes="GET-only; Demo market data; no broker/account/order endpoints",
        scope={
            "symbols": list(SUPPORTED_SYMBOLS),
            "from": SAMPLE_FROM,
            "to": SAMPLE_TO,
            "interval": "5m",
            "side": "both",
            "limit": LOCAL_PAGE_LIMIT,
            "credential_source": {"api_key_env": api_key_env, "user_key_env": user_key_env},
            "request_sequence": ["search", "coverage", "sample"],
        },
    )


def check_scope(auth: DataAuthorization, *, api_key_env: str, user_key_env: str) -> None:
    _require_credential_pair(api_key_env, user_key_env)
    if auth.provider != PROVIDER or auth.max_requests != MAX_REQUESTS or auth.max_retries != 0:
        raise AuthorizationRefused("authorization is not the fixed SD-120 scope")
    expected_urls = {f"{HOST}{SEARCH_PATH}", f"{HOST}{COVERAGE_PATH}", f"{HOST}{CANDLES_PATH}"}
    if set(auth.urls) != expected_urls:
        raise AuthorizationRefused("authorization endpoint scope does not match SD-120")
    expected = {
        "symbols": list(SUPPORTED_SYMBOLS), "from": SAMPLE_FROM, "to": SAMPLE_TO,
        "interval": "5m", "side": "both", "limit": LOCAL_PAGE_LIMIT,
        "request_sequence": ["search", "coverage", "sample"],
        "credential_source": {"api_key_env": api_key_env, "user_key_env": user_key_env},
    }
    if auth.scope != expected:
        raise AuthorizationRefused("authorization scope does not match requested symbols or parameters")


def draft_diagnostic_authorization(
    issued_at: datetime, *, hours: int = 48, owner_terms_reviewed: bool = False,
    api_key_env: str = "ETORO_API_KEY", user_key_env: str = "ETORO_USER_KEY",
) -> DataAuthorization:
    """Create the deliberately separate, single-AAPL diagnostic scope."""
    _require_credential_pair(api_key_env, user_key_env)
    if issued_at.tzinfo is None:
        raise EtoroDiscoveryError("issued_at must be timezone-aware")
    return DataAuthorization(
        authorization_id=f"sd120-aapl-diagnostic-{issued_at:%Y%m%d%H%M%S}",
        provider=PROVIDER,
        purpose="SD-120 one-request eToro Demo AAPL HTTP diagnostic",
        urls=(f"{HOST}{SEARCH_PATH}",),
        max_requests=DIAGNOSTIC_MAX_REQUESTS,
        max_retries=0,
        credentials_required=True,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(hours=hours),
        owner_terms_reviewed=owner_terms_reviewed,
        notes="GET-only; one AAPL search; no broker/account/order endpoints",
        scope={
            "method": "GET", "symbol": DIAGNOSTIC_SYMBOL, "endpoint": SEARCH_PATH,
            "credential_source": {"api_key_env": api_key_env, "user_key_env": user_key_env},
            "query": {"internalSymbolFull": DIAGNOSTIC_SYMBOL},
        },
    )


def check_diagnostic_scope(
    auth: DataAuthorization, *, api_key_env: str, user_key_env: str,
) -> None:
    _require_credential_pair(api_key_env, user_key_env)
    expected = {
        "method": "GET", "symbol": DIAGNOSTIC_SYMBOL, "endpoint": SEARCH_PATH,
        "credential_source": {"api_key_env": api_key_env, "user_key_env": user_key_env},
        "query": {"internalSymbolFull": DIAGNOSTIC_SYMBOL},
    }
    if (auth.provider != PROVIDER or auth.max_requests != DIAGNOSTIC_MAX_REQUESTS
            or auth.max_retries != 0 or auth.urls != (f"{HOST}{SEARCH_PATH}",)
            or auth.scope != expected):
        raise AuthorizationRefused("authorization is not the fixed SD-120 AAPL diagnostic scope")


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        raise EtoroDiscoveryError("redirect rejected")


def _safe_open(request: urllib.request.Request, *, timeout: float = 20) -> Any:
    parsed = urllib.parse.urlsplit(request.full_url)
    if parsed.scheme != "https" or parsed.netloc != "public-api.etoro.com":
        raise EtoroDiscoveryError("host is not allowlisted")
    return urllib.request.build_opener(_RejectRedirects).open(request, timeout=timeout)


def _credential(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise EtoroDiscoveryError(f"credential environment variable {name} is missing")
    return value


def _read_json(response: Any) -> tuple[int, bytes, dict[str, Any]]:
    status = getattr(response, "status", None)
    raw = response.read(8_000_001)
    if len(raw) > 8_000_000:
        raise EtoroDiscoveryError("response exceeds bounded size")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise EtoroDiscoveryError("response is not JSON") from None
    if not isinstance(payload, dict):
        raise EtoroDiscoveryError("response JSON is not an object")
    if not isinstance(status, int):
        raise EtoroDiscoveryError("response status is missing")
    return status, raw, payload


def _url(path: str, query: dict[str, str] | None = None) -> str:
    return HOST + path + ("?" + urllib.parse.urlencode(query) if query else "")


def _valid_aapl_search(payload: dict[str, Any]) -> bool:
    rows = payload.get("results", payload.get("items", payload.get("data")))
    if not isinstance(rows, list):
        return False
    matches = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("internalSymbolFull", row.get("symbol", ""))).upper()
        if symbol.split("/", 1)[0] == DIAGNOSTIC_SYMBOL:
            instrument_id = row.get("instrumentId", row.get("internalInstrumentId"))
            if isinstance(instrument_id, bool) or not isinstance(instrument_id, int) or instrument_id <= 0:
                return False
            matches.append(row)
    return len(matches) == 1


def run_discovery(
    auth: DataAuthorization, ledger: DataRequestLedger, *, api_key: str, user_key: str,
    api_key_env: str = "ETORO_API_KEY", user_key_env: str = "ETORO_USER_KEY",
    out_dir: Path, opener: Callable[..., Any] = _safe_open,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    check_scope(auth, api_key_env=api_key_env, user_key_env=user_key_env)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise AuthorizationRefused("output directory is not empty")
    out_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []

    def request(path: str, query: dict[str, str]) -> tuple[int, bytes, dict[str, Any]]:
        full = _url(path, query)
        request_id = ledger.reserve(full, now())
        req = urllib.request.Request(full, method="GET", headers={
            "Accept": "application/json", "x-api-key": api_key,
            "x-user-key": user_key, "x-request-id": str(uuid4()),
        })
        try:
            with opener(req, timeout=20) as response:
                status, raw, payload = _read_json(response)
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            ledger.record(request_id, f"HTTP_{status}")
            raise EtoroHttpError(status, _classify_http_status(status)) from None
        except Exception as exc:
            ledger.record(request_id, f"FAILED:{type(exc).__name__}")
            raise
        ledger.record(request_id, f"HTTP_{status}")
        return status, raw, payload

    stopped_early: dict[str, Any] | None = None
    for index, symbol in enumerate(SUPPORTED_SYMBOLS):
        search_entry: dict[str, Any] = {"symbol": symbol, "kind": "search"}
        try:
            status, raw, payload = request(SEARCH_PATH, {"internalSymbolFull": symbol})
            search_entry.update({"status": status, "sha256": hashlib.sha256(raw).hexdigest()})
            instrument_id = parse_instrument_search(payload, symbol)
            search_entry["identity"] = "EXACT"
        except EtoroHttpError as exc:
            search_entry.update({"status": exc.status, "result": "HTTP_ERROR",
                                 "classification": exc.classification})
            records.append(search_entry)
            stopped_early = {"symbol": symbol, "status": exc.status,
                             "classification": exc.classification}
            for skipped in SUPPORTED_SYMBOLS[index + 1:]:
                records.append({"symbol": skipped, "kind": "search", "status": "SKIPPED",
                                "result": "STOPPED_AFTER_HTTP_ERROR"})
            break
        except Exception as exc:
            search_entry.update({"status": "FAILED", "result": type(exc).__name__})
            records.append(search_entry)
            stopped_early = {"symbol": symbol, "status": "LOCAL_FAILURE",
                             "classification": type(exc).__name__}
            for skipped in SUPPORTED_SYMBOLS[index + 1:]:
                records.append({"symbol": skipped, "kind": "search", "status": "SKIPPED",
                                "result": "STOPPED_AFTER_LOCAL_FAILURE"})
            break
        records.append(search_entry)

        coverage_entry: dict[str, Any] = {"symbol": symbol, "kind": "coverage"}
        try:
            status, raw, payload = request(COVERAGE_PATH.replace("{instrumentId}", str(instrument_id)), {})
            coverage = parse_coverage(payload, instrument_id=instrument_id, symbol=symbol)
            coverage_entry.update({"status": status, "sha256": hashlib.sha256(raw).hexdigest(),
                                   "coverage": coverage["intervals"]})
            has_5m = any(item["interval"] == "5m" and item["candles"] > 0 for item in coverage["intervals"])
        except EtoroHttpError as exc:
            coverage_entry.update({"status": exc.status, "result": "HTTP_ERROR",
                                   "classification": exc.classification})
            records.append(coverage_entry)
            stopped_early = {"symbol": symbol, "status": exc.status,
                             "classification": exc.classification}
            break
        except Exception as exc:
            coverage_entry.update({"status": "FAILED", "result": type(exc).__name__})
            records.append(coverage_entry)
            continue
        records.append(coverage_entry)
        if not has_5m:
            continue

        sample_entry: dict[str, Any] = {"symbol": symbol, "kind": "sample"}
        try:
            query = {"interval": "5m", "from": SAMPLE_FROM, "to": SAMPLE_TO,
                     "side": "both", "limit": str(LOCAL_PAGE_LIMIT), "format": "verbose"}
            status, raw, payload = request(CANDLES_PATH.replace("{instrumentId}", str(instrument_id)), query)
            candles = parse_candles(payload, instrument_id=instrument_id, symbol=symbol)
            sample_entry.update({"status": status, "sha256": hashlib.sha256(raw).hexdigest(),
                                 "rows": len(candles), "schema": "ETORO_VERBOSE_BID_ASK_CANONICAL"})
        except EtoroHttpError as exc:
            sample_entry.update({"status": exc.status, "result": "HTTP_ERROR",
                                 "classification": exc.classification})
            stopped_early = {"symbol": symbol, "status": exc.status,
                             "classification": exc.classification}
        except Exception as exc:
            sample_entry.update({"status": "FAILED", "result": type(exc).__name__})
        records.append(sample_entry)

    report = {
        "schema": "sidedeck-etoro-discovery/1", "research_only": True,
        "authorization_id": auth.authorization_id, "authorization_digest": auth.digest,
        "requests_used": ledger.used(), "max_requests": MAX_REQUESTS,
        "window": {"from": SAMPLE_FROM, "to": SAMPLE_TO}, "interval": "5m", "side": "both",
        "records": records, "stopped_early": stopped_early, "broker_execution": "DISABLED",
    }
    (out_dir / "summary.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    ledger.auth  # keep the authorization visibly bound to this run
    return report


def run_diagnostic(
    auth: DataAuthorization, ledger: DataRequestLedger, *, api_key: str, user_key: str,
    api_key_env: str = "ETORO_API_KEY", user_key_env: str = "ETORO_USER_KEY",
    out_dir: Path, opener: Callable[..., Any] = _safe_open,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """Run exactly one signed-scope AAPL GET and retain sanitized evidence only."""
    check_diagnostic_scope(auth, api_key_env=api_key_env, user_key_env=user_key_env)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise AuthorizationRefused("output directory is not empty")
    out_dir.mkdir(parents=True, exist_ok=True)
    full = _url(SEARCH_PATH, {"internalSymbolFull": DIAGNOSTIC_SYMBOL})
    request_id = ledger.reserve(full, now())
    req = urllib.request.Request(full, method="GET", headers={
        "Accept": "application/json", "x-api-key": api_key,
        "x-user-key": user_key, "x-request-id": str(uuid4()),
    })
    evidence: dict[str, Any] = {
        "schema": "sidedeck-etoro-aapl-diagnostic/1", "research_only": True,
        "authorization_id": auth.authorization_id, "authorization_digest": auth.digest,
        "endpoint": f"{HOST}{SEARCH_PATH}", "method": "GET", "symbol": DIAGNOSTIC_SYMBOL,
        "requests_used": 1, "max_requests": DIAGNOSTIC_MAX_REQUESTS,
        "broker_execution": "DISABLED", "response_sha256": None,
        "schema_result": "UNAVAILABLE", "result_count": None,
    }
    try:
        with opener(req, timeout=20) as response:
            status, raw, payload = _read_json(response)
        evidence["status"] = status
        evidence["classification"] = "SUCCESS"
        evidence["response_sha256"] = hashlib.sha256(raw).hexdigest()
        if not _valid_aapl_search(payload):
            evidence["schema_result"] = "INVALID_SEARCH_RESPONSE"
        else:
            evidence["schema_result"] = "VALID_SEARCH_RESPONSE"
        results = payload.get("results")
        evidence["result_count"] = len(results) if isinstance(results, list) else None
        ledger.record(request_id, f"HTTP_{status}")
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        evidence.update({"status": status, "classification": _classify_http_status(status)})
        ledger.record(request_id, f"HTTP_{status}")
    except Exception as exc:
        ledger.record(request_id, f"FAILED:{type(exc).__name__}")
        raise
    (out_dir / "summary.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8"
    )
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SD-120 eToro five-minute discovery (owner-signed, GET-only)")
    sub = parser.add_subparsers(dest="command", required=True)
    draft = sub.add_parser("draft")
    draft.add_argument("--out", required=True)
    draft.add_argument("--owner-confirms-terms-reviewed", action="store_true")
    draft.add_argument("--api-key-env", default="ETORO_API_KEY")
    draft.add_argument("--user-key-env", default="ETORO_USER_KEY")
    diagnostic_draft = sub.add_parser("diagnostic-draft")
    diagnostic_draft.add_argument("--out", required=True)
    diagnostic_draft.add_argument("--owner-confirms-terms-reviewed", action="store_true")
    diagnostic_draft.add_argument("--api-key-env", default="ETORO_API_KEY")
    diagnostic_draft.add_argument("--user-key-env", default="ETORO_USER_KEY")
    run = sub.add_parser("run")
    run.add_argument("--authorization", required=True)
    run.add_argument("--signature", required=True)
    run.add_argument("--allowed-signers", default="data/approval_allowed_signers")
    run.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    run.add_argument("--out-dir", default="data/sd120-etoro-5m")
    run.add_argument("--api-key-env", default="ETORO_API_KEY")
    run.add_argument("--user-key-env", default="ETORO_USER_KEY")
    diagnostic = sub.add_parser("diagnostic-run")
    diagnostic.add_argument("--authorization", required=True)
    diagnostic.add_argument("--signature", required=True)
    diagnostic.add_argument("--allowed-signers", default="data/approval_allowed_signers")
    diagnostic.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    diagnostic.add_argument("--out-dir", default="data/sd120-aapl-diagnostic")
    diagnostic.add_argument("--api-key-env", default="ETORO_API_KEY")
    diagnostic.add_argument("--user-key-env", default="ETORO_USER_KEY")
    args = parser.parse_args(argv)
    if args.command == "draft":
        target = Path(args.out)
        if target.exists() or not args.owner_confirms_terms_reviewed:
            parser.error("refusing to overwrite or draft without owner terms confirmation")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(draft_authorization(
            datetime.now(UTC), owner_terms_reviewed=True,
            api_key_env=args.api_key_env, user_key_env=args.user_key_env,
        ).canonical(), encoding="utf-8")
        print(f"DRAFT_WRITTEN={target}; NETWORK_REQUESTS=0")
        return 0
    if args.command == "diagnostic-draft":
        target = Path(args.out)
        if target.exists() or not args.owner_confirms_terms_reviewed:
            parser.error("refusing to overwrite or draft without owner terms confirmation")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(draft_diagnostic_authorization(
            datetime.now(UTC), owner_terms_reviewed=True,
            api_key_env=args.api_key_env, user_key_env=args.user_key_env,
        ).canonical(), encoding="utf-8")
        print(f"DRAFT_WRITTEN={target}; NETWORK_REQUESTS=0")
        return 0
    from sidedeck.application.sd045_ssh_approval_verifier import SshSignatureVerifier
    from sidedeck.application.sd064_unlock_grant import require_pinned_signer
    auth = DataAuthorization.from_json(Path(args.authorization).read_text(encoding="utf-8"))
    diagnostic_mode = args.command == "diagnostic-run"
    if diagnostic_mode:
        check_diagnostic_scope(auth, api_key_env=args.api_key_env, user_key_env=args.user_key_env)
    else:
        check_scope(auth, api_key_env=args.api_key_env, user_key_env=args.user_key_env)
    require_pinned_signer(Path(args.allowed_signers), PRINCIPAL, PINNED_SIGNER_KEY_SHA256)
    verifier = SshSignatureVerifier(args.allowed_signers, PRINCIPAL, namespace=NAMESPACE)
    verify_authorization(auth, Path(args.signature).read_text(encoding="ascii"), verifier=verifier,
                         principal=PRINCIPAL, now=datetime.now(UTC))
    # Credential access occurs only after signature, signer and scope verification.
    api_key = _credential(args.api_key_env)
    user_key = _credential(args.user_key_env)
    claim_authorization(Path(args.authorization), auth)
    if diagnostic_mode:
        report = run_diagnostic(auth, DataRequestLedger(Path(args.ledger), auth),
                                api_key=api_key, user_key=user_key,
                                api_key_env=args.api_key_env, user_key_env=args.user_key_env,
                                out_dir=Path(args.out_dir))
        print(json.dumps({"requests_used": report["requests_used"], "status": report["status"],
                          "classification": report["classification"],
                          "broker_execution": "DISABLED"}, sort_keys=True))
    else:
        report = run_discovery(auth, DataRequestLedger(Path(args.ledger), auth), api_key=api_key,
                               user_key=user_key, api_key_env=args.api_key_env,
                               user_key_env=args.user_key_env, out_dir=Path(args.out_dir))
        print(json.dumps({"requests_used": report["requests_used"], "records": len(report["records"]),
                          "broker_execution": "DISABLED"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
