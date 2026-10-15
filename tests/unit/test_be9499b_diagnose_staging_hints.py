# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.services.diagnose_staging_hints import STAGING_STUCK_HINTS, compute_stuck_conditions


def _counts(**overrides) -> dict:
    base = {"total": 0, "completed": 0, "blocked": 0, "active": 0, "silent": 0}
    base.update(overrides)
    return base


class TestStagingStuckHints:
    def test_staged_and_staging_have_distinct_hints(self):
        assert STAGING_STUCK_HINTS["staged"] != STAGING_STUCK_HINTS["staging"]
        assert "unstage_project" in STAGING_STUCK_HINTS["staged"][0]
        assert "unstage_project" in STAGING_STUCK_HINTS["staging"][0]

    def test_every_stuck_hint_names_unstage_and_how_to_abandon(self):
        for hints in STAGING_STUCK_HINTS.values():
            joined = " ".join(hints)
            assert "unstage_project" in joined
            assert "status='cancelled'" in joined
            assert "restage_project" not in joined
            assert "cancel_project_staging" not in joined


class TestComputeStuckConditions:
    def test_no_agents_and_staged_names_unstage(self):
        stuck, suggested = compute_stuck_conditions(
            execution_mode="claude_code_cli",
            is_terminal=False,
            counts=_counts(total=0),
            all_finished=False,
            staging_status="staged",
            any_awaiting_user=False,
        )
        assert "no_agents_spawned" in stuck
        assert any("unstage_project" in s for s in suggested)

    def test_no_agents_and_staging_names_unstage(self):
        stuck, suggested = compute_stuck_conditions(
            execution_mode="claude_code_cli",
            is_terminal=False,
            counts=_counts(total=0),
            all_finished=False,
            staging_status="staging",
            any_awaiting_user=False,
        )
        assert "no_agents_spawned" in stuck
        assert any("unstage_project" in s for s in suggested)

    def test_no_agents_and_no_staging_status_has_no_reverse_gear_hint(self):
        stuck, suggested = compute_stuck_conditions(
            execution_mode="claude_code_cli",
            is_terminal=False,
            counts=_counts(total=0),
            all_finished=False,
            staging_status=None,
            any_awaiting_user=False,
        )
        assert "no_agents_spawned" in stuck
        assert suggested == []

    def test_terminal_project_suppresses_no_agents_stuck_condition(self):
        stuck, _suggested = compute_stuck_conditions(
            execution_mode=None,
            is_terminal=True,
            counts=_counts(total=0),
            all_finished=False,
            staging_status="staging",
            any_awaiting_user=False,
        )
        assert "no_agents_spawned" not in stuck

    def test_missing_execution_mode_suggests_staging(self):
        stuck, suggested = compute_stuck_conditions(
            execution_mode=None,
            is_terminal=False,
            counts=_counts(total=1, active=1),
            all_finished=False,
            staging_status=None,
            any_awaiting_user=False,
        )
        assert "execution_mode_not_selected" in stuck
        assert any("stage the project" in s for s in suggested)

    def test_all_finished_suggests_closeout(self):
        stuck, suggested = compute_stuck_conditions(
            execution_mode="claude_code_cli",
            is_terminal=False,
            counts=_counts(total=2, completed=2, active=0),
            all_finished=True,
            staging_status=None,
            any_awaiting_user=False,
        )
        assert "all_agents_finished_project_still_open" in stuck
        assert any("write_project_closeout" in s for s in suggested)

    def test_blocked_and_silent_and_awaiting_user_all_flag_independently(self):
        stuck, suggested = compute_stuck_conditions(
            execution_mode="claude_code_cli",
            is_terminal=False,
            counts=_counts(total=3, active=3, blocked=1, silent=1),
            all_finished=False,
            staging_status=None,
            any_awaiting_user=True,
        )
        assert {"blocked_agents", "silent_agents", "awaiting_user_approval"} <= set(stuck)
        assert any("set_agent_status" in s for s in suggested)
        assert any("approvals" in s for s in suggested)
