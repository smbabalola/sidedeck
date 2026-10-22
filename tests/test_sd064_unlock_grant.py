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
    ledger = open_ledger(tmp_path)
    yield UnlockAuthority(verifier=grant_verifier(keys), principal=PRINCIPAL,
                          ledger=ledger), ledger
    ledger.close()


def open_ledger(tmp_path):
    return GrantLedger(str(tmp_path / "grants.sqlite3"),
                       anchor_path=str(tmp_path / "anchor" / "grant-anchor.json"))


def grant_verifier(keys):
    return SshSignatureVerifier(str(keys / "allowed_signers"), PRINCIPAL,
                                namespace=GRANT_NAMESPACE)


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
    assert ledger.verify_chain() is False         # truncation no longer matches the anchor
    assert ledger.revoked(doc["grant_id"])        # and the anchor still remembers it
    with pytest.raises(GrantRefused, match="integrity|revoked"):
        auth.check(document=doc, signature=signed(keys, doc), subject_digest=SUBJECT, now=NOW)


def test_edited_ledger_row_fails_closed(keys, authority, tmp_path):
    auth, ledger = authority
    doc = document()
    auth.check(document=doc, signature=signed(keys, doc), subject_digest=SUBJECT, now=NOW)
    raw = sqlite3.connect(tmp_path / "grants.sqlite3")
    raw.execute("UPDATE unlock_grant_events SET detail='edited' WHERE seq=1")
    raw.commit()
    raw.close()
    assert ledger.verify_chain() is False
    with pytest.raises(GrantRefused, match="integrity"):
        auth.check(document=doc, signature=signed(keys, doc), subject_digest=SUBJECT, now=NOW)


def test_deleted_or_replaced_anchor_fails_closed(keys, authority, tmp_path):
    auth, ledger = authority
    doc = document()
    auth.check(document=doc, signature=signed(keys, doc), subject_digest=SUBJECT, now=NOW)
    anchor = tmp_path / "anchor" / "grant-anchor.json"
    anchor.unlink()
    assert ledger.verify_chain() is False
    with pytest.raises(GrantRefused, match="integrity"):
        auth.check(document=doc, signature=signed(keys, doc), subject_digest=SUBJECT, now=NOW)
    anchor.write_text("not json", encoding="utf-8")
    assert ledger.verify_chain() is False


def test_deleted_ledger_with_surviving_anchor_fails_closed(keys, tmp_path):
    ledger = open_ledger(tmp_path)
    auth = UnlockAuthority(verifier=grant_verifier(keys), principal=PRINCIPAL, ledger=ledger)
    doc = document()
    auth.check(document=doc, signature=signed(keys, doc), subject_digest=SUBJECT, now=NOW)
    auth.revoke(doc["grant_id"], "stop")
    ledger.close()
    (tmp_path / "grants.sqlite3").unlink()                 # attacker wipes the ledger
    fresh = open_ledger(tmp_path)
    try:
        assert fresh.verify_chain() is False and fresh.revoked(doc["grant_id"])
        again = UnlockAuthority(verifier=grant_verifier(keys), principal=PRINCIPAL, ledger=fresh)
        with pytest.raises(GrantRefused):
            again.check(document=doc, signature=signed(keys, doc), subject_digest=SUBJECT,
                        now=NOW)
    finally:
        fresh.close()


def test_request_caps_persist_across_restart_and_writes_are_single_use(keys, tmp_path):
    doc = document()
    signature = signed(keys, doc)
    ledger = open_ledger(tmp_path)
    auth = UnlockAuthority(verifier=grant_verifier(keys), principal=PRINCIPAL, ledger=ledger)
    request = dict(document=doc, signature=signature, subject_digest=SUBJECT, now=NOW)
    auth.authorize_request(write=True, reference_id="open-ref", **request)
    with pytest.raises(GrantRefused, match="replay"):
        auth.authorize_request(write=True, reference_id="open-ref", **request)
    for n in range(5):
        auth.authorize_request(write=False, reference_id=f"read-{n}", **request)
    ledger.close()
    restarted = open_ledger(tmp_path)                       # process restart
    try:
        auth = UnlockAuthority(verifier=grant_verifier(keys), principal=PRINCIPAL,
                               ledger=restarted)
        auth.authorize_request(write=True, reference_id="close-ref", **request)
        with pytest.raises(GrantRefused, match="write cap"):
            auth.authorize_request(write=True, reference_id="third-write", **request)
        for n in range(5, 10):                                    # 2 writes + 10 reads = 12
            auth.authorize_request(write=False, reference_id=f"read-{n}", **request)
        with pytest.raises(GrantRefused, match="request cap"):    # the 13th is refused
            auth.authorize_request(write=False, reference_id="read-x", **request)
        uses = [e for _, e, _ in restarted.events(doc["grant_id"]) if e.startswith("USE_")]
        assert len(uses) == 12 and uses.count("USE_WRITE") == 2
        assert restarted.verify_chain()
    finally:
        restarted.close()


def test_expired_or_revoked_grant_authorizes_no_request(keys, authority):
    auth, ledger = authority
    doc = document()
    signature = signed(keys, doc)
    late = datetime(2026, 10, 23, 15, 30, tzinfo=timezone.utc)
    with pytest.raises(GrantRefused, match="window"):
        auth.authorize_request(document=doc, signature=signature, subject_digest=SUBJECT,
                               write=True, reference_id="r", now=late)
    auth.revoke(doc["grant_id"], "stop")
    with pytest.raises(GrantRefused, match="revoked"):
        auth.authorize_request(document=doc, signature=signature, subject_digest=SUBJECT,
                               write=False, reference_id="r2", now=NOW)
    assert not [e for _, e, _ in ledger.events(doc["grant_id"]) if e.startswith("USE_")]


def test_verifier_must_use_the_grant_namespace(keys, tmp_path):
    ledger = open_ledger(tmp_path)
    try:
        with pytest.raises(GrantRefused, match="namespace"):
            UnlockAuthority(verifier=SshSignatureVerifier(str(keys / "allowed_signers"),
                                                          PRINCIPAL), principal=PRINCIPAL,
                            ledger=ledger)
    finally:
        ledger.close()
    with pytest.raises(GrantRefused, match="durable"):
        GrantLedger(":memory:", anchor_path=str(tmp_path / "a.json"))
    with pytest.raises(GrantRefused, match="separate anchor"):
        GrantLedger(str(tmp_path / "x.sqlite3"), anchor_path=str(tmp_path / "x.sqlite3"))


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


def test_prepared_grant_round_trips_through_owner_signature(keys, authority, tmp_path):
    import json

    from sidedeck.application.sd064_unlock_grant import prepare_grant
    auth, _ = authority
    out = prepare_grant(tmp_path / "grants", kind="pilot_release", subject_digest=SUBJECT,
                        not_before="2026-10-23T14:00:00+00:00",
                        expires_at="2026-10-23T15:30:00+00:00", max_requests=12, max_writes=2,
                        purpose="SD-053 MSFT Demo pilot")
    digest_file = tmp_path / "grants" / f"{out['grant_id']}.digest"
    assert digest_file.read_bytes() == out["digest"].encode("ascii")
    assert f"-ceq '{out['digest']}'" in out["sign_in_powershell"]
    assert GRANT_NAMESPACE in out["sign_in_powershell"]
    doc = json.loads((tmp_path / "grants" / f"{out['grant_id']}.json").read_text())
    signature = sign(keys, digest_file.read_text())
    assert auth.check(document=doc, signature=signature, subject_digest=SUBJECT,
                      now=NOW).grant_id == out["grant_id"]


def test_prepare_refuses_out_of_scope_grants(tmp_path):
    from sidedeck.application.sd064_unlock_grant import prepare_grant
    with pytest.raises(GrantRefused, match="window"):
        prepare_grant(tmp_path, kind="pilot_release", subject_digest=SUBJECT,
                      not_before="2026-10-23T14:00:00+00:00",
                      expires_at="2026-10-24T14:00:00+00:00", max_requests=12, max_writes=2,
                      purpose="too long")
    with pytest.raises(GrantRefused, match="max_writes"):
        prepare_grant(tmp_path, kind="pilot_release", subject_digest=SUBJECT,
                      not_before="2026-10-23T14:00:00+00:00",
                      expires_at="2026-10-23T15:00:00+00:00", max_requests=12, max_writes=5,
                      purpose="too many writes")
    assert not list(tmp_path.glob("*.json"))
