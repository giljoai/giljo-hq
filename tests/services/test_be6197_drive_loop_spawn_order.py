# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re

from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_chain_drive


def _drive() -> str:
    return _build_ch_chain_drive(
        run_id="r",
        resolved_order=["p1", "p2", "p3"],
        current_index=0,
        execution_mode="claude_code_cli",
        conductor_agent_id="c1",
        job_id="j1",
    )


def test_spawn_is_the_release_no_launch_gate() -> None:
    chapter = _drive()
    assert "spawn_job" in chapter, "the conductor releases each project by spawning its sub-orch"
    assert "launch_implementation" not in chapter, (
        "§14: the conductor no longer crosses a per-project gate — launch_implementation is gone from the drive"
    )


def test_no_staging_complete_wait() -> None:
    chapter = _drive()
    low = chapter.lower()
    assert "staging_complete" not in chapter, "the removed STEP B staging-complete wait must be gone"
    assert "wait for p_i to reach staging-complete" not in low, "the staging-complete wait step must be gone"


def test_polls_closeout() -> None:
    chapter = _drive()
    assert "project_closeout_at" in chapter
    flat = re.sub(r"\s+", " ", chapter.lower())
    assert 'do not advance on status "complete" alone' in flat, (
        "the prose must warn against advancing on status 'complete' alone"
    )


def test_crash_resume_respawn() -> None:
    chapter = _drive()
    resume_start = chapter.find("CRASH-RESUME")
    assert resume_start != -1, "the CRASH-RESUME section must be present"
    resume = chapter[resume_start:]
    low = resume.lower()
    assert "respawn" in low, "crash-resume must instruct RESPAWN of the current sub-orch"
    assert "spawn_job" in resume, "respawn routes through spawn_job"
    assert "launch the next" in low or "merely" in low, (
        "the respawn guidance must explicitly contrast with only launching the next project"
    )


def test_conductor_precedence_and_finale_preserved() -> None:
    chapter = _drive()
    assert "CONDUCTOR_CHAIN_INCOMPLETE" in chapter
    assert "does not apply" in chapter.lower()
    assert "SERIES SUMMARY" in chapter
    assert 'tags=["chore"]' in chapter
    assert "complete_job" in chapter
    assert "TOOLS ONLY" in chapter
    assert "batch-unlock" in chapter
