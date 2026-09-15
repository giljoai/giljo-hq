# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re

from giljo_mcp.domain.todo_kinds import CLOSEOUT_TODO_PATTERN
from giljo_mcp.schemas.service_responses import build_next_action
from giljo_mcp.services.job_completion_service import JobCompletionService
from giljo_mcp.services.memory_entry_write_validator import CONTROLLED_TAG_VOCABULARY
from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_chain_drive


def _drive() -> str:
    return _build_ch_chain_drive(
        run_id="run-x",
        resolved_order=["head", "p2", "p3"],
        current_index=0,
        execution_mode="claude_code_cli",
        conductor_agent_id="cond-1",
        job_id="job-77",
    )




def test_series_summary_uses_valid_tag() -> None:
    chapter = _drive()
    assert "chain-summary" not in chapter
    assert 'tags=["chore"]' in chapter
    assert "chore" in CONTROLLED_TAG_VOCABULARY


def test_series_summary_still_renders_write_memory_entry() -> None:
    chapter = _drive()
    assert "write_memory_entry" in chapter
    assert "SERIES SUMMARY" in chapter




def test_conductor_complete_next_action_chain_aware() -> None:
    phase, _message, next_action = JobCompletionService._phase_response(
        is_staging_end=False,
        is_closeout_phase=True,
        is_conductor=True,
    )
    assert phase == "closeout"
    assert next_action["tool"] == "write_memory_entry"
    assert "Chain complete" in next_action["why"]
    assert "series summary" in next_action["why"]


def test_solo_closeout_next_action_byte_identical() -> None:
    expected = build_next_action(
        tool="write_project_closeout",
        why=(
            "Call write_project_closeout() to write the project closeout (orchestrators "
            "coordinate, they do not commit code)."
        ),
    )
    explicit = JobCompletionService._phase_response(is_staging_end=False, is_closeout_phase=True, is_conductor=False)
    default = JobCompletionService._phase_response(is_staging_end=False, is_closeout_phase=True)
    assert explicit == default
    assert explicit == ("closeout", "Orchestrator job completed; closeout recorded.", expected)


def test_conductor_closeout_swap_does_not_bleed_into_staging_end() -> None:
    staging = JobCompletionService._phase_response(is_staging_end=True, is_closeout_phase=False, is_conductor=True)
    assert staging[0] == "staging_end"
    assert staging[2]["tool"] != "write_project_closeout", "the closeout swap must not bleed into staging-end"
    assert "EXPLICIT GO" in staging[2]["why"], "staging-end conductor must be told to wait for the user's explicit GO"




def test_self_complete_todo_auto_acked() -> None:
    assert CLOSEOUT_TODO_PATTERN.search("Conductor self-complete") is not None
    assert CLOSEOUT_TODO_PATTERN.search("conductor self_complete") is not None
    assert CLOSEOUT_TODO_PATTERN.search("Self Complete the chain") is not None


def test_existing_closeout_keywords_still_match() -> None:
    assert CLOSEOUT_TODO_PATTERN.search("Closeout: write the 360") is not None
    assert CLOSEOUT_TODO_PATTERN.search("call complete_job") is not None
    assert CLOSEOUT_TODO_PATTERN.search("close_project and update memory") is not None


def test_normal_todo_not_auto_acked() -> None:
    assert CLOSEOUT_TODO_PATTERN.search("Implement the rate limiter") is None
    assert CLOSEOUT_TODO_PATTERN.search("Review the PR and merge") is None
    assert CLOSEOUT_TODO_PATTERN.search("Mark the feature complete in the UI") is None




def _suborch() -> str:
    from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_sub_orchestrator

    return _build_ch_sub_orchestrator(run_id="run-x", position=2, n_projects=3, execution_mode="claude_code_cli")


def test_drive_step_b_has_real_wake_mechanism() -> None:
    chapter = _drive()
    flat = re.sub(r"\s+", " ", chapter.lower())
    assert "run_in_background" in chapter, "STEP B must name the background-run wake mechanism"
    assert "sleep 1" in chapter, "STEP B must reuse the `sleep 1 N` harness workaround idiom"
    assert "dashboard label" in flat, "STEP B must warn set_agent_status is only the dashboard label"
    assert "stalls the whole chain" in flat, "STEP B must warn that sleep-and-stop stalls the chain"


def test_drive_step_b_reads_hub_via_thread_history() -> None:
    chapter = _drive()
    low = chapter.lower()
    assert "get_thread_history" in chapter, "STEP B must read the Hub via get_thread_history"
    assert "unread_only=true" in chapter, "STEP B must use the unread_only cursor"
    assert "mark_read=true" in chapter, "STEP B must use the mark_read cursor"
    assert "receive_messages" not in chapter, "receive_messages is retired (bus hard-removed)"
    assert "one messaging surface" in low, "STEP B must state there is only one messaging surface now"


def test_drive_step_b_hub_poll_uses_unread_cursor_single_surface() -> None:
    chapter = _drive()
    flat = re.sub(r"\s+", " ", chapter.lower())
    assert "unread_only=true" in chapter, "STEP B must use the unread_only cursor"
    assert "mark_read=true" in chapter, "STEP B must use the mark_read cursor"
    assert "only what's new since your last read" in flat, (
        "STEP B must say the cursor pulls only what's new since the last read"
    )
    assert "separate channels" not in flat, "the retired 'separate channels' framing must not reappear"
    assert "cannot drop either channel" not in flat, "the retired two-channel framing must not reappear"
    assert "after_message_id" not in chapter, "the manual after_message_id cursor is retired in favor of unread_only"
    assert "one messaging surface" in flat, "STEP B must state there is a single messaging surface"


def test_series_summary_clears_drive_todos_and_states_caps() -> None:
    chapter = _drive()
    low = chapter.lower()
    assert "clear your drive todos first" in low, "the finale must instruct clearing drive TODOs first"
    assert "orchestrator_incomplete_todos" in chapter, "the finale must name the gate it avoids"
    assert "1500" in chapter and "250" in chapter, "the summary/250-char caps must be surfaced before the call"


def test_suborch_posts_done_only_after_write_project_closeout() -> None:
    chapter = _suborch()
    wpc = chapter.find("write_project_closeout")
    done = chapter.find("ONLY AFTER write_project_closeout RETURNS")
    assert wpc != -1 and done != -1, "step 7 must name write_project_closeout and the after-return Hub post"
    assert wpc < done, "the Hub DONE post must be instructed AFTER write_project_closeout"


def test_conductor_inbox_poll_has_background_wake() -> None:
    chapter = _build_ch_chain_drive(
        run_id="run-77",
        resolved_order=["p1", "p2"],
        current_index=0,
        execution_mode="multi_terminal",
        conductor_agent_id="cond-1",
        job_id="job-77",
    )
    flat = re.sub(r"\s+", " ", chapter.lower())
    assert "run_in_background" in chapter, "the conductor loop must use the background-wake idiom"
    assert "sleep 1" in chapter
    assert ("not re-invoke you" in flat) or ("not wake you" in flat), (
        "must warn set_agent_status will not wake/re-invoke the conductor on its own"
    )
    assert "ready_to_advance" in chapter, "the loop must advance on ready_to_advance"
    assert "receive_messages" not in chapter, "receive_messages is retired (bus hard-removed)"
    assert "get_thread_history" in chapter, "the folded directive inbox poll must live in the same drive loop"
