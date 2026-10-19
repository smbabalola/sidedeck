"""P4 GO/NO-GO evaluator; never contacts Saxo or submits an order.

Code-safety gates are evaluated by exercising the real guards. External gates
(authenticated account, quote, FX, precheck, operator approval) can only pass
from a ``SimOrderRequest`` / ``ExecutionAuthorization`` that went through the
production checks; the offline CLI has neither, so it always reports NO-GO.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sidedeck.application import saxo_sim_submission as submission
from sidedeck.infrastructure import saxo_precheck, saxo_sim
from sidedeck.infrastructure.saxo_submit_transport import SaxoSimSubmitTransport

SIM_PREFIX = "https://gateway.saxobank.com/sim/openapi"


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
    gates.append(Gate("SIM_SUBMISSION_RELEASE",
                      "FAIL" if submission.SIM_SUBMISSION_RELEASED else "DISABLED",
                      "no approved release; submission refuses before any POST"))
    return gates


def evaluate(*, request: submission.SimOrderRequest | None = None,
             authorization: submission.ExecutionAuthorization | None = None,
             allowed_signers: Path | None = None,
             now: datetime | None = None) -> tuple[list[Gate], str]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    gates = _code_gates()
    fresh = (request is not None
             and current - request.prepared_at <= submission.MAX_REQUEST_AGE
             and request.prepared_at <= current)
    pre = "PASS" if fresh else "MISSING"
    why = ("prepared through production checks" if fresh
           else "needs a separately approved authenticated read-only run")
    for name in ("AUTHENTICATED_SIM_ACCOUNT_AND_INSTRUMENT", "CURRENT_SOFI_QUOTE_PROVENANCE",
                 "CURRENT_EURUSD_FX_PROVENANCE", "BROKER_PRECHECK_AND_ACCOUNT_CURRENCY",
                 "EXACT_ORDER_PAYLOAD"):
        gates.append(Gate(name, pre, why))
    signers = allowed_signers is not None and allowed_signers.is_file()
    gates.append(Gate("OPERATOR_VERIFIER_CONFIGURED", "PASS" if signers else "MISSING",
                      "operator public keys (allowed_signers) present" if signers
                      else "operator must provide an allowed_signers file"))
    approved = (fresh and authorization is not None and request is not None
                and authorization.request_sha256 == request.digest()
                and authorization.expires_at > current)
    gates.append(Gate("INDEPENDENT_OPERATOR_APPROVAL", "PASS" if approved else "MISSING",
                      "signed approval bound to this order" if approved
                      else "no operator-signed approval for a current order"))
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
