"""SD-063 bounded autonomous eToro Demo policy (offline; proposals only, never sent)."""
from __future__ import annotations

import ast
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from sidedeck.application import sd063_autonomous_demo_policy as sd063
from sidedeck.application.sd063_autonomous_demo_policy import (
    AutonomousDemoPolicy, EntryProposal, EntryQuote, ExitQuote, InstrumentScope,
    ManagedPosition, PolicyLedger, PolicyRefused, Refusal, StrategyScope, TrackBudget,
    TrackEquity, check_grant_binding, plan_exits, propose_entry,
)
from sidedeck.application.sd064_unlock_grant import UnlockGrant
from sidedeck.application.sd070_research_signal import EvidenceRef, ResearchSignal
from sidedeck.application.sd071_decision_engine import Decision, SizingProposal, StrategyAdmission

UTC = timezone.utc
NOW = datetime(2026, 11, 2, 15, 0, tzinfo=UTC)          # Monday, NY session open
MSFT = "US:XNAS:MSFT"
PROTECTED = frozenset({1001, 1002, 1003, 1005})
SHA = "a" * 64


def _policy(**changes: object) -> AutonomousDemoPolicy:
    base = AutonomousDemoPolicy(
        policy_id="7b0c3e52-6f5e-4a8e-9d3c-2f1a0b9c8d7e",
        not_before=datetime(2026, 11, 2, 14, 0, tzinfo=UTC),
        expires_at=datetime(2026, 11, 6, 21, 0, tzinfo=UTC),
        tracks=(TrackBudget("SWING", Decimal("500"), Decimal("100"), 3, 2, 4,
                            Decimal("0.05"), Decimal("0.10")),),
        strategies=(StrategyScope("sma_cross", "1.0.0", "SWING", "docs/SD022.md"),),
        instruments=(InstrumentScope(MSFT, 1004),),
        protected_instrument_ids=PROTECTED,
        max_limit_premium_pct=Decimal("0.005"),
        max_quote_age_seconds=60,
        max_decision_age_seconds=300,
        purpose="SD-063 offline test policy",
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def _signal(source_kind: str = "NATIVE_STRATEGY", source_id: str = "sma_cross",
            version: str = "1.0.0", track: str = "SWING",
            generated_at: datetime = NOW - timedelta(minutes=2)) -> ResearchSignal:
    return ResearchSignal(
        canonical_id=MSFT, track=track, source_kind=source_kind, source_id=source_id,
        source_version=version, horizon_min_days=2, horizon_max_days=10, direction="LONG",
        evidence=(EvidenceRef("backtest", "docs/SD022.md", SHA),),
        generated_at=generated_at, data_cutoff=generated_at - timedelta(hours=1),
        invalidation=("close below SMA50",),
    )


def _decision(signal: ResearchSignal, **changes: object) -> Decision:
    base = Decision(
        status="ELIGIBLE", canonical_id=MSFT, track="SWING", policy_id="track-policy-1",
        decided_at=NOW - timedelta(minutes=1), reasons=("BINDING_LIMIT:MAX_POSITION",),
        qualified_signal_ids=(signal.signal_id,),
        sizing=SizingProposal(Decimal("0.3000"), Decimal("150.00"), Decimal("480.00"), 10,
                              "STOP_OR_TIME_EXIT_10_TRADING_DAYS"),
    )
    return replace(base, **changes)  # type: ignore[arg-type]


ADMISSIONS = (StrategyAdmission("sma_cross", "1.0.0", "SWING", "ADMITTED", "docs/SD022.md",
                                45, True),)
QUOTE = EntryQuote(MSFT, Decimal("500.00"), NOW - timedelta(seconds=10))
EQUITY = TrackEquity(Decimal("500"), Decimal("500"), Decimal("500"))


@pytest.fixture
def ledger(tmp_path: Path):
    book = PolicyLedger.open(tmp_path / "sd063.sqlite3", _policy().digest())
    yield book
    book.close()


def _entry(ledger: PolicyLedger, **changes: object) -> EntryProposal | Refusal:
    signal = changes.pop("signal", _signal())
    kwargs: dict[str, object] = dict(
        decision=_decision(signal), signals=(signal,), admissions=ADMISSIONS, quote=QUOTE,
        equity=EQUITY, open_positions=(), now=NOW,
    )
    kwargs.update(changes)
    return propose_entry(_policy(), ledger, **kwargs)  # type: ignore[arg-type]


def _fresh(ledger: PolicyLedger, at: datetime) -> EntryProposal | Refusal:
    """A distinct decision (new signal) at time ``at`` with a fresh quote."""
    signal = _signal(generated_at=at - timedelta(minutes=2))
    return _entry(ledger, signal=signal, decision=_decision(signal, decided_at=at - timedelta(minutes=1)),
                  quote=replace(QUOTE, quote_time=at - timedelta(seconds=5)), now=at)


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
        AutonomousDemoPolicy.from_document({**document, "schema": "other/1"})
    with pytest.raises(PolicyRefused):
        AutonomousDemoPolicy.from_document({**document, "broker": "etoro-real"})


def _budget(**changes: object) -> TrackBudget:
    base = TrackBudget("SWING", Decimal("500"), Decimal("100"), 3, 2, 4,
                       Decimal("0.05"), Decimal("0.10"))
    return replace(base, **changes)  # type: ignore[arg-type]


@pytest.mark.parametrize("changes, message", [
    ({"broker": "etoro-real"}, "Demo"),
    ({"issued_by": "claude@sidedeck"}, "owner"),
    ({"policy_id": "not-a-uuid"}, "UUID"),
    ({"expires_at": datetime(2026, 11, 9, 15, 0, tzinfo=UTC)}, "7 days"),
    ({"expires_at": datetime(2026, 11, 2, 13, 0, tzinfo=UTC)}, "positive"),
    ({"not_before": datetime(2026, 11, 2, 14, 0)}, "timezone"),
    ({"tracks": ()}, "at least one track"),
    ({"tracks": (_budget(), _budget())}, "duplicate track"),
    ({"tracks": (_budget(track="DAY"),)}, "DAY"),
    ({"tracks": (_budget(virtual_capital=Decimal("1200")),)}, "1000"),
    ({"tracks": (_budget(max_position_notional=Decimal("600")),)}, "position"),
    ({"tracks": (_budget(max_new_entries_per_day=5),)}, "entries"),
    ({"tracks": (_budget(max_orders_per_day=50),)}, "orders"),
    ({"tracks": (_budget(max_daily_loss_pct=Decimal("1.5")),)}, "loss"),
    ({"tracks": (_budget(max_open_positions=True),)}, "integer"),
    ({"instruments": (InstrumentScope(MSFT, 1001),)}, "protected"),
    ({"instruments": (InstrumentScope(MSFT, 1004), InstrumentScope(MSFT, 1006))}, "duplicate"),
    ({"instruments": ()}, "at least one instrument"),
    ({"strategies": (StrategyScope("sma_cross", "1.0.0", "POSITION", "x"),)}, "track"),
    ({"strategies": ()}, "at least one strategy"),
    ({"max_limit_premium_pct": Decimal("0.01")}, "premium"),
    ({"max_quote_age_seconds": 120}, "quote"),
    ({"max_decision_age_seconds": 3600}, "decision"),
])
def test_policy_scope_violations_are_refused(changes, message):
    with pytest.raises(PolicyRefused, match=message):
        _policy(**changes)


# --- SD-064 grant binding --------------------------------------------------------------------

def _grant(**changes: object) -> UnlockGrant:
    policy = _policy()
    base = UnlockGrant(grant_id="0f6d4c1e-2b3a-4c5d-8e9f-a0b1c2d3e4f5", kind="autonomous_policy",
                       subject_digest=policy.digest(), not_before=policy.not_before,
                       expires_at=policy.expires_at, max_requests=400, max_writes=40,
                       issued_by="owner@sidedeck", purpose="SD-063 test")
    return replace(base, **changes)  # type: ignore[arg-type]


def test_grant_binding_accepts_only_the_matching_autonomous_grant():
    check_grant_binding(_policy(), _grant(), NOW)
    with pytest.raises(PolicyRefused, match="digest"):
        check_grant_binding(_policy(), _grant(subject_digest="b" * 64), NOW)
    with pytest.raises(PolicyRefused, match="autonomous_policy"):
        check_grant_binding(_policy(), _grant(kind="pilot_release",
                                              expires_at=_policy().not_before + timedelta(hours=2)),
                            NOW)
    with pytest.raises(PolicyRefused, match="window"):
        check_grant_binding(_policy(), _grant(expires_at=_policy().expires_at + timedelta(hours=1)),
                            NOW)
    with pytest.raises(PolicyRefused, match="window"):    # shorter grant would strand positions
        check_grant_binding(_policy(), _grant(expires_at=_policy().expires_at - timedelta(days=2)),
                            NOW)
    with pytest.raises(PolicyRefused, match="active"):
        check_grant_binding(_policy(), _grant(), _policy().expires_at)


# --- entry qualification ---------------------------------------------------------------------

def test_eligible_admitted_signal_becomes_an_unsent_bounded_limit_proposal(ledger):
    proposal = _entry(ledger)
    assert isinstance(proposal, EntryProposal)
    assert proposal.policy_digest == _policy().digest()
    assert proposal.etoro_instrument_id == 1004
    assert proposal.order_type == "limitIOC" and proposal.leverage == 1
    assert proposal.direction == "BUY"
    assert proposal.limit_price == Decimal("502.50")          # ask x 1.005, rounded down
    # Units are capped by the policy's USD 100 max position, not the decision's USD 150.
    assert proposal.units == Decimal("0.1990")
    assert proposal.units * proposal.limit_price <= Decimal("100")
    assert proposal.stop_price == Decimal("480.00")
    assert proposal.submission == "OFFLINE_PROPOSAL_NOT_SUBMITTED"
    assert len(proposal.reference_id) == 32
    assert ledger.pending_entries("SWING") == (proposal.reference_id,)


@pytest.mark.parametrize("make, reason", [
    (lambda s: {"decision": _decision(s, status="WATCHLIST", sizing=None)}, "DECISION_NOT_ELIGIBLE"),
    (lambda s: {"decision": _decision(s, decided_at=NOW - timedelta(minutes=10))}, "DECISION_STALE"),
    (lambda s: {"decision": _decision(s, decided_at=NOW + timedelta(minutes=1))}, "DECISION_STALE"),
    (lambda s: {"decision": _decision(s, track="POSITION")}, "TRACK_NOT_IN_POLICY"),
    (lambda s: {"decision": _decision(s, qualified_signal_ids=())}, "NO_QUALIFIED_SIGNAL"),
    (lambda s: {"signals": ()}, "QUALIFIED_SIGNAL_MISSING"),
    (lambda s: {"admissions": ()}, "STRATEGY_NOT_ADMITTED"),
    (lambda s: {"admissions": (replace(ADMISSIONS[0], evidence_ref="other.md"),)},
     "STRATEGY_NOT_ADMITTED"),
    (lambda s: {"decision": _decision(s, canonical_id="US:XNAS:AAPL")}, "SIGNAL_DECISION_MISMATCH"),
    (lambda s: {"quote": replace(QUOTE, quote_time=NOW - timedelta(seconds=61))}, "QUOTE_STALE"),
    (lambda s: {"quote": replace(QUOTE, quote_time=NOW + timedelta(seconds=1))}, "QUOTE_STALE"),
    (lambda s: {"quote": replace(QUOTE, ask=Decimal("0"))}, "QUOTE_INVALID"),
    (lambda s: {"quote": replace(QUOTE, canonical_id="US:XNAS:AAPL")}, "QUOTE_INSTRUMENT_MISMATCH"),
    (lambda s: {"quote": replace(QUOTE, ask=Decimal("470"))}, "STOP_NOT_BELOW_LIMIT"),
    (lambda s: {"equity": TrackEquity(Decimal("440"), Decimal("500"), Decimal("440"))},
     "MAX_DRAWDOWN_BREACHED"),
    (lambda s: {"equity": TrackEquity(Decimal("470"), Decimal("500"), Decimal("500"))},
     "DAILY_LOSS_LIMIT_BREACHED"),
    (lambda s: {"equity": TrackEquity(Decimal("600"), Decimal("500"), Decimal("500"))},
     "INCONSISTENT_RISK_STATE"),
    (lambda s: {"now": datetime(2026, 11, 2, 13, 0, tzinfo=UTC)}, "POLICY_NOT_ACTIVE"),
    (lambda s: {"now": datetime(2026, 11, 6, 21, 0, tzinfo=UTC)}, "POLICY_NOT_ACTIVE"),
])
def test_entry_refusals(ledger, make, reason):
    signal = _signal()
    result = _entry(ledger, signal=signal, **make(signal))
    assert isinstance(result, Refusal)
    assert reason in result.reasons
    assert ledger.pending_entries("SWING") == ()


def test_unmapped_instrument_is_refused(ledger):
    aapl = replace(_signal(), canonical_id="US:XNAS:AAPL")
    result = _entry(ledger, signal=aapl, decision=_decision(aapl, canonical_id="US:XNAS:AAPL"),
                    quote=replace(QUOTE, canonical_id="US:XNAS:AAPL"))
    assert isinstance(result, Refusal) and result.reasons == ("INSTRUMENT_NOT_IN_POLICY",)


def test_entries_only_inside_the_exchange_session(ledger):
    pre_open = datetime(2026, 11, 2, 14, 10, tzinfo=UTC)       # 09:10 New York
    result = _fresh(ledger, pre_open)
    assert isinstance(result, Refusal) and result.reasons == ("MARKET_CLOSED",)


def test_agent_only_signal_never_qualifies(ledger):
    agent = _signal(source_kind="TRADINGAGENTS", source_id="tradingagents")
    result = _entry(ledger, signal=agent)
    assert isinstance(result, Refusal) and "STRATEGY_NOT_ADMITTED" in result.reasons


def test_strategy_admitted_but_outside_policy_scope_is_refused(ledger):
    other = _signal(source_id="breakout", version="2.0.0")
    admissions = ADMISSIONS + (StrategyAdmission("breakout", "2.0.0", "SWING", "ADMITTED",
                                                 "docs/x.md", 40, True),)
    result = _entry(ledger, signal=other, admissions=admissions)
    assert isinstance(result, Refusal) and "STRATEGY_NOT_IN_POLICY" in result.reasons


def test_duplicate_decision_is_single_use(ledger):
    first = _entry(ledger)
    assert isinstance(first, EntryProposal)
    ledger.resolve(first.reference_id, "NOT_FILLED", NOW)
    again = _entry(ledger)
    assert isinstance(again, Refusal) and "DUPLICATE_ENTRY" in again.reasons


def test_unresolved_pending_entry_blocks_further_entries(ledger):
    assert isinstance(_entry(ledger), EntryProposal)
    result = _fresh(ledger, NOW + timedelta(seconds=30))
    assert isinstance(result, Refusal) and "PENDING_ENTRY_UNRESOLVED" in result.reasons


def test_daily_entry_and_open_position_caps(ledger):
    for minutes in (0, 5):
        proposal = _fresh(ledger, NOW + timedelta(minutes=minutes))
        assert isinstance(proposal, EntryProposal)
        ledger.resolve(proposal.reference_id, "FILLED", NOW + timedelta(minutes=minutes))
    third = _fresh(ledger, NOW + timedelta(minutes=10))
    assert isinstance(third, Refusal) and "DAILY_ENTRY_LIMIT" in third.reasons
    tomorrow = NOW + timedelta(days=1)
    held = tuple(_position(f"{i}" * 32) for i in range(3))
    signal = _signal(generated_at=tomorrow - timedelta(minutes=2))
    capped = _entry(ledger, signal=signal, open_positions=held, now=tomorrow,
                    decision=_decision(signal, decided_at=tomorrow - timedelta(minutes=1)),
                    quote=replace(QUOTE, quote_time=tomorrow - timedelta(seconds=5)))
    assert isinstance(capped, Refusal) and "MAX_OPEN_POSITIONS" in capped.reasons


def test_unresolved_outcome_trips_a_persistent_kill_switch(tmp_path):
    path = tmp_path / "sd063.sqlite3"
    book = PolicyLedger.open(path, _policy().digest())
    proposal = _entry(book)
    assert isinstance(proposal, EntryProposal)
    book.resolve(proposal.reference_id, "UNRESOLVED", NOW)
    assert book.kill_switch_engaged()
    book.close()
    reopened = PolicyLedger.open(path, _policy().digest())
    try:
        assert reopened.kill_switch_engaged()
        result = _fresh(reopened, NOW + timedelta(minutes=1))
        assert isinstance(result, Refusal) and result.reasons == ("KILL_SWITCH_ENGAGED",)
    finally:
        reopened.close()


# --- ledger integrity ------------------------------------------------------------------------

def test_ledger_is_append_only_and_bound_to_one_policy(tmp_path):
    path = tmp_path / "sd063.sqlite3"
    book = PolicyLedger.open(path, _policy().digest())
    book.trip_kill_switch("manual", NOW)
    book.close()
    conn = sqlite3.connect(path)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("UPDATE events SET event = 'ALERT'")
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM events")
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("UPDATE meta SET policy_digest = 'x'")
    finally:
        conn.close()
    with pytest.raises(PolicyRefused, match="different policy"):
        PolicyLedger.open(path, "c" * 64)


def test_ledger_refuses_foreign_sqlite_files(tmp_path):
    path = tmp_path / "etoro_demo.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE baseline_positions (id INTEGER)")
    conn.commit()
    conn.close()
    with pytest.raises(PolicyRefused, match="not an SD-063 policy ledger"):
        PolicyLedger.open(path, _policy().digest())
    conn = sqlite3.connect(path)
    try:
        tables = {n for (n,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert tables == {"baseline_positions"}                  # untouched


def test_resolve_requires_a_known_pending_reference(ledger):
    with pytest.raises(PolicyRefused, match="unknown"):
        ledger.resolve("0" * 32, "FILLED", NOW)
    proposal = _entry(ledger)
    assert isinstance(proposal, EntryProposal)
    with pytest.raises(PolicyRefused, match="outcome"):
        ledger.resolve(proposal.reference_id, "MAYBE", NOW)
    ledger.resolve(proposal.reference_id, "FILLED", NOW)
    with pytest.raises(PolicyRefused, match="already resolved"):
        ledger.resolve(proposal.reference_id, "FILLED", NOW)


# --- exit management -------------------------------------------------------------------------

def _position(ref: str = "e" * 32, **changes: object) -> ManagedPosition:
    base = ManagedPosition(entry_reference=ref, track="SWING", canonical_id=MSFT,
                           etoro_instrument_id=1004, units=Decimal("0.1990"),
                           stop_price=Decimal("480.00"), horizon_max_days=2,
                           opened_at=NOW, lineage_verified=True)
    return replace(base, **changes)  # type: ignore[arg-type]


def _bid(price: str, at: datetime) -> dict[str, ExitQuote]:
    return {MSFT: ExitQuote(MSFT, Decimal(price), at - timedelta(seconds=5))}


def test_stop_breach_proposes_a_full_close(ledger):
    later = NOW + timedelta(hours=2)
    plan = plan_exits(_policy(), ledger, (_position(),), _bid("479.99", later), later)
    assert [(e.reason, e.units) for e in plan.exits] == [("STOP_BREACHED", Decimal("0.1990"))]
    assert plan.exits[0].submission == "OFFLINE_PROPOSAL_NOT_SUBMITTED"
    assert plan.alerts == ()
    assert ledger.pending_exits() == (plan.exits[0].reference_id,)


def test_horizon_counts_exchange_sessions_not_calendar_days(ledger):
    tuesday = datetime(2026, 11, 3, 15, 0, tzinfo=UTC)
    assert plan_exits(_policy(), ledger, (_position(),), _bid("500", tuesday), tuesday).exits == ()
    wednesday = datetime(2026, 11, 4, 15, 0, tzinfo=UTC)
    plan = plan_exits(_policy(), ledger, (_position(),), _bid("500", wednesday), wednesday)
    assert [e.reason for e in plan.exits] == ["HORIZON_REACHED"]


def test_positions_are_flattened_before_policy_expiry(ledger):
    late = datetime(2026, 11, 6, 15, 0, tzinfo=UTC)
    plan = plan_exits(_policy(), ledger, (_position(horizon_max_days=10),), _bid("500", late), late)
    assert [e.reason for e in plan.exits] == ["POLICY_EXPIRY_FLATTEN"]


def test_exit_is_proposed_once_while_pending(ledger):
    later = NOW + timedelta(hours=2)
    first = plan_exits(_policy(), ledger, (_position(),), _bid("470", later), later)
    assert len(first.exits) == 1
    second = plan_exits(_policy(), ledger, (_position(),), _bid("470", later), later)
    assert second.exits == () and second.alerts == (f"EXIT_PENDING:{'e' * 32}",)


def test_unattributed_protected_or_stale_positions_raise_alerts_not_exits(ledger):
    later = NOW + timedelta(hours=2)
    positions = (_position("a" * 32, lineage_verified=False),
                 _position("b" * 32, etoro_instrument_id=1001),
                 _position("c" * 32))
    quotes = {MSFT: ExitQuote(MSFT, Decimal("470"), later - timedelta(minutes=5))}
    plan = plan_exits(_policy(), ledger, positions, quotes, later)
    assert plan.exits == ()
    assert plan.alerts == (f"UNATTRIBUTED_POSITION:{'a' * 32}",
                           f"PROTECTED_POSITION_NEVER_MANAGED:{'b' * 32}",
                           f"QUOTE_UNAVAILABLE:{'c' * 32}")


def test_kill_switch_stops_exit_proposals_too(ledger):
    ledger.trip_kill_switch("operator", NOW)
    later = NOW + timedelta(hours=2)
    plan = plan_exits(_policy(), ledger, (_position(),), _bid("470", later), later)
    assert plan.exits == () and plan.alerts == ("KILL_SWITCH_ENGAGED",)


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
