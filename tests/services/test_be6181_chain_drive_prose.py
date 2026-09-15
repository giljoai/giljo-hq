# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.services.protocol_sections import chapters_chain
from giljo_mcp.services.protocol_sections.chapters_chain import (
    _build_ch_chain_drive,
    _build_ch_chain_staging,
)


def _drive() -> str:
    return _build_ch_chain_drive(
        run_id="run-x",
        resolved_order=["head", "p2", "p3"],
        current_index=0,
        execution_mode="claude_code_cli",
        conductor_agent_id="cond-1",
        job_id="job-77",
    )


def test_drive_advances_via_spawn_not_launch() -> None:
    chapter = _drive()
    assert "spawn_job" in chapter, "the conductor advances by spawning the next project's sub-orch"
    assert "launch_implementation" not in chapter, "§14: the conductor no longer crosses a per-project gate"


def test_drive_has_no_raw_http_sequence_run_instruction() -> None:
    chapter = _drive()
    assert "/api/v1/sequence-runs" not in chapter
    assert "curl" not in chapter
    assert "PATCH /" not in chapter
    assert "GET /" not in chapter


def test_drive_has_conductor_precedence_clause() -> None:
    chapter = _drive()
    low = chapter.lower()
    assert "does not apply" in low or "does NOT apply" in chapter
    assert "complete_job becomes valid only" in low, (
        "the precedence clause must state complete_job becomes valid ONLY at the series-summary finale"
    )
    assert "CONDUCTOR_CHAIN_INCOMPLETE" in chapter


def test_drive_points_backout_at_dashboard_buttons() -> None:
    chapter = _drive()
    assert "Deactivate Chain" in chapter
    assert "Reset" in chapter
    assert "Cancel" in chapter
    assert "Delete" in chapter
    assert "TERMINATE_CHAIN" not in chapter, "BE-6186: the inert TERMINATE_CHAIN prose must be gone"


def test_drive_spawns_then_polls_closeout() -> None:
    chapter = _drive()
    idx_spawn = chapter.find("spawn_job")
    idx_closeout = chapter.find("project_closeout_at")
    assert idx_spawn != -1, "STEP A (spawn) must be present"
    assert idx_closeout != -1, "STEP B must poll project_closeout_at"
    assert idx_spawn < idx_closeout, "spawn (release) must precede the closeout poll"
    assert "launch_implementation" not in chapter, "§14: no per-project launch gate in the drive"
    assert "staging_complete" not in chapter, "§14: no staging-complete wait step in the drive"


def test_no_tdd_implementor_ghost_in_chapter_modules() -> None:
    import inspect

    source = inspect.getsource(chapters_chain)
    assert "tdd-implementor" not in source
    assert "tdd_implementor" not in source


def test_staging_chapter_still_emits_short_mode_and_stop() -> None:
    chapter = _build_ch_chain_staging(
        run_id="run-x", resolved_order=["head", "p2"], execution_mode="claude_code_cli", job_id="job-77"
    )
    assert 'mode="claude"' in chapter
    assert "claude_code_cli" not in chapter
