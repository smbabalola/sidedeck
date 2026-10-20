"""P4 GO/NO-GO evaluator; never contacts Saxo or submits an order.

Code-safety gates are evaluated by exercising the real guards. External gates
never trust caller-supplied values: a request must carry this process's
preparation seal, the precheck its transport seal, quote/FX evidence must be
re-verified by a registered verifier type, and the operator signature is
re-checked here with a verifier built from ``allowed_signers``. The offline
CLI has none of this evidence, so it always reports NO-GO.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from sidedeck.application import saxo_sim_submission as submission
from sidedeck.application.saxo_market_data import ExecutionEvidence, MarketEvidenceVerifier
from sidedeck.application.saxo_sim_submission import evidence_digest
from sidedeck.infrastructure import saxo_precheck, saxo_sim
from sidedeck.infrastructure.saxo_operator_approval import SshSignatureApprovalVerifier
from sidedeck.infrastructure.saxo_submit_transport import SaxoSimSubmitTransport

SIM_PREFIX = "https://gateway.saxobank.com/sim/openapi"
MARKET_MAX_AGE = timedelta(minutes=2)


@dataclass(frozen=True)
class Gate:
    name: str
    status: str  # PASS | FAIL | MISSING | DISABLED | NOT_APPLICABLE
    detail: str


def _code_gates() -> list[Gate]:
    gates: list[Gate] = []
    hosts = (saxo_sim.SIM_BASE, submission.SIM_HOST, saxo_precheck._PRECHECK_URL)
    gates.append(Gate("SIM_HOST_ONLY", "PASS" if all(h.startswith(SIM_PREFIX) for h in hosts)
                      else "FAIL", "all broker URLs are under the Saxo SIM gateway"))
    try:
        SaxoSimSubmitTransport().submit({
            "AccountKey": "offline-check", "Uic": submission.SOFI_UIC, "AssetType": "Stock",
            "BuySell": "Buy", "Amount": 1, "OrderType": "Market",
            "OrderDuration": {"DurationType": "DayOrder"}, "ExternalReference": "offline-check",
        })
        transport = Gate("SUBMIT_TRANSPORT_DEFAULT_OFF", "FAIL", "default transport attempted a POST")
    except RuntimeError as exc:
        transport = Gate("SUBMIT_TRANSPORT_DEFAULT_OFF",
                         "PASS" if "disabled" in str(exc) else "FAIL", "default transport refuses")
    gates.append(transport)

    class _SelfAttesting:
        def attest(self, material: str) -> str:
            return material

        def verify(self, attestation: str, material: str, principal: str) -> bool:
            return True

    try:
        submission._require_verify_only(_SelfAttesting())
        gates.append(Gate("SELF_APPROVAL_REJECTED", "FAIL", "self-attesting verifier accepted"))
    except submission.SubmissionBlocked:
        gates.append(Gate("SELF_APPROVAL_REJECTED", "PASS",
                          "a verifier able to attest cannot authorize"))
    forged = saxo_precheck.PrecheckEvidence(
        "Ok", "broker_precheck_validated", Decimal("1"), "EUR", Decimal("1"), "USD",
        Decimal("1"), "EUR", Decimal("1"), "x", "y", datetime.now(timezone.utc), "a",
        submission.SOFI_UIC, "Buy", 1, "Market", "DayOrder", transport_seal="forged")
    gates.append(Gate("HAND_BUILT_PRECHECK_REJECTED",
                      "FAIL" if forged.is_transport_sealed() else "PASS",
                      "only the SIM precheck transport can seal evidence"))
    gates.append(Gate("TRUSTED_MARKET_VERIFIER_REGISTRY",
                      "PASS" if submission.TRUSTED_MARKET_VERIFIER_TYPES else "MISSING",
                      "registered: " + ", ".join(t.__name__ for t in
                                                 submission.TRUSTED_MARKET_VERIFIER_TYPES)
                      if submission.TRUSTED_MARKET_VERIFIER_TYPES
                      else "no authenticated quote/FX verifier is registered yet (Stage 2)"))
    # Reporting only: SIM fills still post to the research ledgers until the
    # separate SIM books in docs/ADR-003-saxo-sim-accounting.md are built.
    gates.append(Gate("SIM_ACCOUNTING_SEPARATED", "MISSING",
                      "SIM fills would post to research ledgers; ADR-003 not implemented"))
    gates.append(Gate("SIM_SUBMISSION_RELEASE",
                      "FAIL" if submission.SIM_SUBMISSION_RELEASED else "DISABLED",
                      "no approved release; submission refuses before any POST"))
    return gates


def _approval_verified(request: submission.SimOrderRequest,
                       authorization: submission.ExecutionAuthorization,
                       verifier: SshSignatureApprovalVerifier, current: datetime) -> str | None:
    """Return None when the signature independently verifies, else the reason."""
    bound = (authorization.request_sha256 == request.digest()
             and authorization.broker_payload_sha256 == request.broker_payload_digest()
             and authorization.risk_evidence_sha256 == request.risk_evidence_sha256
             and authorization.order_key == request.order_key
             and authorization.requested_by == request.requested_by
             and authorization.account_id == request.account_id
             and authorization.portfolio_id == request.portfolio_id
             and (authorization.ticker, authorization.uic, authorization.side,
                  authorization.quantity, authorization.order_type)
             == (request.ticker, request.uic, "Buy", request.quantity, "Market"))
    if not bound:
        return "authorization fields are not bound to this exact order"
    if authorization.issued_by == request.requested_by:
        return "the requesting principal cannot approve its own order"
    if authorization.expires_at.tzinfo is None:
        return "authorization expiry has no timezone"
    expiry = authorization.expires_at.astimezone(timezone.utc)
    if not current < expiry <= current + submission.MAX_APPROVAL_LIFETIME:
        return "authorization is expired or outside the allowed window"
    material = submission.approval_material(
        request, authorization_id=authorization.authorization_id,
        approver=authorization.issued_by, expires_at=expiry)
    if not verifier.verify(authorization.attestation, material, authorization.issued_by):
        return "operator signature does not verify against allowed_signers"
    return None


def _market_fresh(evidence: ExecutionEvidence, current: datetime) -> bool:
    stamps = (evidence.observed_at, evidence.quote.market_timestamp,
              evidence.quote.ingestion_timestamp, evidence.fx.observed_at, evidence.fx.ingestion_at)
    return all(timedelta(0) <= current - stamp.astimezone(timezone.utc) <= MARKET_MAX_AGE
               for stamp in stamps)


def evaluate(*, request: submission.SimOrderRequest | None = None,
             precheck: saxo_precheck.PrecheckEvidence | None = None,
             evidence: ExecutionEvidence | None = None,
             market_verifier: MarketEvidenceVerifier | None = None,
             authorization: submission.ExecutionAuthorization | None = None,
             allowed_signers: Path | None = None, ssh_keygen: str | None = None,
             now: datetime | None = None) -> tuple[list[Gate], str]:
    """Each external gate re-verifies evidence; matching dataclass values are not enough."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    gates = _code_gates()
    prepared = request is not None and request.is_prepared()
    fresh = (request is not None and prepared
             and timedelta(0) <= current - request.prepared_at <= submission.MAX_REQUEST_AGE)
    if request is None:
        request_reason = "needs a separately approved authenticated read-only run"
    elif not prepared:
        request_reason = "request was not produced by prepare_sofi_request (hand-built or altered)"
    elif not fresh:
        request_reason = "prepared request is stale"
    else:
        request_reason = ""

    precheck_ok = (fresh and request is not None and precheck is not None
                   and precheck.is_transport_sealed()
                   and precheck.response_sha256 == request.precheck_sha256
                   and precheck.account_id == request.account_id
                   and precheck.uic == request.uic == submission.SOFI_UIC)
    precheck_reason = request_reason or ("" if precheck_ok else
                                         "no sealed SIM precheck matching this request")
    gates.append(Gate("AUTHENTICATED_SIM_ACCOUNT_AND_INSTRUMENT",
                      "PASS" if precheck_ok else "MISSING",
                      "authenticated scope and sealed SOFI precheck bound to the request"
                      if precheck_ok else precheck_reason))

    if fresh and request is not None and evidence is not None:
        if market_verifier is None or not submission.trusted_market_verifier(market_verifier):
            market_reason = "no registered market-data verifier type"
        elif evidence_digest(evidence) != request.evidence_sha256:
            market_reason = "evidence differs from the evidence the request was built from"
        elif not _market_fresh(evidence, current):
            market_reason = "quote or FX evidence is stale or future-dated"
        elif not market_verifier.verify(evidence):
            market_reason = "registered market-data verifier rejected the evidence"
        else:
            market_reason = ""
    else:
        market_reason = request_reason or "no quote/FX evidence supplied for re-verification"
    for name in ("CURRENT_SOFI_QUOTE_PROVENANCE", "CURRENT_EURUSD_FX_PROVENANCE"):
        gates.append(Gate(name, "MISSING" if market_reason else "PASS",
                          market_reason or "re-verified by a registered verifier type"))

    gates.append(Gate("BROKER_PRECHECK_AND_ACCOUNT_CURRENCY", "PASS" if precheck_ok else "MISSING",
                      "sealed EUR-account precheck for USD instrument" if precheck_ok
                      else precheck_reason))
    payload_ok = False
    if fresh and request is not None:
        try:
            SaxoSimSubmitTransport.validate_payload(request.payload())
            payload_ok = True
        except ValueError:
            payload_ok = False
    gates.append(Gate("EXACT_ORDER_PAYLOAD", "PASS" if payload_ok else "MISSING",
                      "payload matches the one-share SOFI SIM contract" if payload_ok
                      else request_reason or "payload does not match the approved contract"))

    verifier: SshSignatureApprovalVerifier | None = None
    verifier_reason = "operator must provide an allowed_signers file"
    if allowed_signers is not None:
        try:
            verifier = SshSignatureApprovalVerifier(allowed_signers, ssh_keygen=ssh_keygen)
        except ValueError as exc:
            verifier_reason = str(exc)
    gates.append(Gate("OPERATOR_VERIFIER_CONFIGURED", "PASS" if verifier else "MISSING",
                      "OpenSSH verifier built from operator public keys" if verifier
                      else verifier_reason))
    approval_reason: str | None
    if verifier is None:
        approval_reason = "no operator verifier configured"
    elif authorization is None:
        approval_reason = "no operator-signed approval supplied"
    elif not fresh or request is None:
        approval_reason = request_reason
    else:
        approval_reason = _approval_verified(request, authorization, verifier, current)
    gates.append(Gate("INDEPENDENT_OPERATOR_APPROVAL", "MISSING" if approval_reason else "PASS",
                      approval_reason or "operator signature independently re-verified"))
    gates.append(Gate("POST_SUBMISSION_FILL_RECONCILIATION", "NOT_APPLICABLE",
                      "fills can only be reconciled after an approved SIM order exists"))
    blocking = [g for g in gates if g.status not in {"PASS", "NOT_APPLICABLE"}]
    return gates, "GO" if not blocking else "NO-GO"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SideDeck P4 offline pre-execution check")
    parser.add_argument("--offline", action="store_true", required=True)
    parser.add_argument("--allowed-signers", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None, help="write the report here")
    args = parser.parse_args(argv)
    gates, decision = evaluate(allowed_signers=args.allowed_signers)
    code_ok = all(g.status != "FAIL" for g in gates)
    print(f"P4_OFFLINE_CHECK={'PASS' if code_ok else 'FAIL'}")
    for gate in gates:
        print(f"{gate.name}={gate.status}")
    print("BROKER_REQUESTS_MADE=0")
    print(f"P4_DECISION={decision}")
    if args.json is not None:
        args.json.write_text(json.dumps({
            "generated_at": datetime.now(timezone.utc).isoformat(), "mode": "offline",
            "broker_requests_made": 0, "decision": decision,
            "gates": [asdict(g) for g in gates],
        }, indent=2), encoding="utf-8")
    return 0 if code_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
