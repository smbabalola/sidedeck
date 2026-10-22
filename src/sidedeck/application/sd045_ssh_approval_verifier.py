"""SD-045 real signature verifier for paper-order approvals (OpenSSH signatures).

Plugs into ``ApprovalKillSwitch(path, verify_signature)``. The owner signs the
SD-033 intent digest with their own SSH key; SideDeck holds only the public key
in an OpenSSH ``allowed_signers`` file and verifies with ``ssh-keygen -Y verify``.
No private key, secret or new dependency is involved.

Owner signing (outside SideDeck), for a digest printed by the approval request:

    printf %s <digest> | ssh-keygen -Y sign -f ~/.ssh/id_ed25519 -n sidedeck-paper-approval

The approval's ``public_key`` field carries the signer *principal* named in
``allowed_signers``. Any failure (wrong key, principal, namespace, digest,
tampered or oversized signature, missing tool, timeout) verifies as ``False``.
Verification grants nothing: execution release remains ``NO_GO``.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

NAMESPACE = "sidedeck-paper-approval"
MAX_SIGNATURE_BYTES = 8192
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_PRINCIPAL = re.compile(r"^[A-Za-z0-9._@+-]{1,128}$")
_ARMOR = ("-----BEGIN SSH SIGNATURE-----", "-----END SSH SIGNATURE-----")


class SshSignatureVerifier:
    def __init__(self, allowed_signers_path: str, principal: str, *,
                 ssh_keygen: str = "ssh-keygen", timeout_seconds: float = 10.0,
                 namespace: str = NAMESPACE) -> None:
        target = Path(allowed_signers_path)
        if not target.is_file() or target.is_symlink():
            raise ValueError("allowed_signers must be a regular file")
        if not _PRINCIPAL.fullmatch(principal):
            raise ValueError("principal must be a simple identifier")
        if not _PRINCIPAL.fullmatch(namespace):
            raise ValueError("namespace must be a simple identifier")
        resolved = shutil.which(ssh_keygen)
        if resolved is None:
            raise ValueError("ssh-keygen is not available")
        if Path(resolved).resolve().parent == Path(os.getcwd()).resolve():
            # Windows searches the current directory first; a planted binary must not verify.
            raise ValueError("ssh-keygen must not be resolved from the current directory")
        self._allowed = str(target.resolve())
        self._principal = principal
        self._tool = resolved
        self._timeout = timeout_seconds
        self.namespace = namespace

    def __call__(self, public_key: str, digest: str, signature: str) -> bool:
        if public_key != self._principal or not _DIGEST.fullmatch(digest):
            return False
        text = signature.strip()
        if (not text.isascii() or len(text) > MAX_SIGNATURE_BYTES or not text.startswith(_ARMOR[0])
                or not text.endswith(_ARMOR[1])):
            return False
        with tempfile.TemporaryDirectory() as workdir:
            sig_path = Path(workdir) / "approval.sig"
            sig_path.write_text(text + "\n", encoding="ascii", errors="strict")
            try:
                result = subprocess.run(
                    [self._tool, "-Y", "verify", "-f", self._allowed, "-I", self._principal,
                     "-n", self.namespace, "-s", str(sig_path)],
                    input=digest.encode("ascii"), capture_output=True,
                    timeout=self._timeout, check=False)
            except (OSError, subprocess.SubprocessError):
                return False
        return result.returncode == 0
