# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.services.protocol_survival import (
    build_complete_job_footer,
    build_mission_update_footer,
    build_spawn_footer,
)


def _line_count(footer: str) -> int:
    return footer.count("\n") + 1




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
    assert build_spawn_footer(phase=None) == build_spawn_footer(phase="staging")




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




def test_complete_footer_staging_end_solo_points_at_human_implement():
    footer = build_complete_job_footer(phase="staging_end")
    assert "staging_end" in footer
    assert "staging-complete" in footer
    assert "waiting" in footer
    assert "Implement" in footer
    assert "Do NOT write the closeout" in footer
    assert _line_count(footer) <= 10


def test_complete_footer_staging_end_chain_suborch_says_already_advanced():
    footer = build_complete_job_footer(phase="staging_end", is_chain_member_suborch=True)
    assert "CHAIN member" in footer
    assert "ALREADY advanced" in footer
    assert "get_job_mission" in footer
    assert "protocol_etag" in footer
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
    assert "write_project_closeout" not in footer
    assert _line_count(footer) <= 10


def test_complete_footer_deliverable_says_no_further_action():
    footer = build_complete_job_footer(phase="deliverable")
    assert "deliverable" in footer
    assert "complete (green)" in footer
    assert "No further action" in footer
    assert _line_count(footer) <= 10


def test_conductor_flag_wins_over_suborch_flag_for_staging_end():
    footer = build_complete_job_footer(phase="staging_end", is_conductor=True, is_chain_member_suborch=True)
    assert "CONDUCTOR" in footer
    assert "HALT" in footer
