"""SD-063 bounded autonomous eToro Demo policy (offline; proposals only, never sent).

Includes regression tests for the independent review findings F1-F13 (2026-10-23).
"""
from __future__ import annotations

import ast
import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from sidedeck.application import sd063_autonomous_demo_policy as sd063
from sidedeck.application.sd063_autonomous_demo_policy import (
    AutonomousDemoPolicy, AutonomousDemoRuntime, EntryProposal, EntryQuote, ExitQuote,
    InstrumentScope, PolicyLedger, PolicyRefused, Refusal, StrategyScope, TrackBudget,
    check_grant_binding,
)
from sidedeck.application.sd064_unlock_grant import (
    GRANT_NAMESPACE, GrantLedger, UnlockAuthority, UnlockGrant,
)
from sidedeck.application.sd070_research_signal import EvidenceRef, ResearchSignal
from sidedeck.application.sd071_decision_engine import MarketContext, StrategyAdmission

UTC = timezone.utc
NOW = datetime(2026, 11, 2, 15, 0, tzinfo=UTC)          # Monday 10:00 New York
MSFT, AAPL, NVDA, AMZN = "US:XNAS:MSFT", "US:XNAS:AAPL", "US:XNAS:NVDA", "US:XNAS:AMZN"
IDS = {MSFT: 1004, AAPL: 2001, NVDA: 2002, AMZN: 2003}
PROTECTED = frozenset({1001, 1002, 1003, 1005})
EVIDENCE = b"SD-022 locked out-of-sample report for sma_cross 1.0.0\n"
EVIDENCE_SHA = hashlib.sha256(EVIDENCE).hexdigest()
SHA = "a" * 64


def _budget(**changes: object) -> TrackBudget:
    base = TrackBudget("SWING", Decimal("500"), Decimal("100"), 3, 2, 4, Decimal("0.05"),
                       Decimal("0.10"), Decimal("0.20"), Decimal("0.02"), Decimal("2"),
                       Decimal("0.8"))
    return replace(base, **changes)  # type: ignore[arg-type]


def _policy(**changes: object) -> AutonomousDemoPolicy:
    base = AutonomousDemoPolicy(
        policy_id="7b0c3e52-6f5e-4a8e-9d3c-2f1a0b9c8d7e",
        not_before=datetime(2026, 11, 2, 14, 0, tzinfo=UTC),
        expires_at=datetime(2026, 11, 6, 21, 0, tzinfo=UTC),
        tracks=(_budget(),),
        strategies=(StrategyScope("sma_cross", "1.0.0", "SWING", "SD022.md", EVIDENCE_SHA),),
        instruments=tuple(InstrumentScope(c, i) for c, i in IDS.items()),
        protected_instrument_ids=PROTECTED,
        max_limit_premium_pct=Decimal("0.005"),
        max_quote_age_seconds=60,
        max_signal_age_seconds=3600,
        max_signal_data_age_seconds=86400,
        purpose="SD-063 offline test policy",
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def _fill(reference: str, outcome: str, at: datetime, *, filled_units: Decimal = Decimal(0),
          avg_price: Decimal = Decimal(0)) -> sd063.FillEvidence:
    """Test stand-in for SD-074 verified reconciliation evidence."""
    return sd063._new_fill_evidence(reference=reference, outcome=outcome, units=filled_units,
                                    price=avg_price, at=at, source_id="test-reconciliation",
                                    broker_order_id="demo-order-1", lookup_sha256="c" * 64)


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class _FakeVerifier:
    """Stands in for SshSignatureVerifier (real signatures are covered by SD-064 tests)."""
    namespace = GRANT_NAMESPACE

    def __call__(self, principal: str, digest: str, signature: str) -> bool:
        return principal == "owner@sidedeck" and signature == f"sig:{digest}"


def _grant(policy: AutonomousDemoPolicy, **changes: object) -> UnlockGrant:
    base = UnlockGrant(grant_id="0f6d4c1e-2b3a-4c5d-8e9f-a0b1c2d3e4f5", kind="autonomous_policy",
                       subject_digest=policy.digest(), not_before=policy.not_before,
                       expires_at=policy.expires_at, max_requests=400, max_writes=40,
                       issued_by="owner@sidedeck", purpose="SD-063 test")
    return replace(base, **changes)  # type: ignore[arg-type]


class _Env:
    def __init__(self, tmp: Path, policy: AutonomousDemoPolicy | None = None) -> None:
        self.tmp = tmp
        self.policy = policy or _policy()
        (tmp / "evidence").mkdir(exist_ok=True)
        (tmp / "evidence" / "SD022.md").write_bytes(EVIDENCE)
        self.clock = _Clock(NOW)
        grant = _grant(self.policy)
        self.grant_document = json.loads(grant.canonical())
        self.signature = f"sig:{grant.digest()}"
        self.ledger = self.open_ledger()
        self.authority = self.make_authority()
        self.rt = self.runtime(self.ledger, self.authority)

    def open_ledger(self) -> PolicyLedger:
        return PolicyLedger.open(self.tmp / "sd063.sqlite3", self.policy.digest(),
                                 anchor_path=self.tmp / "sd063.anchor.json")

    def make_authority(self) -> UnlockAuthority:
        grants = GrantLedger(str(self.tmp / "grants.sqlite3"),
                             anchor_path=str(self.tmp / "grants.anchor.json"))
        return UnlockAuthority(verifier=_FakeVerifier(), principal="owner@sidedeck",
                               ledger=grants)

    def runtime(self, ledger: PolicyLedger, authority: UnlockAuthority,
                **changes: object) -> AutonomousDemoRuntime:
        kwargs: dict[str, object] = dict(
            authority=authority, grant_document=self.grant_document,
            grant_signature=self.signature, evidence_root=self.tmp / "evidence",
            clock=self.clock)
        kwargs.update(changes)
        return AutonomousDemoRuntime(self.policy, ledger, **kwargs)  # type: ignore[arg-type]

    # inputs
    def signal(self, cid: str = MSFT, *, kind: str = "NATIVE_STRATEGY", source: str = "sma_cross",
               version: str = "1.0.0", age: timedelta = timedelta(minutes=2),
               horizon: int = 10) -> ResearchSignal:
        generated = self.clock.now - age
        return ResearchSignal(
            canonical_id=cid, track="SWING", source_kind=kind, source_id=source,
            source_version=version, horizon_min_days=2, horizon_max_days=horizon,
            direction="LONG", evidence=(EvidenceRef("backtest", "SD022.md", SHA),),
            generated_at=generated, data_cutoff=generated - timedelta(hours=1),
            invalidation=("close below SMA50",))

    def market(self, cid: str = MSFT, *, price: str = "500", atr: str = "10") -> MarketContext:
        return MarketContext(cid, Decimal(price), self.clock.now - timedelta(seconds=5),
                             Decimal(atr), "Technology", True, True,
                             {other: Decimal("0.1") for other in IDS if other != cid})

    def quote(self, cid: str = MSFT, ask: str = "500") -> EntryQuote:
        return EntryQuote(cid, Decimal(ask), self.clock.now - timedelta(seconds=5))

    def bids(self, price: str, *cids: str) -> dict[str, ExitQuote]:
        return {c: ExitQuote(c, Decimal(price), self.clock.now - timedelta(seconds=5))
                for c in (cids or (MSFT,))}

    def entry(self, cid: str = MSFT, *, rt: AutonomousDemoRuntime | None = None,
              **changes: object) -> EntryProposal | Refusal:
        kwargs: dict[str, object] = dict(
            track="SWING", signals=(self.signal(cid),),
            admissions=(StrategyAdmission("sma_cross", "1.0.0", "SWING", "ADMITTED", "SD022.md",
                                          45, True),),
            market=self.market(cid), quote=self.quote(cid), marks={})
        kwargs.update(changes)
        return (rt or self.rt).propose_entry(**kwargs)  # type: ignore[arg-type]

    def open_position(self, cid: str = MSFT, units: str | None = None,
                      price: str = "500", **changes: object) -> EntryProposal:
        proposal = self.entry(cid, **changes)
        assert isinstance(proposal, EntryProposal), proposal
        filled = Decimal(units) if units else proposal.units
        outcome = "FILLED" if filled == proposal.units else "PARTIALLY_FILLED"
        self.ledger.resolve(_fill(proposal.reference_id, outcome, self.clock.now,
                            filled_units=filled, avg_price=Decimal(price)))
        return proposal


@pytest.fixture
def env(tmp_path: Path):
    e = _Env(tmp_path)
    yield e
    e.ledger.close()


# --- policy document -------------------------------------------------------------------------

def test_policy_digest_is_stable_and_round_trips():
    policy = _policy()
    assert len(policy.digest()) == 64
    assert AutonomousDemoPolicy.from_document(policy.to_document()).digest() == policy.digest()
    assert _policy(purpose="different").digest() != policy.digest()


def test_from_document_is_strict():
    document = _policy().to_document()
    with pytest.raises(PolicyRefused, match="exactly"):
        AutonomousDemoPolicy.from_document({**document, "execution": "auto"})
    with pytest.raises(PolicyRefused, match="schema"):
        AutonomousDemoPolicy.from_document({**document, "schema": "sidedeck-autonomous-demo-policy/1"})
    with pytest.raises(PolicyRefused):
        AutonomousDemoPolicy.from_document({**document, "broker": "etoro-real"})


@pytest.mark.parametrize("changes, message", [
    ({"broker": "etoro-real"}, "Demo"),
    ({"issued_by": "claude@sidedeck"}, "owner"),
    ({"policy_id": "not-a-uuid"}, "UUID"),
    ({"expires_at": datetime(2026, 11, 9, 15, 0, tzinfo=UTC)}, "7 days"),
    ({"expires_at": datetime(2026, 11, 2, 13, 0, tzinfo=UTC)}, "positive"),
    ({"not_before": datetime(2026, 11, 2, 14, 0)}, "timezone"),
    ({"not_before": datetime(2026, 11, 7, 12, 0, tzinfo=UTC),
      "expires_at": datetime(2026, 11, 8, 23, 0, tzinfo=UTC)}, "full exchange session"),
    ({"tracks": ()}, "at least one track"),
    ({"tracks": (_budget(), _budget())}, "duplicate track"),
    ({"tracks": (_budget(track="DAY"),)}, "DAY"),
    ({"tracks": (_budget(virtual_capital=Decimal("1200")),)}, "1000"),
    ({"tracks": (_budget(max_position_notional=Decimal("600")),)}, "position"),
    ({"tracks": (_budget(max_new_entries_per_day=5),)}, "entries"),
    ({"tracks": (_budget(max_orders_per_day=50),)}, "orders"),
    ({"tracks": (_budget(max_daily_loss_pct=Decimal("1.5")),)}, "loss"),
    ({"tracks": (_budget(max_loss_pct=Decimal("0")),)}, "loss"),
    ({"tracks": (_budget(risk_per_trade_pct=Decimal("0.2")),)}, "risk per trade"),
    ({"tracks": (_budget(stop_atr_multiple=Decimal("NaN")),)}, "finite"),
    ({"tracks": (_budget(max_open_positions=True),)}, "integer"),
    ({"instruments": (InstrumentScope(MSFT, 1001),)}, "protected"),
    ({"instruments": (InstrumentScope(MSFT, 1004), InstrumentScope(MSFT, 1006))}, "duplicate"),
    ({"instruments": ()}, "at least one instrument"),
    ({"protected_instrument_ids": frozenset()}, "must not be empty"),
    ({"strategies": (StrategyScope("sma_cross", "1.0.0", "POSITION", "x", SHA),)}, "track"),
    ({"strategies": (StrategyScope("sma_cross", "1.0.0", "SWING", "x", "nothex"),)}, "SHA-256"),
    ({"strategies": ()}, "at least one strategy"),
    ({"max_limit_premium_pct": Decimal("0.01")}, "premium"),
    ({"max_quote_age_seconds": 120}, "quote"),
    ({"max_signal_age_seconds": 0}, "max_signal_age_seconds"),
])
def test_policy_scope_violations_are_refused(changes, message):
    with pytest.raises(PolicyRefused, match=message):
        _policy(**changes)


# --- SD-064 grant binding (F1) ---------------------------------------------------------------

def test_grant_binding_accepts_only_the_matching_autonomous_grant():
    policy = _policy()
    check_grant_binding(policy, _grant(policy), NOW)
    with pytest.raises(PolicyRefused, match="digest"):
        check_grant_binding(policy, _grant(policy, subject_digest="b" * 64), NOW)
    with pytest.raises(PolicyRefused, match="autonomous_policy"):
        check_grant_binding(policy, _grant(policy, kind="pilot_release"), NOW)
    with pytest.raises(PolicyRefused, match="owner"):
        check_grant_binding(policy, _grant(policy, issued_by="claude@sidedeck"), NOW)
    for expires in (policy.expires_at + timedelta(hours=1), policy.expires_at - timedelta(days=2)):
        with pytest.raises(PolicyRefused, match="window"):
            check_grant_binding(policy, _grant(policy, expires_at=expires), NOW)
    with pytest.raises(PolicyRefused, match="active"):
        check_grant_binding(policy, _grant(policy), policy.expires_at)


def test_f1_revoked_grant_stops_entries_and_exits(env):
    position = env.open_position()
    env.authority.revoke(env.grant_document["grant_id"], "owner revoked")
    env.clock.now += timedelta(hours=1)
    assert env.entry(AAPL) == Refusal(("GRANT_NOT_VALID",))
    plan = env.rt.plan_exits(bids=env.bids("400"))
    assert plan.exits == ()
    assert plan.alerts == (f"GRANT_NOT_VALID_POSITION_OPEN:{position.reference_id}",)


def test_f1_bad_signature_or_other_policy_grant_is_not_valid(env):
    forged = env.runtime(env.ledger, env.authority, grant_signature="sig:forged")
    assert env.entry(rt=forged) == Refusal(("GRANT_NOT_VALID",))
    other = _policy(purpose="another policy")
    doc = json.loads(_grant(other).canonical())
    wrong = env.runtime(env.ledger, env.authority, grant_document=doc,
                        grant_signature=f"sig:{_grant(other).digest()}")
    assert env.entry(rt=wrong) == Refusal(("GRANT_NOT_VALID",))


def test_f1_time_comes_from_the_runtime_clock_only(env):
    env.clock.now = datetime(2026, 11, 2, 13, 0, tzinfo=UTC)
    assert env.entry() == Refusal(("POLICY_NOT_ACTIVE",))
    env.clock.now = NOW
    inputs = dict(track="SWING", signals=(env.signal(),), admissions=(), market=env.market(),
                  quote=env.quote(), marks={})
    env.clock.now = datetime(2026, 11, 2, 15, 0)            # naive clock refused
    with pytest.raises(PolicyRefused, match="timezone"):
        env.rt.propose_entry(**inputs)


# --- entry qualification ---------------------------------------------------------------------

def test_eligible_admitted_signal_becomes_an_unsent_bounded_limit_proposal(env):
    proposal = env.entry()
    assert isinstance(proposal, EntryProposal)
    assert proposal.policy_digest == env.policy.digest()
    assert proposal.etoro_instrument_id == 1004
    assert (proposal.order_type, proposal.leverage, proposal.direction) == ("limitIOC", 1, "BUY")
    assert proposal.limit_price == Decimal("502.50")          # ask x 1.005, rounded down
    assert proposal.units == Decimal("0.1990")                # capped by USD 100 max position
    assert proposal.stop_price == Decimal("480")              # last price - 2 x ATR
    assert proposal.strategies == ("sma_cross@1.0.0",)
    assert proposal.submission == "OFFLINE_PROPOSAL_NOT_SUBMITTED"
    assert len(proposal.reference_id) == 32


def test_f2_forged_or_tampered_evidence_never_qualifies(env):
    (env.tmp / "evidence" / "SD022.md").write_bytes(b"edited after the owner signed")
    result = env.entry()
    assert isinstance(result, Refusal) and result.reasons[0] == "DECISION_WATCHLIST"


def test_f2_evidence_path_traversal_is_refused(tmp_path):
    outside = tmp_path / "SD022.md"
    outside.write_bytes(EVIDENCE)
    policy = _policy(strategies=(StrategyScope("sma_cross", "1.0.0", "SWING", "../SD022.md",
                                               EVIDENCE_SHA),))
    e = _Env(tmp_path, policy)
    try:
        result = e.entry(admissions=(StrategyAdmission("sma_cross", "1.0.0", "SWING", "ADMITTED",
                                                       "../SD022.md", 45, True),))
        assert isinstance(result, Refusal) and result.reasons[0] == "DECISION_WATCHLIST"
    finally:
        e.ledger.close()


@pytest.mark.parametrize("make, first_reason", [
    (lambda e: {"admissions": ()}, "DECISION_WATCHLIST"),
    (lambda e: {"admissions": (StrategyAdmission("sma_cross", "1.0.0", "SWING", "ADMITTED",
                                                 "other.md", 45, True),)}, "DECISION_WATCHLIST"),
    (lambda e: {"signals": (e.signal(kind="TRADINGAGENTS", source="tradingagents"),)},
     "DECISION_WATCHLIST"),
    (lambda e: {"signals": (e.signal(age=timedelta(days=30)),)}, "DECISION_ABSTAIN"),
    (lambda e: {"signals": (e.signal(source="breakout", version="2.0.0"),),
                "admissions": (StrategyAdmission("breakout", "2.0.0", "SWING", "ADMITTED",
                                                 "SD022.md", 45, True),)}, "DECISION_WATCHLIST"),
    (lambda e: {"track": "POSITION"}, "TRACK_NOT_IN_POLICY"),
    (lambda e: {"market": e.market("US:XNAS:TSLA"), "quote": e.quote("US:XNAS:TSLA")},
     "INSTRUMENT_NOT_IN_POLICY"),
    (lambda e: {"quote": replace(e.quote(), quote_time=e.clock.now - timedelta(seconds=61))},
     "QUOTE_STALE"),
    (lambda e: {"quote": replace(e.quote(), quote_time=e.clock.now + timedelta(seconds=1))},
     "QUOTE_STALE"),
    (lambda e: {"quote": e.quote(ask="0")}, "QUOTE_INVALID"),
    (lambda e: {"quote": e.quote(ask="NaN")}, "QUOTE_INVALID"),
    (lambda e: {"quote": e.quote(AAPL)}, "QUOTE_INSTRUMENT_MISMATCH"),
    (lambda e: {"quote": e.quote(ask="520")}, "ASK_DEVIATES_FROM_DECISION_PRICE"),
    (lambda e: {"quote": e.quote(ask="1E+30")}, "ASK_DEVIATES_FROM_DECISION_PRICE"),
    (lambda e: {"market": e.market(atr="100")}, "STOP_TOO_WIDE"),
])
def test_entry_refusals(env, make, first_reason):
    result = env.entry(**make(env))
    assert isinstance(result, Refusal), result
    assert result.reasons[0] == first_reason
    assert env.ledger.state().entries == {}


def test_entries_only_inside_the_exchange_session(env):
    env.clock.now = datetime(2026, 11, 2, 14, 10, tzinfo=UTC)   # 09:10 New York
    assert env.entry() == Refusal(("MARKET_CLOSED",))


def test_duplicate_signal_set_is_single_use(env):
    first = env.entry()
    assert isinstance(first, EntryProposal)
    env.ledger.resolve(_fill(first.reference_id, "NOT_FILLED", env.clock.now))
    env.clock.now += timedelta(minutes=1)
    signals = (env.signal(),)
    # The same signals again (same signal ids) can never open a second order.
    again = env.rt.propose_entry(
        track="SWING", signals=signals,
        admissions=(StrategyAdmission("sma_cross", "1.0.0", "SWING", "ADMITTED", "SD022.md",
                                      45, True),),
        market=env.market(), quote=env.quote(), marks={})
    assert isinstance(again, EntryProposal)                      # new signal ids: allowed
    env.ledger.resolve(_fill(again.reference_id, "NOT_FILLED", env.clock.now))
    repeat = env.rt.propose_entry(
        track="SWING", signals=signals,
        admissions=(StrategyAdmission("sma_cross", "1.0.0", "SWING", "ADMITTED", "SD022.md",
                                      45, True),),
        market=env.market(), quote=env.quote(), marks={})
    assert repeat == Refusal(("DUPLICATE_ENTRY",))


def test_pending_entry_blocks_further_entries(env):
    assert isinstance(env.entry(), EntryProposal)
    env.clock.now += timedelta(minutes=1)
    assert env.entry(AAPL) == Refusal(("PENDING_ENTRY_UNRESOLVED",))


# --- exposure from the ledger (F3) -----------------------------------------------------------

def test_f3_exposure_and_positions_come_from_the_ledger(env):
    env.open_position(MSFT)
    env.clock.now += timedelta(minutes=1)
    env.open_position(AAPL, marks={MSFT: Decimal("500")})
    env.clock.now += timedelta(minutes=1)
    assert env.entry(NVDA, marks={MSFT: Decimal("500"), AAPL: Decimal("500")}) == \
        Refusal(("DAILY_ENTRY_LIMIT",))
    env.clock.now = datetime(2026, 11, 3, 15, 0, tzinfo=UTC)
    marks = {MSFT: Decimal("500"), AAPL: Decimal("500")}
    assert env.entry(MSFT, marks=marks) == Refusal(("DECISION_REJECTED", "ALREADY_HELD_IN_TRACK"))
    env.open_position(NVDA, marks=marks)
    env.clock.now += timedelta(minutes=1)
    marks[NVDA] = Decimal("500")
    fourth = env.entry(AMZN, marks=marks)
    assert fourth == Refusal(("DECISION_REJECTED", "MAX_POSITIONS"))
    positions = env.ledger.open_positions()
    assert len(positions) == 3
    assert sum(p.units * p.avg_price for p in positions) <= Decimal("500")


def test_f3_missing_mark_for_an_open_position_refuses(env):
    env.open_position(MSFT)
    env.clock.now = datetime(2026, 11, 3, 15, 0, tzinfo=UTC)
    assert env.entry(AAPL) == Refusal(("MARK_MISSING_FOR_OPEN_POSITION",))


def test_f3_unresolved_entries_stay_reserved(env):
    proposal = env.entry()
    env.ledger.resolve(_fill(proposal.reference_id, "UNRESOLVED", env.clock.now))
    state = env.ledger.state()
    assert state.killed and state.entries[proposal.reference_id].outcome == "UNRESOLVED"
    assert env.entry(AAPL) == Refusal(("KILL_SWITCH_ENGAGED",))


# --- concurrency (F4) ------------------------------------------------------------------------

def test_f4_concurrent_workers_cannot_exceed_one_pending_entry(env, monkeypatch):
    real_decide = sd063.decide

    def slow_decide(*args, **kwargs):
        time.sleep(0.2)                                    # widen the old TOCTOU window
        return real_decide(*args, **kwargs)

    monkeypatch.setattr(sd063, "decide", slow_decide)
    results: list[object] = []
    lock = threading.Lock()

    def worker(cid: str) -> None:
        ledger = env.open_ledger()
        try:
            rt = env.runtime(ledger, env.make_authority())
            outcome = env.entry(cid, rt=rt)
        finally:
            ledger.close()
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker, args=(c,)) for c in (MSFT, AAPL, NVDA)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sum(isinstance(r, EntryProposal) for r in results) == 1
    assert sorted(r.reasons for r in results if isinstance(r, Refusal)) == \
        [("PENDING_ENTRY_UNRESOLVED",)] * 2


# --- resolution and recovery -----------------------------------------------------------------

def test_resolve_validates_fills(env):
    with pytest.raises(PolicyRefused, match="unknown"):
        env.ledger.resolve(_fill("0" * 32, "FILLED", NOW))
    with pytest.raises(PolicyRefused, match="unknown"):
        env.ledger.resolve(_fill("not-a-ref; DROP TABLE", "FILLED", NOW))
    proposal = env.entry()
    ref = proposal.reference_id
    with pytest.raises(PolicyRefused, match="outcome"):
        env.ledger.resolve(_fill(ref, "MAYBE", NOW))
    with pytest.raises(PolicyRefused, match="exactly"):
        env.ledger.resolve(_fill(ref, "FILLED", NOW, filled_units=Decimal("0.1"), avg_price=Decimal("500")))
    with pytest.raises(PolicyRefused, match="units"):
        env.ledger.resolve(_fill(ref, "PARTIALLY_FILLED", NOW, filled_units=Decimal("5"),
                           avg_price=Decimal("500")))
    with pytest.raises(PolicyRefused, match="above the limit"):
        env.ledger.resolve(_fill(ref, "FILLED", NOW, filled_units=proposal.units,
                           avg_price=Decimal("503")))
    with pytest.raises(PolicyRefused, match="only fill outcomes"):
        env.ledger.resolve(_fill(ref, "NOT_FILLED", NOW, filled_units=Decimal("0.1")))
    env.ledger.resolve(_fill(ref, "FILLED", NOW, filled_units=proposal.units, avg_price=Decimal("500")))
    with pytest.raises(PolicyRefused, match="already resolved"):
        env.ledger.resolve(_fill(ref, "FILLED", NOW, filled_units=proposal.units,
                           avg_price=Decimal("500")))


def test_n1_reconciliation_values_are_bounded(env):
    proposal = env.entry()
    ref, units = proposal.reference_id, proposal.units
    with pytest.raises(PolicyRefused, match="below the stop"):
        env.ledger.resolve(_fill(ref, "FILLED", NOW, filled_units=units, avg_price=Decimal("0.01")))
    with pytest.raises(PolicyRefused, match="IOC fill window"):
        env.ledger.resolve(_fill(ref, "FILLED", NOW + timedelta(days=30), filled_units=units,
                           avg_price=Decimal("500")))
    with pytest.raises(PolicyRefused, match="precedes"):
        env.ledger.resolve(_fill(ref, "FILLED", NOW - timedelta(minutes=1), filled_units=units,
                           avg_price=Decimal("500")))
    env.ledger.resolve(_fill(ref, "FILLED", NOW, filled_units=units, avg_price=Decimal("500")))
    env.clock.now += timedelta(hours=1)
    exit_ = env.rt.plan_exits(bids=env.bids("470")).exits[0]
    with pytest.raises(PolicyRefused, match="planned bid"):
        env.ledger.resolve(_fill(exit_.reference_id, "FILLED", env.clock.now, filled_units=units,
                           avg_price=Decimal("100000")))
    env.ledger.resolve(_fill(exit_.reference_id, "FILLED", env.clock.now, filled_units=units,
                       avg_price=Decimal("469")))


class _CommitFails:
    """Connection proxy whose COMMIT raises (simulated crash after the anchor write)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def execute(self, sql: str, *args: object):
        if sql.strip().upper() == "COMMIT":
            raise sqlite3.OperationalError("disk I/O error")
        return self._conn.execute(sql, *args)

    def __getattr__(self, name: str):
        return getattr(self._conn, name)


def _recover(env: _Env, expected_head: str | None = None) -> PolicyLedger:
    anchor = env.tmp / "sd063.anchor.json"
    head = expected_head or PolicyLedger.inspect_recovery(anchor)["expected_head"]
    return PolicyLedger.recover_last_transaction(
        env.tmp / "sd063.sqlite3", env.policy.digest(), anchor_path=anchor,
        expected_head=head, at=env.clock.now)


def _forge_anchor(env: _Env, rows: list[list[str | None]]) -> None:
    """Anchor-only edit: append forged rows with valid (unkeyed) hashes; DB untouched."""
    with env.ledger.transaction():
        count, head = env.ledger._head()
    cursor, pending = head, []
    for row in rows:
        digest = PolicyLedger._hash(cursor, row)
        pending.append((*row, cursor, digest))
        cursor = digest
    env.ledger._write_anchor(count + len(rows), cursor, prev=(count, head), pending=pending)
    env.ledger.close()


def _detail(**values: str) -> str:
    return json.dumps(values, sort_keys=True, separators=(",", ":"))


def test_n2d_anchor_only_forgeries_never_become_state(env):
    real = env.open_position()                                   # one genuine filled position
    env.clock.now += timedelta(minutes=5)
    at = env.clock.now.isoformat()
    phantom, fake_exit = "a" * 32, "b" * 32
    _forge_anchor(env, [
        [at, "ENTRY_PROPOSED", "SWING", phantom, None,
         json.dumps({"canonical_id": "US:XNAS:EVIL", "instrument": 1001, "sector": "x",
                     "units": "1000", "limit": "500", "stop": "0.01", "horizon": 10,
                     "strategies": []}, sort_keys=True, separators=(",", ":"))],
        [at, "ENTRY_RESOLVED", None, phantom, None,
         _detail(outcome="FILLED", units="1000", price="0.02")],
        [at, "EXIT_PROPOSED", "SWING", fake_exit, None,
         _detail(entry=real.reference_id, units=str(real.units), bid="1000000", reason="x")],
        [at, "EXIT_RESOLVED", None, fake_exit, None,
         _detail(outcome="FILLED", units=str(real.units), price="1000000")],
    ])
    with pytest.raises(PolicyRefused, match="anchor"):
        env.open_ledger()
    preview = PolicyLedger.inspect_recovery(env.tmp / "sd063.anchor.json")
    assert [r["event"] for r in preview["rows"]][:2] == ["ENTRY_PROPOSED", "ENTRY_RESOLVED"]
    with pytest.raises(PolicyRefused, match="owner-confirmed head"):
        _recover(env, expected_head="0" * 64)
    env.ledger = _recover(env)
    env.rt = env.runtime(env.ledger, env.authority)
    state = env.ledger.state()
    assert state.killed
    assert set(state.entries) == {real.reference_id}             # no phantom entry
    assert state.exits == {}                                     # no forged exit
    assert sum(e.realized for e in state.entries.values()) == 0  # no forged P&L
    assert [p.entry_reference for p in env.ledger.open_positions()] == [real.reference_id]
    env.clock.now += timedelta(minutes=5)
    plan = env.rt.plan_exits(bids=env.bids("470"))               # stop still protects it
    assert [x.reason for x in plan.exits] == ["STOP_BREACHED"]
    assert f"QUARANTINED_UNKNOWN_REFERENCE:{phantom}" in plan.alerts


def test_n2_crash_in_a_multi_row_transaction_is_replayed_and_trips_kill_switch(env):
    real = env.ledger._conn
    env.ledger._conn = _CommitFails(real)                     # type: ignore[assignment]
    with pytest.raises(sqlite3.OperationalError):
        env.entry()                                           # EQUITY_MARK + ENTRY_PROPOSED
    env.ledger._conn = real
    env.ledger.close()
    with pytest.raises(PolicyRefused, match="anchor"):
        env.open_ledger()
    recovered = _recover(env)
    try:
        state = recovered.state()
        assert state.killed
        assert state.entries == {}            # the crashed proposal was never sent: not state
        assert len(state.quarantined) == 1    # but it is kept, visible, as quarantined data
    finally:
        recovered.close()
    env.ledger = env.open_ledger()                            # consistent again


def test_n2_deleted_last_transaction_is_quarantined_not_hidden(env):
    proposal = env.open_position()                            # last txn: ENTRY_RESOLVED
    env.ledger.close()
    conn = sqlite3.connect(env.tmp / "sd063.sqlite3")
    try:
        conn.execute("DROP TRIGGER events_no_delete")
        conn.execute("CREATE TRIGGER events_no_delete BEFORE DELETE ON events BEGIN SELECT 1; END")
        conn.execute("DELETE FROM events WHERE seq = (SELECT MAX(seq) FROM events)")
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(PolicyRefused, match="anchor"):
        env.open_ledger()
    recovered = _recover(env)
    try:
        assert recovered.kill_switch_engaged()
        entry = recovered.state().entries[proposal.reference_id]
        assert entry.outcome == "QUARANTINED"           # visible, reserved, owner must check
    finally:
        recovered.close()
    env.ledger = env.open_ledger()


def test_n2_recovery_refuses_a_consistent_or_unrelated_ledger(env):
    env.entry()
    env.ledger.close()
    with pytest.raises(PolicyRefused, match="last anchored transaction"):
        _recover(env)
    env.ledger = env.open_ledger()


def test_n4_polling_does_not_grow_equity_marks(env):
    for _ in range(5):
        env.entry(quote=env.quote(ask="520"))                         # refused after decide
        env.clock.now += timedelta(seconds=1)
    marks = [e for e in env.ledger._conn.execute(
        "SELECT event FROM events WHERE event = 'EQUITY_MARK'")]
    assert len(marks) == 1


def test_polling_exit_plans_does_not_grow_alert_rows(env):
    env.open_position()
    env.ledger.trip_kill_switch("operator", env.clock.now)
    env.clock.now += timedelta(hours=1)
    stale = {MSFT: ExitQuote(MSFT, Decimal("470"), env.clock.now - timedelta(minutes=5))}
    for _ in range(5):
        env.rt.plan_exits(bids=stale)
        env.clock.now += timedelta(seconds=1)
    alerts = [r for r in env.ledger._conn.execute("SELECT 1 FROM events WHERE event = 'ALERT'")]
    assert len(alerts) == 2          # KILL_SWITCH_ENGAGED + QUOTE_UNAVAILABLE, once each


def test_kill_switch_persists_across_restart(env):
    proposal = env.entry()
    env.ledger.resolve(_fill(proposal.reference_id, "UNRESOLVED", env.clock.now))
    env.ledger.close()
    env.ledger = env.open_ledger()
    env.rt = env.runtime(env.ledger, env.authority)
    assert env.ledger.kill_switch_engaged()
    env.clock.now += timedelta(minutes=1)
    assert env.entry(AAPL) == Refusal(("KILL_SWITCH_ENGAGED",))


# --- exits from the ledger (F5, F6, F7, F11) -------------------------------------------------

def test_f5_stop_exit_closes_exactly_the_filled_units_once(env):
    entry = env.open_position(units="0.1500", price="500")     # partial IOC fill
    env.clock.now += timedelta(hours=1)
    plan = env.rt.plan_exits(bids=env.bids("479.99"))
    assert [(x.reason, x.units) for x in plan.exits] == [("STOP_BREACHED", Decimal("0.1500"))]
    assert plan.exits[0].entry_reference == entry.reference_id
    assert plan.exits[0].submission == "OFFLINE_PROPOSAL_NOT_SUBMITTED"
    again = env.rt.plan_exits(bids=env.bids("470"))
    assert again.exits == () and again.alerts == (f"EXIT_PENDING:{entry.reference_id}",)
    env.ledger.resolve(_fill(plan.exits[0].reference_id, "FILLED", env.clock.now,
                       filled_units=Decimal("0.1500"), avg_price=Decimal("479")))
    assert env.ledger.open_positions() == ()
    assert env.rt.plan_exits(bids=env.bids("470")).exits == ()


def test_f5_not_filled_exit_is_retried_with_a_new_reference(env):
    env.open_position()
    env.clock.now += timedelta(hours=1)
    first = env.rt.plan_exits(bids=env.bids("470")).exits[0]
    env.ledger.resolve(_fill(first.reference_id, "NOT_FILLED", env.clock.now))
    second = env.rt.plan_exits(bids=env.bids("470")).exits[0]
    assert second.reference_id != first.reference_id


def test_horizon_counts_exchange_sessions(tmp_path):
    e = _Env(tmp_path)
    try:
        e.open_position(signals=(e.signal(horizon=2),))
        e.clock.now = datetime(2026, 11, 3, 15, 0, tzinfo=UTC)
        assert e.rt.plan_exits(bids=e.bids("500")).exits == ()
        e.clock.now = datetime(2026, 11, 4, 15, 0, tzinfo=UTC)
        assert [x.reason for x in e.rt.plan_exits(bids=e.bids("500")).exits] == ["HORIZON_REACHED"]
    finally:
        e.ledger.close()


def test_f6_kill_switch_blocks_entries_but_not_protective_exits(env):
    env.open_position()
    env.ledger.trip_kill_switch("operator", env.clock.now)
    env.clock.now += timedelta(hours=1)
    plan = env.rt.plan_exits(bids=env.bids("470"))
    assert [x.reason for x in plan.exits] == ["STOP_BREACHED"]
    assert plan.alerts == ("KILL_SWITCH_ENGAGED",)
    assert env.entry(AAPL) == Refusal(("KILL_SWITCH_ENGAGED",))


def test_f7_flatten_uses_the_last_session_before_a_weekend_expiry(tmp_path):
    policy = _policy(expires_at=datetime(2026, 11, 9, 13, 0, tzinfo=UTC))   # Monday pre-open
    e = _Env(tmp_path, policy)
    try:
        e.open_position()
        e.clock.now = datetime(2026, 11, 6, 15, 0, tzinfo=UTC)               # Friday session
        assert e.entry(AAPL, marks={MSFT: Decimal("500")}) == Refusal(("ENTRY_WINDOW_CLOSED",))
        assert e.rt.plan_exits(bids=e.bids("500")).exits == ()
        e.clock.now = datetime(2026, 11, 6, 20, 15, tzinfo=UTC)              # last hour
        plan = e.rt.plan_exits(bids=e.bids("500"))
        assert [x.reason for x in plan.exits] == ["POLICY_EXPIRY_FLATTEN"]
        e.ledger.resolve(_fill(plan.exits[0].reference_id, "NOT_FILLED", e.clock.now))
        e.clock.now = datetime(2026, 11, 9, 13, 30, tzinfo=UTC)              # after expiry
        late = e.rt.plan_exits(bids=e.bids("500"))
        assert late.exits == ()
        assert late.alerts[0].startswith("POLICY_EXPIRED_POSITION_OPEN:")
    finally:
        e.ledger.close()


def test_stale_quote_raises_an_alert_not_an_exit(env):
    entry = env.open_position()
    env.clock.now += timedelta(hours=1)
    quotes = {MSFT: ExitQuote(MSFT, Decimal("470"), env.clock.now - timedelta(minutes=5))}
    plan = env.rt.plan_exits(bids=quotes)
    assert plan.exits == () and plan.alerts == (f"QUOTE_UNAVAILABLE:{entry.reference_id}",)


# --- equity and loss limits (F9) -------------------------------------------------------------

def test_f9_realized_losses_drive_the_cumulative_loss_limit(tmp_path):
    policy = _policy(tracks=(_budget(max_loss_pct=Decimal("0.0001"),
                                     max_drawdown_pct=Decimal("0.5"),
                                     max_daily_loss_pct=Decimal("0.5")),))
    e = _Env(tmp_path, policy)
    try:
        e.open_position()
        e.clock.now += timedelta(hours=1)
        exit_ = e.rt.plan_exits(bids=e.bids("470")).exits[0]
        e.ledger.resolve(_fill(exit_.reference_id, "FILLED", e.clock.now, filled_units=exit_.units,
                         avg_price=Decimal("470")))
        e.clock.now = datetime(2026, 11, 3, 15, 0, tzinfo=UTC)
        assert e.entry(AAPL) == Refusal(("CUMULATIVE_LOSS_LIMIT",))
    finally:
        e.ledger.close()


def test_f9_mark_to_market_drawdown_halts_entries(env):
    env.open_position()
    env.clock.now = datetime(2026, 11, 3, 15, 0, tzinfo=UTC)
    # 0.199 units marked from 500 to 1 is ~ -99 USD on 500 capital: 19.9 % drawdown.
    result = env.entry(AAPL, marks={MSFT: Decimal("1")})
    assert isinstance(result, Refusal) and "MAX_DRAWDOWN_BREACHED" in result.reasons


# --- ledger integrity (F8) -------------------------------------------------------------------

def test_f8_ledger_is_append_only_and_tamper_evident(env):
    env.ledger.trip_kill_switch("manual", NOW)
    env.ledger.close()
    db = env.tmp / "sd063.sqlite3"
    conn = sqlite3.connect(db)
    try:
        for sql in ("UPDATE events SET event = 'ALERT'", "DELETE FROM events",
                    "UPDATE meta SET policy_digest = 'x'"):
            with pytest.raises(sqlite3.DatabaseError):
                conn.execute(sql)
        conn.execute("DROP TRIGGER events_no_delete")
        conn.execute("DELETE FROM events")
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(PolicyRefused, match="triggers"):
        env.open_ledger()


def test_f8_deleted_or_replaced_ledger_fails_closed(env):
    env.ledger.trip_kill_switch("manual", NOW)
    env.ledger.close()
    (env.tmp / "sd063.sqlite3").unlink()
    with pytest.raises(PolicyRefused, match="anchor exists without its ledger"):
        env.open_ledger()


def test_f8_stale_anchor_fails_closed(env):
    anchor = env.tmp / "sd063.anchor.json"
    snapshot = anchor.read_text(encoding="utf-8")
    env.ledger.trip_kill_switch("manual", NOW)
    env.ledger.close()
    anchor.write_text(snapshot, encoding="utf-8")            # roll the anchor back
    with pytest.raises(PolicyRefused, match="anchor"):
        env.open_ledger()


def test_ledger_binding_and_foreign_files(env, tmp_path):
    env.ledger.close()
    with pytest.raises(PolicyRefused, match="different policy"):
        PolicyLedger.open(env.tmp / "sd063.sqlite3", "c" * 64,
                          anchor_path=env.tmp / "sd063.anchor.json")
    foreign = tmp_path / "etoro_demo.sqlite3"
    conn = sqlite3.connect(foreign)
    conn.execute("CREATE TABLE baseline_positions (id INTEGER)")
    conn.commit()
    conn.close()
    with pytest.raises(PolicyRefused, match="not an SD-063 policy ledger"):
        PolicyLedger.open(foreign, env.policy.digest(), anchor_path=tmp_path / "x.json")
    conn = sqlite3.connect(foreign)
    try:
        tables = {n for (n,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert tables == {"baseline_positions"}
    env.ledger = env.open_ledger()


def test_ledger_writes_require_a_transaction(env):
    with pytest.raises(PolicyRefused, match="transaction"):
        env.ledger._append(NOW, "ALERT", detail={"code": "x"})


# --- boundaries ------------------------------------------------------------------------------

def test_module_has_no_network_or_order_transport_access():
    tree = ast.parse(Path(sd063.__file__).read_text(encoding="utf-8"))
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    imported |= {node.module for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.module}
    assert not {m.split(".")[0] for m in imported} & {"urllib", "http", "requests", "httpx",
                                                       "socket", "aiohttp"}
    assert not any("write_transport" in m or "etoro_demo_client" in m for m in imported)


def test_runtime_api_takes_no_caller_time_decision_or_positions():
    import inspect
    params = set(inspect.signature(AutonomousDemoRuntime.propose_entry).parameters)
    assert not params & {"now", "decision", "open_positions", "equity"}
    assert set(inspect.signature(AutonomousDemoRuntime.plan_exits).parameters) == {"self", "bids"}
