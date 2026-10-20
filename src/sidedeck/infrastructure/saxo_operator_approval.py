"""Verify-only operator approval for a Saxo SIM order.

SideDeck holds operator *public* keys only (an OpenSSH ``allowed_signers``
file). The operator signs the exact approval material outside SideDeck with
their own private key::

    ssh-keygen -Y sign -f ~/.ssh/<operator_key> -n sidedeck-saxo-sim-approval material.txt

SideDeck cannot produce such a signature, so a process can never approve its
own request. This module exposes no attest/sign capability on purpose.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

APPROVAL_NAMESPACE = "sidedeck-saxo-sim-approval"
_PRINCIPAL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@-]{0,63}")
_SIG_BEGIN = "-----BEGIN SSH SIGNATURE-----"
_SIG_END = "-----END SSH SIGNATURE-----"
MAX_ATTESTATION_CHARS = 4096


def valid_principal(principal: object) -> bool:
    return isinstance(principal, str) and _PRINCIPAL.fullmatch(principal) is not None


class SshSignatureApprovalVerifier:
    """Checks an OpenSSH signature against operator-managed public keys."""

    def __init__(self, allowed_signers: str | Path, *, ssh_keygen: str | None = None,
                 timeout_seconds: float = 10.0) -> None:
        path = Path(allowed_signers)
        if not path.is_file():
            raise ValueError("operator allowed_signers file is missing")
        executable = ssh_keygen or shutil.which("ssh-keygen")
        if not executable:
            raise ValueError("ssh-keygen is unavailable; operator approval cannot be verified")
        if not 0 < timeout_seconds <= 30:
            raise ValueError("invalid verifier timeout")
        self._allowed_signers = path
        self._ssh_keygen = executable
        self._timeout = timeout_seconds

    def verify(self, attestation: str, material: str, principal: str) -> bool:
        if not valid_principal(principal):
            return False
        if (not isinstance(attestation, str) or len(attestation) > MAX_ATTESTATION_CHARS
                or not attestation.strip().startswith(_SIG_BEGIN)
                or not attestation.strip().endswith(_SIG_END)):
            return False
        if not isinstance(material, str) or not material:
            return False
        with tempfile.TemporaryDirectory(prefix="sidedeck-approval-") as work:
            signature = Path(work) / "approval.sig"
            signature.write_text(attestation.strip() + "\n", encoding="ascii")
            try:
                completed = subprocess.run(
                    [self._ssh_keygen, "-Y", "verify", "-f", str(self._allowed_signers),
                     "-I", principal, "-n", APPROVAL_NAMESPACE, "-s", str(signature)],
                    input=material.encode("utf-8"), capture_output=True,
                    timeout=self._timeout, check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                return False
        return completed.returncode == 0
