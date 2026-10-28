"""SD-152 Bundle O consolidated offline regression acceptance entrypoint.

This suite intentionally invokes existing tests rather than reimplementing the
simulation. It is not broker qualification, a release grant, or an external audit.
Run with: pytest -q tests/test_sd152_bundle_o_acceptance.py
"""
from __future__ import annotations

import pytest

import test_sd140_sd152_offline_swing_runner as scenarios


@pytest.mark.parametrize("scenario", [
    scenarios.test_sd140_sd152_two_sessions_open_and_close_via_real_fake_adapter,
    scenarios.test_sd152_twenty_restart_attempts_do_not_repeat_simulated_entry,
    scenarios.test_sd152_repeated_restart_after_unresolved_fence_never_reposts,
    scenarios.test_sd152_ambiguous_close_ten_restarts_preserve_single_exit_post,
    scenarios.test_sd152_close_ledger_mismatch_blocks_twelve_restarts_without_replay,
    scenarios.test_sd152_tampered_final_close_units_blocks_ten_clean_slot_restarts,
    scenarios.test_sd152_inconsistent_remaining_units_never_rearms_synthetic_entry,
    scenarios.test_sd152_partial_entry_requires_manual_recovery_before_second_slot,
    scenarios.test_sd152_partial_close_ten_restarts_never_infer_flat_or_repost,
], ids=lambda test: test.__name__.removeprefix("test_"))
def test_bundle_o_offline_acceptance_scenarios(setup, scenario):
    scenario(setup)


@pytest.fixture
def setup(tmp_path):
    # Keep one fresh fixture per parametrized scenario: never share ledgers
    # across fault cases. The underlying test module owns the lifecycle.
    iterator = scenarios.setup.__wrapped__(tmp_path)
    value = next(iterator)
    try:
        yield value
    finally:
        try:
            next(iterator)
        except StopIteration:
            pass
