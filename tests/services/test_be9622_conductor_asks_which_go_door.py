# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.services.job_completion_service import JobCompletionService


def _ask_markers(text: str) -> str:
    return text.lower()


def test_conductor_staging_end_next_action_asks_which_door() -> None:
    phase, _msg, next_action = JobCompletionService._phase_response(
        is_staging_end=True, is_closeout_phase=False, is_conductor=True, is_chain_member_suborch=False
    )
    assert phase == "staging_end"
    low = _ask_markers(next_action["why"])
    assert "ask" in low, f"the conductor must be told to ASK the user which door: {next_action['why']!r}"
    assert "implement chain" in low, "the dashboard door must be named in the question"
    assert '"go"' in low or " go " in low or "say go" in low, "the chat door must be named in the question"
    assert "explicit go" in low
    assert next_action["tool"] is None


def test_conductor_staging_directive_asks_which_door() -> None:
    directive = JobCompletionService._staging_directive_for(False, is_conductor=True)
    assert directive.action == "STOP", "the halt is unchanged"
    low = _ask_markers(directive.message + " " + directive.next_action["why"])
    assert "ask" in low, f"the directive must tell the conductor to ask: {directive.message!r}"
    assert "implement chain" in low


def test_chain_staging_chapter_asks_which_door() -> None:
    from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_chain_staging

    chapter = _build_ch_chain_staging(
        run_id="run-ask", resolved_order=["p1", "p2"], execution_mode="multi_terminal", job_id="job-ask"
    )
    low = chapter.lower()
    assert "ask the user" in low, "the HALT block must tell the conductor to ASK which door, not to announce one"
    assert "halt after staging" in low
    assert "explicit go" in low
    assert "implement chain" in low


def test_chain_drive_banner_asks_which_door() -> None:
    from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_chain_drive

    chapter = _build_ch_chain_drive(
        run_id="run-ask",
        resolved_order=["p1", "p2"],
        current_index=0,
        execution_mode="multi_terminal",
        conductor_agent_id="cond-ask",
        job_id="job-ask",
    )
    low = chapter.lower()
    assert "ask the user" in low, "the drive banner must name the choice as the user's, not assume a door"
    assert "proceed only after the user's explicit go" in low, "the gate wording is unchanged"
