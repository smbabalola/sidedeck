"""SD-064 owner-signed unlock grants: offline, real ssh-keygen signatures, test keys only."""
import hashlib
import shutil
import sqlite3
import subprocess
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from sidedeck.application.sd045_ssh_approval_verifier import SshSignatureVerifier
from sidedeck.application.sd064_unlock_grant import (
    GRANT_NAMESPACE, GrantLedger, GrantRefused, UnlockAuthority, UnlockGrant,
    require_pinned_signer,
)

pytestmark = pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="ssh-keygen missing")
PRINCIPAL = "owner@sidedeck"
SUBJECT = "71e111b3a8806dc9b8e59d96ce1ef6e6a0b64dc2b00363465244acccaad09a62"
NOW = datetime(2026, 10, 23, 14, 30, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def keys(tmp_path_factory):
    root = tmp_path_factory.mktemp("keys")
    for name in ("owner", "other"):
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f",
                        str(root / name)], check=True, capture_output=True)
    (root / "allowed_signers").write_text(
        f"{PRINCIPAL} " + (root / "owner.pub").read_text().strip() + "\n")
    return root


def sign(root, digest, namespace=GRANT_NAMESPACE, key="owner"):
    return subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(root / key), "-n", namespace],
                          input=digest.encode(), capture_output=True, check=True).stdout.decode()


def document(**changes):
    doc = {"schema": "sidedeck-unlock-grant/1", "grant_id": str(uuid.uuid4()),
           "kind": "pilot_release", "broker": "etoro-demo", "subject_digest": SUBJECT,
           "not_before": "2026-10-23T14:00:00+00:00", "expires_at": "2026-10-23T15:30:00+00:00",
           "max_requests": 12, "max_writes": 2, "issued_by": PRINCIPAL,
           "purpose": "SD-053 MSFT Demo pilot"}
    doc.update(changes)
    return doc


@pytest.fixture
def authority(keys, tmp_path):
    ledger = GrantLedger(str(tmp_path / "grants.sqlite3"))
    verifier = SshSignatureVerifier(str(keys / "allowed_signers"), PRINCIPAL,
                                    namespace=GRANT_NAMESPACE)
    yield UnlockAuthority(verifier=verifier, principal=PRINCIPAL, ledger=ledger), ledger
    ledger.close()


def signed(keys, doc, **kw):
    return sign(keys, UnlockGrant.from_document(doc).digest(), **kw)


def test_valid_grant_unlocks_only_its_subject_inside_its_window(keys, authority):
    auth, ledger = authority
    doc = document()
    grant = auth.check(document=doc, signature=signed(keys, doc), subject_digest=SUBJECT,
                       now=NOW)
    assert grant.max_writes == 2 and grant.kind == "pilot_release"
    with pytest.raises(GrantRefused, match="subject"):
        auth.check(document=doc, signature=signed(keys, doc), subject_digest="0" * 64, now=NOW)
    for moment in (NOW - timedelta(hours=1), datetime(2026, 10, 23, 15, 30,
                                                     tzinfo=timezone.utc)):
        with pytest.raises(GrantRefused, match="window"):
            auth.check(document=doc, signature=signed(keys, doc), subject_digest=SUBJECT,
                       now=moment)
    events = [event for _, event, _ in ledger.events(doc["grant_id"])]
    assert events[0] == "ACTIVE_CHECK_PASSED" and events.count("REFUSED") == 3
    assert ledger.verify_chain()


@pytest.mark.parametrize("key,namespace", [("other", GRANT_NAMESPACE),
                                           ("owner", "sidedeck-etoro-pilot-release"),
                                           ("owner", "sidedeck-etoro-pilot-approval")])
def test_wrong_key_or_namespace_is_refused(keys, authority, key, namespace):
    auth, _ = authority
    doc = document()
    with pytest.raises(GrantRefused, match="signature"):
        auth.check(document=doc, signature=signed(keys, doc, key=key, namespace=namespace),
                   subject_digest=SUBJECT, now=NOW)


@pytest.mark.parametrize("field,value", [
    ("subject_digest", "1" * 64), ("expires_at", "2026-10-23T15:40:00+00:00"),
    ("max_writes", 1), ("purpose", "something else"),
])
def test_signature_binds_every_field(keys, authority, field, value):
    auth, _ = authority
    doc = document()
    signature = signed(keys, doc)
    with pytest.raises(GrantRefused):
        auth.check(document={**doc, field: value}, signature=signature,
                   subject_digest=doc["subject_digest"] if field != "subject_digest" else value,
                   now=NOW)


@pytest.mark.parametrize("changes,match", [
    ({"broker": "etoro-real"}, "Real"),
    ({"kind": "anything"}, "kind"),
    ({"subject_digest": "*"}, "digest"),
    ({"expires_at": "2026-10-23T23:00:00+00:00"}, "window"),
    ({"kind": "autonomous_policy", "expires_at": "2026-11-01T14:00:00+00:00"}, "window"),
    ({"max_requests": 13}, "max_requests"), ({"max_writes": 3}, "max_writes"),
    ({"max_writes": True}, "max_writes"), ({"not_before": "2026-10-23T14:00:00"}, "aware"),
    ({"grant_id": "not-a-uuid"}, "UUID"), ({"issued_by": "claude@sidedeck"}, "owner"),
    ({"extra": 1}, "exactly"),
])
def test_scope_and_self_authorization_rules(keys, authority, changes, match):
    auth, _ = authority
    doc = document(**changes)
    with pytest.raises(GrantRefused, match=match):
        auth.check(document=doc, signature="x", subject_digest=SUBJECT, now=NOW)


def test_autonomous_policy_grant_within_seven_days(keys, authority):
    auth, _ = authority
    doc = document(kind="autonomous_policy", expires_at="2026-10-30T14:00:00+00:00",
                   max_requests=500, max_writes=20)
    assert auth.check(document=doc, signature=signed(keys, doc), subject_digest=SUBJECT,
                      now=NOW).kind == "autonomous_policy"


def test_revocation_is_permanent(keys, authority):
    auth, ledger = authority
    doc = document()
    auth.check(document=doc, signature=signed(keys, doc), subject_digest=SUBJECT, now=NOW)
    auth.revoke(doc["grant_id"], "owner stopped the pilot")
    with pytest.raises(GrantRefused, match="revoked"):
        auth.check(document=doc, signature=signed(keys, doc), subject_digest=SUBJECT, now=NOW)


def test_tampered_ledger_fails_closed(keys, authority, tmp_path):
    auth, ledger = authority
    doc = document()
    auth.check(document=doc, signature=signed(keys, doc), subject_digest=SUBJECT, now=NOW)
    auth.revoke(doc["grant_id"], "stop")
    raw = sqlite3.connect(tmp_path / "grants.sqlite3")
    raw.execute("DELETE FROM unlock_grant_events WHERE event='REVOKED'")   # hide revocation
    raw.commit()
    raw.close()
    assert ledger.verify_chain() is True          # tail deletion keeps a valid prefix ...
    raw = sqlite3.connect(tmp_path / "grants.sqlite3")
    raw.execute("UPDATE unlock_grant_events SET detail='edited' WHERE seq=1")
    raw.commit()
    raw.close()
    assert ledger.verify_chain() is False         # ... but any edit is detected
    with pytest.raises(GrantRefused, match="integrity"):
        auth.check(document=doc, signature=signed(keys, doc), subject_digest=SUBJECT, now=NOW)


def test_verifier_must_use_the_grant_namespace(keys, tmp_path):
    ledger = GrantLedger(str(tmp_path / "g.sqlite3"))
    try:
        with pytest.raises(GrantRefused, match="namespace"):
            UnlockAuthority(verifier=SshSignatureVerifier(str(keys / "allowed_signers"),
                                                          PRINCIPAL), principal=PRINCIPAL,
                            ledger=ledger)
    finally:
        ledger.close()
    with pytest.raises(GrantRefused, match="durable"):
        GrantLedger(":memory:")


def test_pinned_signer_file(keys, tmp_path):
    blob = (keys / "owner.pub").read_text().split()[1]
    pin = hashlib.sha256(blob.encode("ascii")).hexdigest()
    require_pinned_signer(keys / "allowed_signers", PRINCIPAL, pin)
    other = (keys / "other.pub").read_text().split()
    extra = tmp_path / "signers"
    extra.write_text((keys / "allowed_signers").read_text()
                     + f"{PRINCIPAL} {other[0]} {other[1]}" + chr(10))
    for path, principal in ((extra, PRINCIPAL), (keys / "allowed_signers", "claude@sidedeck")):
        with pytest.raises(GrantRefused, match="pinned"):
            require_pinned_signer(path, principal, pin)
