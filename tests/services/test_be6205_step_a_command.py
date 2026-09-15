# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid

from giljo_mcp.services.protocol_sections.chapters_chain import (
    _build_ch_capability,
    _build_ch_chain_drive,
)


def _drive(execution_mode: str = "claude_code_cli") -> str:
    return _build_ch_chain_drive(
        run_id="RUN123",
        resolved_order=["p1", "p2"],
        current_index=0,
        execution_mode=execution_mode,
        conductor_agent_id="cond-1",
        job_id="job-1",
    )




def test_step_a_has_windows_direct_wt_command() -> None:
    chapter = _drive("multi_terminal")
    assert "wt -w 0 new-tab --title 'giljo sub-orch' -d \"$PWD\"" in chapter, "STEP A carries the direct wt command"
    assert "claude --dangerously-skip-permissions" in chapter


def test_step_a_has_linux_direct_gnome_command() -> None:
    chapter = _drive("multi_terminal")
    assert 'gnome-terminal --working-directory="$PWD"' in chapter, "STEP A carries the direct gnome-terminal command"
    assert "claude --dangerously-skip-permissions" in chapter


def test_step_a_regression_no_nested_no_startprocess_no_files() -> None:
    chapter = _drive("claude_code_cli")
    assert "Start-Process wt -ArgumentList '" not in chapter, "the nested single-string ArgumentList form is the bug"
    assert 'powershell.exe -Command "Start-Process wt' not in chapter
    assert "launch.ps1" not in chapter and "suborch.txt" not in chapter, "file-less: no launcher/prompt FILES"
    assert "<YOUR_CWD>" not in chapter, "$PWD self-resolves the cwd; no placeholder for the agent to mangle"


def test_step_a_has_verbatim_directive() -> None:
    chapter = _drive("claude_code_cli")
    low = chapter.lower()
    assert "verbatim" in low, "STEP A must tell the conductor to copy the launcher verbatim"
    assert "-argumentlist" in low, "the directive must explicitly forbid -ArgumentList reformatting"
    assert "do not" in low


def test_step_a_substitutes_uuid_placeholders_inline() -> None:
    chapter = _drive("claude_code_cli")
    assert "<P_i>" in chapter
    assert "<SUB_ORCH_JOB_ID>" in chapter


def test_step_a_keeps_idempotent_reuse_resolution() -> None:
    chapter = _drive("claude_code_cli")
    low = chapter.lower()
    assert "get_workflow_status" in chapter
    assert "idempotent" in low
    assert "already minted" in low or "already-minted" in low
    assert "never mints a duplicate" in low or "never a duplicate" in low


def test_step_a_fails_loud_on_headless() -> None:
    chapter = _drive("claude_code_cli")
    assert "DISPLAY" in chapter
    assert "WAYLAND_DISPLAY" in chapter
    assert "re-stage" in chapter.lower()




def test_ch_capability_subagent_spawns_suborch_in_fresh_terminal() -> None:
    cap = _build_ch_capability(execution_mode="claude_code_cli", can_spawn_terminals=True)
    low = cap.lower()
    assert "fresh" in low and "terminal" in low, "sub-orch spawn is always a fresh terminal"
    assert "run each p_i as a real task()" not in low, "the old Task()-spawns-the-sub-orch language must be gone"
    assert "worker" in low
    assert "REAL Task()" in cap, "Task() is the sub-orch's WORKER mechanism in subagent modes"


def test_ch_capability_multi_terminal_spawns_suborch_in_fresh_terminal() -> None:
    cap = _build_ch_capability(execution_mode="multi_terminal", can_spawn_terminals=True)
    low = cap.lower()
    assert "fresh" in low and "terminal" in low
    assert "worker" in low




def test_solo_protocol_has_no_terminal_spawn_leak() -> None:
    from giljo_mcp.services.protocol_builder import _build_orchestrator_protocol

    solo = _build_orchestrator_protocol(
        cli_mode=True,
        project_id=str(uuid.uuid4()),
        orchestrator_id="job-solo",
        tenant_key="tk_solo",
        include_implementation_reference=False,
        chain_ctx=None,
    )
    blob = "\n".join(str(v) for v in solo.values())
    assert "launch.ps1" not in blob, "solo render must not leak the conductor launcher artifact"
    assert "gnome-terminal" not in blob
    assert "CH_CHAIN_DRIVE" not in blob
