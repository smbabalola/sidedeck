"""Real OpenSSH signature verification with a throwaway, test-only operator key."""
import shutil
import subprocess

import pytest

from sidedeck.application.saxo_sim_submission import SubmissionBlocked, _require_verify_only
from sidedeck.infrastructure.saxo_operator_approval import (
    APPROVAL_NAMESPACE, SshSignatureApprovalVerifier,
)

SSH_KEYGEN = shutil.which("ssh-keygen")
pytestmark = pytest.mark.skipif(SSH_KEYGEN is None, reason="ssh-keygen unavailable")


def operator_setup(tmp_path, principal="operator"):
    key = tmp_path / "operator_key"
    subprocess.run([SSH_KEYGEN, "-q", "-t", "ed25519", "-N", "", "-C", principal, "-f", str(key)],
                   check=True, capture_output=True)
    public = (tmp_path / "operator_key.pub").read_text(encoding="ascii").strip()
    signers = tmp_path / "allowed_signers"
    signers.write_text(f'{principal} namespaces="{APPROVAL_NAMESPACE}" {public}\n', encoding="ascii")
    return key, signers


def operator_signs(tmp_path, key, material, namespace=APPROVAL_NAMESPACE):
    """The human's step, performed outside SideDeck with the private key."""
    message = tmp_path / "material.txt"
    message.write_bytes(material.encode("utf-8"))
    subprocess.run([SSH_KEYGEN, "-q", "-Y", "sign", "-f", str(key), "-n", namespace, str(message)],
                   check=True, capture_output=True)
    return (tmp_path / "material.txt.sig").read_text(encoding="ascii")


def test_operator_signature_verifies_only_for_exact_material_and_principal(tmp_path):
    key, signers = operator_setup(tmp_path)
    verifier = SshSignatureApprovalVerifier(signers, ssh_keygen=SSH_KEYGEN)
    material = '{"order_key":"sofi-1","quantity":1}'
    signature = operator_signs(tmp_path, key, material)
    assert verifier.verify(signature, material, "operator")
    assert not verifier.verify(signature, material.replace("1}", "2}"), "operator")
    assert not verifier.verify(signature, material, "someone-else")
    assert not verifier.verify("not a signature", material, "operator")
    assert not verifier.verify(signature, material, "bad principal; rm")


def test_signature_from_another_namespace_is_rejected(tmp_path):
    key, signers = operator_setup(tmp_path)
    verifier = SshSignatureApprovalVerifier(signers, ssh_keygen=SSH_KEYGEN)
    material = '{"order_key":"sofi-1"}'
    git_signature = operator_signs(tmp_path, key, material, namespace="git")
    assert not verifier.verify(git_signature, material, "operator")


def test_ssh_verifier_is_verify_only_and_needs_operator_keys(tmp_path):
    _, signers = operator_setup(tmp_path)
    verifier = SshSignatureApprovalVerifier(signers, ssh_keygen=SSH_KEYGEN)
    assert _require_verify_only(verifier) is verifier
    with pytest.raises(ValueError, match="allowed_signers"):
        SshSignatureApprovalVerifier(tmp_path / "missing", ssh_keygen=SSH_KEYGEN)


def test_self_attesting_wrapper_is_still_rejected(tmp_path):
    _, signers = operator_setup(tmp_path)

    class Wrapped(SshSignatureApprovalVerifier):
        def sign(self, material):
            return material

    with pytest.raises(SubmissionBlocked, match="cannot authorize its own"):
        _require_verify_only(Wrapped(signers, ssh_keygen=SSH_KEYGEN))
