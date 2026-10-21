"""SD-045 OpenSSH approval signatures. Uses throwaway test keys in tmp_path only."""
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from sidedeck.application.sd033_approval_killswitch import (
    ApprovalError, ApprovalKillSwitch, intent_digest,
)
from sidedeck.application.sd045_ssh_approval_verifier import NAMESPACE, SshSignatureVerifier

pytestmark = pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="ssh-keygen missing")


def keypair(tmp_path, name):
    key = tmp_path / name
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(key)],
                   check=True, capture_output=True)
    return key


def sign(key, message, namespace=NAMESPACE):
    result = subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", namespace],
                            input=message.encode(), capture_output=True, check=True)
    return result.stdout.decode()


@pytest.fixture
def setup(tmp_path):
    owner = keypair(tmp_path, "owner")
    other = keypair(tmp_path, "other")
    signers = tmp_path / "allowed_signers"
    signers.write_text("owner@sidedeck " + (tmp_path / "owner.pub").read_text().strip() + "\n")
    verifier = SshSignatureVerifier(str(signers), "owner@sidedeck")
    return verifier, owner, other


DIGEST = intent_digest("intent-1", "etoro-demo:open:scope")


def test_valid_owner_signature_verifies(setup):
    verifier, owner, _ = setup
    assert verifier("owner@sidedeck", DIGEST, sign(owner, DIGEST))


@pytest.mark.parametrize("case", ["other_key", "other_digest", "wrong_namespace",
                                  "wrong_principal", "tampered", "garbage", "non_hex"])
def test_invalid_signatures_rejected(setup, case):
    verifier, owner, other = setup
    principal, digest, signature = "owner@sidedeck", DIGEST, sign(owner, DIGEST)
    if case == "other_key":
        signature = sign(other, DIGEST)
    elif case == "other_digest":
        digest = intent_digest("intent-2", "etoro-demo:open:scope")
    elif case == "wrong_namespace":
        signature = sign(owner, DIGEST, namespace="something-else")
    elif case == "wrong_principal":
        principal = "attacker@sidedeck"
    elif case == "tampered":
        lines = signature.splitlines()
        lines[2] = lines[2][:-4] + ("AAAA" if not lines[2].endswith("AAAA") else "BBBB")
        signature = "\n".join(lines)
    elif case == "garbage":
        signature = "-----BEGIN SSH SIGNATURE-----\nnot-base64\n-----END SSH SIGNATURE-----"
    elif case == "non_hex":
        digest = "Z" * 64
    assert verifier(principal, digest, signature) is False


def test_oversized_or_non_ascii_signature_rejected(setup):
    verifier, owner, _ = setup
    assert verifier("owner@sidedeck", DIGEST, "-----BEGIN SSH SIGNATURE-----\n" + "A" * 9000
                    + "\n-----END SSH SIGNATURE-----") is False
    assert verifier("owner@sidedeck", DIGEST, sign(owner, DIGEST) + "é") is False


def test_constructor_validates_inputs(tmp_path, setup):
    with pytest.raises(ValueError, match="regular file"):
        SshSignatureVerifier(str(tmp_path / "missing"), "owner@sidedeck")
    with pytest.raises(ValueError, match="principal"):
        SshSignatureVerifier(str(tmp_path / "allowed_signers"), "bad principal\n")
    with pytest.raises(ValueError, match="ssh-keygen"):
        SshSignatureVerifier(str(tmp_path / "allowed_signers"), "owner@sidedeck",
                             ssh_keygen="definitely-not-ssh-keygen")


def test_integrates_with_approval_store(tmp_path, setup):
    verifier, owner, other = setup
    controls = ApprovalKillSwitch(str(tmp_path / "controls.sqlite3"), verifier)
    scope = "etoro-demo:open:scope"
    expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
    with pytest.raises(ApprovalError, match="signature"):
        controls.approve("a0", "intent-1", scope, "sidedeck", "owner", "owner@sidedeck",
                         sign(other, DIGEST), expiry)
    controls.approve("a1", "intent-1", scope, "sidedeck", "owner", "owner@sidedeck",
                     sign(owner, DIGEST), expiry)
    assert controls.is_approved("intent-1", scope)
    assert not controls.is_approved("intent-1", scope + ":changed")
    controls.close()
