# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9083b — lifecycle breadcrumb footer builders (pure-function unit cells).

The footers ride on the lifecycle ACTION tools (spawn_job, complete_job,
update_project_mission). Each footer is a short (<= 10 line) plain-prose
breadcrumb whose UI claims trace to the TOOL_UI_EVENT_MAP reference doc.

These pure builders are exercised here for EVERY (tool x phase x role) cell —
including the chain-conductor and chain sub-orch cells that are awkward to seed
through the MCP transport. The transport-boundary companion
(tests/integration/test_be9083b_lifecycle_footers_mcp_boundary.py) proves the
seedable cells end to end.

Edition Scope: Both.
"""

from __future__ import annotations

from giljo_mcp.services.protocol_survival import (
    build_complete_job_footer,
    build_mission_update_footer,
    build_spawn_footer,
)


def _line_count(footer: str) -> int:
    # Prose footers are a single paragraph; "<= 10 lines" is the budget even if a
    # renderer word-wraps. We assert the authored newline count stays tiny.
    return footer.count("\n") + 1


# ---------------------------------------------------------------------------
# spawn_job — fires agent:created (a new JobsTab row)
# ---------------------------------------------------------------------------


def test_spawn_footer_staging_says_inert_until_implementation():
    footer = build_spawn_footer(phase="staging")
    assert "agent:created" in footer
    assert "JobsTab" in footer
    assert "INERT" in footer
    assert "do NOT" in footer.lower() or "do not" in footer.lower()
    assert _line_count(footer) <= 10


def test_spawn_footer_implementation_says_ready_to_launch():
    footer = build_spawn_footer(phase="implementation")
    assert "agent:created" in footer
    assert "ready to launch" in footer
    assert "get_workflow_status" in footer
    assert "INERT" not in footer
    assert _line_count(footer) <= 10


def test_spawn_footer_none_phase_defaults_to_staging_wording():
    # None (unknown phase) must fall back to the safe staging breadcrumb, never crash.
    assert build_spawn_footer(phase=None) == build_spawn_footer(phase="staging")


# ---------------------------------------------------------------------------
# update_project_mission — fires project:mission_updated
# ---------------------------------------------------------------------------


def test_mission_update_footer_staging_points_at_spawn():
    footer = build_mission_update_footer(phase="staging")
    assert "project:mission_updated" in footer
    assert "mission panel" in footer
    assert "spawn_job" in footer
    assert _line_count(footer) <= 10


def test_mission_update_footer_implementation_is_a_refinement():
    footer = build_mission_update_footer(phase="implementation")
    assert "project:mission_updated" in footer
    assert "refinement" in footer
    assert "spawn_job" not in footer
    assert _line_count(footer) <= 10


# ---------------------------------------------------------------------------
# complete_job — three hidden phases x chain role
# ---------------------------------------------------------------------------


def test_complete_footer_staging_end_solo_points_at_human_implement():
    footer = build_complete_job_footer(phase="staging_end")
    assert "staging_end" in footer
    assert "staging-complete" in footer
    assert "waiting" in footer  # CE-0032: chip is waiting, not complete
    assert "Implement" in footer
    assert "Do NOT write the closeout" in footer
    assert _line_count(footer) <= 10


def test_complete_footer_staging_end_chain_suborch_says_already_advanced():
    footer = build_complete_job_footer(phase="staging_end", is_chain_member_suborch=True)
    assert "CHAIN member" in footer
    assert "ALREADY advanced" in footer
    assert "get_job_mission" in footer
    assert "protocol_etag" in footer
    # A chain member has NO human Implement gate.
    assert "presses Implement" not in footer
    assert _line_count(footer) <= 10


def test_complete_footer_staging_end_conductor_halts_for_go():
    footer = build_complete_job_footer(phase="staging_end", is_conductor=True)
    assert "CONDUCTOR" in footer
    assert "HALT" in footer
    assert "GO" in footer
    assert "Implement" not in footer
    assert _line_count(footer) <= 10


def test_complete_footer_closeout_solo_points_at_write_project_closeout():
    footer = build_complete_job_footer(phase="closeout")
    assert "closeout" in footer
    assert "CloseoutModal" in footer
    assert "write_project_closeout" in footer
    assert _line_count(footer) <= 10


def test_complete_footer_closeout_conductor_points_at_series_summary():
    footer = build_complete_job_footer(phase="closeout", is_conductor=True)
    assert "conductor" in footer.lower()
    assert "write_memory_entry" in footer
    assert "write_project_closeout" not in footer  # conductor owns no project
    assert _line_count(footer) <= 10


def test_complete_footer_deliverable_says_no_further_action():
    footer = build_complete_job_footer(phase="deliverable")
    assert "deliverable" in footer
    assert "complete (green)" in footer
    assert "No further action" in footer
    assert _line_count(footer) <= 10


def test_conductor_flag_wins_over_suborch_flag_for_staging_end():
    # Defensive: if both flags were ever set, the conductor cell (project-less)
    # takes precedence — matching _phase_response ordering.
    footer = build_complete_job_footer(phase="staging_end", is_conductor=True, is_chain_member_suborch=True)
    assert "CONDUCTOR" in footer
    assert "HALT" in footer
