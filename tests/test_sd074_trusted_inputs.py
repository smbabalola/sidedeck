"""SD-074 authenticated inputs, verified reconciliation, protective exits, incident report and
adversarial lifecycle tests for the (offline, unwired) autonomous Demo runtime."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from sidedeck.application import sd063_autonomous_demo_policy as sd063
from sidedeck.application.sd063_autonomous_demo_policy import (
    EntryProposal, PolicyRefused, Refusal, protective_subject,
)
from sidedeck.application.sd071_decision_engine import StrategyAdmission
from sidedeck.application.sd074_trusted_inputs import (
    AuthenticatedRuntime, InputRefused, InputVerifier, NonceStore, SourceRegistry, SourceSigner,
    TrustedSource,
)
from test_sd063_autonomous_demo_policy import AAPL, MSFT, NOW, _Env, _grant

UTC = timezone.utc
KEYS = {name: (name * 8).encode()[:40].ljust(40, b"k") for name in
        ("native", "agent", "quotes", "recon", "research")}
SOURCES = [TrustedSource("native-runner", "native_strategy_runner", KEYS["native"]),
           TrustedSource("ta-adapter", "agent_adapter", KEYS["agent"]),
           TrustedSource("etoro-demo-quotes", "broker_quotes", KEYS["quotes"]),
           TrustedSource("etoro-demo-recon", "broker_reconciliation", KEYS["recon"]),
           TrustedSource("research-pipeline", "research_pipeline", KEYS["research"])]
ADMISSIONS = (StrategyAdmission("sma_cross", "1.0.0", "SWING", "ADMITTED", "SD022.md", 45, True),)
LOOKUP = "d" * 64


class _Kit:
    def __init__(self, tmp: Path, env: _Env, **runtime_changes: object) -> None:
        self.env = env
        self.nonces = NonceStore(tmp / "nonces.sqlite3")
        self.verifier = InputVerifier(SourceRegistry(SOURCES), self.nonces, clock=env.clock)
        self.signers = {s.source_id: SourceSigner(s, env.clock) for s in SOURCES}
        if runtime_changes:
            env.rt = env.runtime(env.ledger, env.authority, **runtime_changes)
        self.art = AuthenticatedRuntime(env.rt, self.verifier)

    def native(self, cid: str = MSFT, horizon: int = 10, **changes: object):
        now = self.env.clock.now
        payload = {"source_kind": "NATIVE_STRATEGY", "canonical_id": cid, "track": "SWING",
                   "strategy_id": "sma_cross", "strategy_version": "1.0.0",
                   "horizon_min_days": 2, "horizon_max_days": horizon, "direction": "LONG",
                   "evidence": [{"kind": "backtest", "reference": "SD022.md",
                                 "sha256": "a" * 64}],
                   "generated_at": (now - timedelta(minutes=2)).isoformat(),
                   "data_cutoff": (now - timedelta(hours=1)).isoformat(),
                   "invalidation": ["close below SMA50"]}
        payload.update(changes)
        return self.signers["native-runner"].seal(payload)

    def research(self, cid: str = MSFT, atr: str = "10", **changes: object):
        payload = {"canonical_id": cid, "atr": atr, "sector": "Technology",
                   "correlations": {o: "0.1" for o in (MSFT, AAPL, "US:XNAS:NVDA",
                                                       "US:XNAS:AMZN") if o != cid},
                   "execution_eligible": True, "as_of": self.env.clock.now.isoformat()}
        payload.update(changes)
        return self.signers["research-pipeline"].seal(payload)

    def quote(self, cid: str = MSFT, bid: str = "499.9", ask: str = "500",
              signer: str = "etoro-demo-quotes"):
        return self.signers[signer].seal({"canonical_id": cid, "bid": bid, "ask": ask,
                                          "quote_time": self.env.clock.now.isoformat()})

    def fill(self, reference: str, outcome: str = "FILLED", units: str = "0.1990",
             price: str = "500", signer: str = "etoro-demo-recon", **changes: object):
        payload = {"reference": reference, "outcome": outcome, "units": units, "price": price,
                   "filled_at": self.env.clock.now.isoformat(), "broker_order_id": "demo-77",
                   "lookup_sha256": LOOKUP}
        payload.update(changes)
        return self.signers[signer].seal(payload)

    def entry(self, cid: str = MSFT, **changes: object):
        kwargs: dict[str, object] = dict(track="SWING", signals=[self.native(cid)],
                                         admissions=ADMISSIONS, research=self.research(cid),
                                         quote=self.quote(cid), marks=[])
        kwargs.update(changes)
        return self.art.propose_entry(**kwargs)  # type: ignore[arg-type]

    def open(self, cid: str = MSFT) -> EntryProposal:
        proposal = self.entry(cid)
        assert isinstance(proposal, EntryProposal), proposal
        self.art.resolve(self.fill(proposal.reference_id, units=str(proposal.units)))
        return proposal


@pytest.fixture
def kit(tmp_path: Path):
    env = _Env(tmp_path)
    k = _Kit(tmp_path, env)
    yield k
    k.nonces.close()
    env.ledger.close()


# --- registry and envelopes ------------------------------------------------------------------

def test_registry_rejects_weak_or_ambiguous_sources():
    with pytest.raises(InputRefused, match="32 bytes"):
        SourceRegistry([TrustedSource("q", "broker_quotes", b"short")])
    with pytest.raises(InputRefused, match="role"):
        SourceRegistry([TrustedSource("q", "operator", KEYS["quotes"])])
    with pytest.raises(InputRefused, match="duplicate"):
        SourceRegistry([TrustedSource("q", "broker_quotes", KEYS["quotes"])] * 2)


def test_quote_envelope_round_trip(kit):
    q = kit.verifier.quote(kit.quote())
    assert (q.canonical_id, q.bid, q.ask, q.source_id) == \
        (MSFT, Decimal("499.9"), Decimal("500"), "etoro-demo-quotes")


def test_tampered_forged_or_misrouted_envelopes_are_refused(kit):
    env = kit.quote()
    with pytest.raises(InputRefused, match="MAC"):
        kit.verifier.quote(replace(env, payload={**env.payload, "ask": "1"}))
    forged = TrustedSource("etoro-demo-quotes", "broker_quotes", b"x" * 40)
    with pytest.raises(InputRefused, match="MAC"):
        kit.verifier.quote(SourceSigner(forged, kit.env.clock).seal(dict(env.payload)))
    unknown = TrustedSource("someone", "broker_quotes", b"y" * 40)
    with pytest.raises(InputRefused, match="not registered"):
        kit.verifier.quote(SourceSigner(unknown, kit.env.clock).seal(dict(env.payload)))
    with pytest.raises(InputRefused, match="expected a fill"):
        kit.verifier.fill(kit.quote())                       # a quote is not fill evidence


def test_stale_future_and_replayed_envelopes_are_refused(kit, tmp_path):
    env = kit.quote()
    kit.verifier.quote(env)
    with pytest.raises(InputRefused, match="replayed"):
        kit.verifier.quote(env)
    kit.nonces.close()                                       # replay refused across restarts
    kit.nonces = NonceStore(tmp_path / "nonces.sqlite3")
    kit.verifier = InputVerifier(SourceRegistry(SOURCES), kit.nonces, clock=kit.env.clock)
    with pytest.raises(InputRefused, match="replayed"):
        kit.verifier.quote(env)
    old = kit.quote()
    kit.env.clock.now += timedelta(seconds=61)
    with pytest.raises(InputRefused, match="stale"):
        kit.verifier.quote(old)
    future = kit.quote()
    kit.env.clock.now -= timedelta(seconds=30)
    with pytest.raises(InputRefused, match="future"):
        kit.verifier.quote(future)


def test_payloads_cannot_claim_their_own_authentication(kit):
    sealed = kit.signers["etoro-demo-quotes"].seal(
        {"canonical_id": MSFT, "bid": "1", "ask": "1", "quote_time": NOW.isoformat(),
         "authenticated": True})
    with pytest.raises(InputRefused, match="cannot assert"):
        kit.verifier.quote(sealed)
    with pytest.raises(InputRefused, match="cannot assert"):
        kit.verifier.signal(kit.native(source_id="sma_cross", verified=True))


def test_only_the_native_runner_emits_native_strategy_signals(kit):
    signal = kit.verifier.signal(kit.native())
    assert (signal.source_kind, signal.source_id) == ("NATIVE_STRATEGY", "sma_cross")
    spoof = kit.signers["ta-adapter"].seal({"source_kind": "NATIVE_STRATEGY",
                                            "canonical_id": MSFT})
    with pytest.raises(InputRefused, match="native strategy runner"):
        kit.verifier.signal(spoof)
    with pytest.raises(InputRefused, match="NATIVE_STRATEGY signals only"):
        kit.verifier.signal(kit.native(source_kind="TRADINGAGENTS"))


def test_quote_and_fill_shapes_are_strict(kit):
    with pytest.raises(InputRefused, match="bid <= ask"):
        kit.verifier.quote(kit.quote(bid="501", ask="500"))
    with pytest.raises(InputRefused, match="decimal"):
        kit.verifier.quote(kit.signers["etoro-demo-quotes"].seal(
            {"canonical_id": MSFT, "bid": 1.5, "ask": "2", "quote_time": NOW.isoformat()}))
    with pytest.raises(InputRefused, match="lookup digest"):
        kit.verifier.fill(kit.fill("e" * 32, lookup_sha256="none"))
    with pytest.raises(InputRefused, match="exactly"):
        kit.verifier.fill(kit.fill("e" * 32, extra="x"))


def test_fill_evidence_cannot_be_constructed_or_passed_around_the_verifier(kit):
    with pytest.raises(PolicyRefused, match="verified reconciliation path"):
        sd063.FillEvidence("e" * 32, "FILLED", Decimal(1), Decimal(1), NOW, "me", "o", LOOKUP)
    with pytest.raises(PolicyRefused, match="only verified"):
        kit.env.ledger.resolve("not evidence")                # type: ignore[arg-type]


# --- authenticated runtime end to end --------------------------------------------------------

def test_authenticated_lifecycle_entry_fill_stop_exit(kit):
    proposal = kit.open()
    assert [p.entry_reference for p in kit.env.ledger.open_positions()] == [proposal.reference_id]
    kit.env.clock.now += timedelta(hours=1)
    plan = kit.art.plan_exits(bids=[kit.quote(bid="470", ask="471")])
    assert [x.reason for x in plan.exits] == ["STOP_BREACHED"]
    kit.art.resolve(kit.fill(plan.exits[0].reference_id, units=str(proposal.units),
                             price="469.5"))
    assert kit.env.ledger.open_positions() == ()


def test_forged_quote_never_reaches_the_policy(kit):
    forged = SourceSigner(TrustedSource("etoro-demo-quotes", "broker_quotes", b"z" * 40),
                          kit.env.clock).seal({"canonical_id": MSFT, "bid": "1", "ask": "1",
                                               "quote_time": NOW.isoformat()})
    result = kit.entry(quote=forged)
    assert isinstance(result, Refusal) and result.reasons[0].startswith("INPUT_REFUSED:")
    assert kit.env.ledger.state().entries == {}


def test_decision_price_comes_only_from_the_verified_quote(kit):
    priced = kit.research(last_price="1")                 # research may not carry a price
    result = kit.entry(research=priced)
    assert isinstance(result, Refusal) and "exactly" in result.reasons[0]
    proposal = kit.entry()
    assert isinstance(proposal, EntryProposal) and proposal.limit_price == Decimal("502.50")


def test_research_context_must_be_sealed_by_the_research_pipeline(kit):
    wrong = kit.signers["etoro-demo-quotes"].seal({"canonical_id": MSFT, "atr": "10"})
    result = kit.entry(research=wrong)
    assert isinstance(result, Refusal) and result.reasons[0].startswith("INPUT_REFUSED:")
    result = kit.entry(research=kit.research(atr="0"))
    assert isinstance(result, Refusal) and "ATR" in result.reasons[0]


def test_mapping_payload_tricks_cannot_swap_verified_content(kit):
    real = kit.quote()

    class Evil(dict):
        def items(self):                                   # what json.dumps would see
            return real.payload.items()

        def __iter__(self):
            return iter(real.payload)

    swapped = replace(real, payload=Evil({**real.payload, "bid": "1.0", "ask": "1.01"}))
    with pytest.raises(InputRefused, match="plain JSON object"):
        kit.verifier.quote(swapped)
    with pytest.raises(InputRefused, match="plain JSON"):
        kit.verifier.quote(replace(real, payload={**real.payload, 1: "x"}))


def test_malformed_mac_deep_payload_and_bad_research_are_refusals_not_crashes(kit):
    real = kit.quote()
    with pytest.raises(InputRefused, match="MAC"):
        kit.verifier.quote(replace(real, mac="é" * 64))
    deep: dict = {}
    node = deep
    for _ in range(5000):
        node["x"] = {}
        node = node["x"]
    with pytest.raises(InputRefused):
        kit.verifier.quote(replace(real, payload={**real.payload, "deep": deep}))
    old = kit.research(as_of=(kit.env.clock.now - timedelta(days=10)).isoformat())
    assert kit.entry(research=old) == Refusal(("RESEARCH_CONTEXT_STALE",))
    assert kit.entry(research=kit.research(atr="0.0001")) == \
        Refusal(("RESEARCH_ATR_OUT_OF_BAND",))


def test_raw_runtime_refuses_unverified_inputs_in_production(tmp_path):
    env = _Env(tmp_path)
    try:
        production = env.runtime(env.ledger, env.authority, allow_unverified_inputs=False)
        result = production.propose_entry(track="SWING", signals=(env.signal(),),
                                          admissions=ADMISSIONS, market=env.market(),
                                          quote=env.quote(), marks={})
        assert result == Refusal(("UNVERIFIED_INPUTS_REFUSED",))
        assert production.plan_exits(bids=env.bids("470")).alerts == \
            ("UNVERIFIED_INPUTS_REFUSED",)
    finally:
        env.ledger.close()


def test_sources_must_not_share_keys():
    with pytest.raises(InputRefused, match="own key"):
        SourceRegistry([TrustedSource("a", "broker_quotes", KEYS["quotes"]),
                        TrustedSource("b", "broker_reconciliation", KEYS["quotes"])])


def test_nonces_are_pruned_after_retention(kit):
    kit.verifier.quote(kit.quote())
    assert kit.nonces.count() == 1
    kit.env.clock.now += timedelta(days=9)
    kit.verifier.quote(kit.quote())
    assert kit.nonces.count() == 1                         # the 9-day-old nonce was pruned


def test_fill_provenance_is_recorded_in_the_ledger(kit):
    proposal = kit.entry()
    fill = kit.fill(proposal.reference_id, units=str(proposal.units))
    kit.art.resolve(fill)
    detail = json.loads(kit.env.ledger._conn.execute(
        "SELECT detail FROM events WHERE event = 'ENTRY_RESOLVED'").fetchone()[0])
    assert (detail["envelope_mac"], detail["envelope_nonce"]) == (fill.mac, fill.nonce)


def test_fill_from_a_quote_source_or_replayed_fill_is_refused(kit):
    proposal = kit.entry()
    with pytest.raises(InputRefused):
        kit.art.resolve(kit.quote())
    fill = kit.fill(proposal.reference_id)
    kit.art.resolve(fill)
    with pytest.raises(InputRefused, match="replayed"):
        kit.art.resolve(fill)


def test_unknown_fill_reference_is_refused(kit):
    with pytest.raises(PolicyRefused, match="unknown"):
        kit.art.resolve(kit.fill("f" * 32))


# --- verified reconciliation of unknown outcomes ---------------------------------------------

def test_unresolved_entry_is_settled_only_by_broker_evidence(kit):
    proposal = kit.entry()
    kit.art.resolve(kit.fill(proposal.reference_id, outcome="UNRESOLVED", units="0", price="0"))
    assert kit.env.ledger.kill_switch_engaged()
    with pytest.raises(PolicyRefused, match="final broker outcome"):
        kit.art.reconcile_unknown(kit.fill(proposal.reference_id, outcome="UNRESOLVED",
                                           units="0", price="0"))
    with pytest.raises(PolicyRefused, match="below the stop"):
        kit.art.reconcile_unknown(kit.fill(proposal.reference_id, price="1"))
    kit.art.reconcile_unknown(kit.fill(proposal.reference_id, units=str(proposal.units)))
    assert [p.entry_reference for p in kit.env.ledger.open_positions()] == [proposal.reference_id]
    assert kit.env.ledger.kill_switch_engaged()                # stays on
    with pytest.raises(PolicyRefused, match="only UNRESOLVED or QUARANTINED"):
        kit.art.reconcile_unknown(kit.fill(proposal.reference_id, units=str(proposal.units)))


def test_reconcile_refuses_proposals_that_are_not_unknown(kit):
    proposal = kit.entry()
    with pytest.raises(PolicyRefused, match="only UNRESOLVED or QUARANTINED"):
        kit.art.reconcile_unknown(kit.fill(proposal.reference_id))


def test_quarantined_entry_released_by_not_filled_evidence(kit):
    env = kit.env
    proposal = kit.entry()
    with env.ledger.transaction():
        env.ledger._append(env.clock.now, "RECOVERY_QUARANTINE", detail={
            "anchored_head": "0" * 64, "references": [proposal.reference_id], "rows": []})
    assert env.ledger.state().entries[proposal.reference_id].outcome == "QUARANTINED"
    kit.art.reconcile_unknown(kit.fill(proposal.reference_id, outcome="NOT_FILLED", units="0",
                                       price="0"))
    assert env.ledger.state().entries[proposal.reference_id].outcome == "NOT_FILLED"


# --- protective-exit authority ---------------------------------------------------------------

def _protective(env: _Env, **changes: object) -> tuple[dict, str]:
    fields: dict[str, object] = dict(
        grant_id="5d2c8a1b-3e4f-4a5b-9c6d-7e8f9a0b1c2d",
        subject_digest=protective_subject(env.policy),
        not_before=datetime(2026, 11, 3, 14, 0, tzinfo=UTC),
        expires_at=datetime(2026, 11, 9, 20, 0, tzinfo=UTC))
    fields.update(changes)
    grant = replace(_grant(env.policy), **fields)  # type: ignore[arg-type]
    return json.loads(grant.canonical()), f"sig:{grant.digest()}"


def test_protective_authority_flattens_after_policy_expiry_but_never_enters(tmp_path):
    env = _Env(tmp_path)
    kit = _Kit(tmp_path, env, protective_grant=_protective(env))
    try:
        proposal = kit.open()
        env.clock.now = datetime(2026, 11, 9, 15, 0, tzinfo=UTC)          # policy expired
        plan = kit.art.plan_exits(bids=[kit.quote(bid="500", ask="500.1")])
        assert [(x.reason, x.authority) for x in plan.exits] == [("PROTECTIVE_FLATTEN",
                                                                  "protective")]
        assert plan.exits[0].entry_reference == proposal.reference_id
        assert "PROTECTIVE_EXIT_AUTHORITY_IN_USE" in plan.alerts
        assert kit.entry(AAPL) == Refusal(("POLICY_NOT_ACTIVE",))
    finally:
        kit.nonces.close()
        env.ledger.close()


def test_revocation_never_triggers_a_protective_liquidation(tmp_path):
    env = _Env(tmp_path)
    kit = _Kit(tmp_path, env, protective_grant=_protective(env))
    try:
        proposal = kit.open()
        env.authority.revoke(env.grant_document["grant_id"], "anyone may revoke")
        env.clock.now = datetime(2026, 11, 3, 15, 0, tzinfo=UTC)
        plan = kit.art.plan_exits(bids=[kit.quote(bid="500", ask="500.1")])
        assert plan.exits == ()
        assert f"GRANT_NOT_VALID_POSITION_OPEN:{proposal.reference_id}" in plan.alerts
        assert kit.entry(AAPL, marks=[kit.quote(bid="500", ask="500.1")]) == \
            Refusal(("GRANT_NOT_VALID",))
    finally:
        kit.nonces.close()
        env.ledger.close()


@pytest.mark.parametrize("changes", [
    {"subject_digest": "e" * 64},                                         # other subject
    {"not_before": datetime(2026, 11, 2, 13, 0, tzinfo=UTC)},             # predates policy
])
def test_invalid_protective_grants_do_not_authorize_exits(tmp_path, changes):
    env = _Env(tmp_path)
    kit = _Kit(tmp_path, env, protective_grant=_protective(env, **changes))
    try:
        kit.open()
        env.clock.now = datetime(2026, 11, 9, 15, 0, tzinfo=UTC)
        plan = kit.art.plan_exits(bids=[kit.quote(bid="500", ask="500.1")])
        assert plan.exits == ()
        assert any(a.startswith("POLICY_EXPIRED_POSITION_OPEN:") for a in plan.alerts)
    finally:
        kit.nonces.close()
        env.ledger.close()


# --- incident report -------------------------------------------------------------------------

def test_incident_report_names_owner_actions(kit):
    assert kit.env.rt.incident_report()["status"] == "OK"
    proposal = kit.entry()
    kit.art.resolve(kit.fill(proposal.reference_id, outcome="UNRESOLVED", units="0", price="0"))
    report = kit.env.rt.incident_report()
    assert report["status"] == "ACTION_REQUIRED"
    assert report["kill_switch"] is True
    assert report["unresolved_entries"] == [proposal.reference_id]
    assert any("reconcile_unknown" in a for a in report["owner_actions"])
    assert report["submission"] == "OFFLINE_PROPOSAL_NOT_SUBMITTED"


def test_incident_report_flags_positions_without_exit_authority(kit):
    kit.open()
    kit.env.clock.now = datetime(2026, 11, 9, 15, 0, tzinfo=UTC)
    report = kit.env.rt.incident_report()
    assert report["policy_active"] is False and report["protective_exit_authority"] is False
    assert any("close them manually" in a for a in report["owner_actions"])


# --- adversarial lifecycle -------------------------------------------------------------------

def test_restart_between_proposal_and_fill(tmp_path):
    env = _Env(tmp_path)
    kit = _Kit(tmp_path, env)
    try:
        proposal = kit.entry()
        env.ledger.close()
        env.ledger = env.open_ledger()
        kit.art = AuthenticatedRuntime(env.runtime(env.ledger, env.authority), kit.verifier)
        kit.art.resolve(kit.fill(proposal.reference_id, units=str(proposal.units)))
        assert len(env.ledger.open_positions()) == 1
    finally:
        kit.nonces.close()
        env.ledger.close()


def test_partial_exit_leaves_the_remainder_managed(kit):
    proposal = kit.open()
    kit.env.clock.now += timedelta(hours=1)
    first = kit.art.plan_exits(bids=[kit.quote(bid="470", ask="471")]).exits[0]
    kit.art.resolve(kit.fill(first.reference_id, outcome="PARTIALLY_FILLED", units="0.0990",
                             price="470"))
    remaining = kit.env.ledger.open_positions()[0]
    assert remaining.units == proposal.units - Decimal("0.0990")
    kit.env.clock.now += timedelta(seconds=10)
    second = kit.art.plan_exits(bids=[kit.quote(bid="470", ask="471")]).exits[0]
    assert second.units == remaining.units and second.reference_id != first.reference_id


def test_expired_policy_and_stale_quote_refuse_entries(kit):
    stale = kit.quote()
    kit.env.clock.now += timedelta(seconds=90)
    result = kit.entry(quote=stale)
    assert isinstance(result, Refusal) and "stale" in result.reasons[0]
    kit.env.clock.now = datetime(2026, 11, 7, 15, 0, tzinfo=UTC)
    assert kit.entry() == Refusal(("POLICY_NOT_ACTIVE",))


def test_duplicate_submission_of_the_same_signal_envelope_is_refused(kit):
    signal = kit.native()
    first = kit.entry(signals=[signal])
    assert isinstance(first, EntryProposal)
    again = kit.entry(signals=[signal])
    assert isinstance(again, Refusal) and "replayed" in again.reasons[0]
