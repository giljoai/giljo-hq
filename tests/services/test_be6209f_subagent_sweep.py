# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from pathlib import Path

from giljo_mcp.platform_registry import is_subagent_render
from giljo_mcp.services.protocol_builder import _build_orchestrator_protocol
from giljo_mcp.services.protocol_sections.agent_protocol import _generate_agent_protocol


_GOLDEN = Path(__file__).parent / "_be6209f_golden_multi_terminal.txt"

_SUBAGENT_TOOLS = ("claude-code", "codex", "gemini")

_MULTI_TERMINAL_ONLY = (
    "Go to that agent's terminal",
    "start it from the dashboard",
    "dashboard Play buttons",
    "Open a new session with your AI and paste this prompt",
    "locked Play button",
    "Copy agent prompts from the dashboard to start them.",
    "Tell user to paste the new prompt in a NEW terminal",
    "**If waiting for user to start agents (multi-terminal):**",
)


def _render(*, tool: str, exec_mode: str, staging: bool, conductor: bool = False) -> str:
    chapters = _build_orchestrator_protocol(
        cli_mode=(tool != "multi_terminal"),
        project_id="PID-golden",
        orchestrator_id="OID-golden",
        tenant_key="TK-golden",
        include_implementation_reference=not staging,
        tool=tool,
    )
    body = _generate_agent_protocol(
        job_id="JID-golden",
        tenant_key="TK-golden",
        agent_name="orchestrator",
        agent_id="AID-golden",
        execution_mode=exec_mode,
        job_type="orchestrator",
        tool=tool,
        is_chain_conductor=conductor,
    )
    parts: list[str] = []
    for key, value in chapters.items():
        parts.append(f"<<<CHAPTER:{key}>>>")
        parts.append(str(value))
    parts.append("<<<BODY>>>")
    parts.append(body)
    return "\n".join(parts)


def _multi_terminal_golden_render() -> str:
    blocks: list[str] = []
    for staging in (False, True):
        tag = "STAGING" if staging else "IMPL"
        blocks.append(f"########## MULTI_TERMINAL {tag} ##########")
        blocks.append(_render(tool="multi_terminal", exec_mode="multi_terminal", staging=staging))
    return "\n".join(blocks)




def test_subagent_render_has_no_multi_terminal_only_strings() -> None:
    for tool in _SUBAGENT_TOOLS:
        for staging in (False, True):
            rendered = _render(tool=tool, exec_mode=tool, staging=staging)
            for needle in _MULTI_TERMINAL_ONLY:
                assert needle not in rendered, (
                    f"{tool} ({'staging' if staging else 'impl'}) leaked multi-terminal-only string: {needle!r}"
                )


def test_newly_conditioned_strings_present_in_multi_terminal() -> None:
    multi = _render(tool="multi_terminal", exec_mode="multi_terminal", staging=False)
    assert "Go to that agent's terminal and say: the orchestrator responded" in multi
    assert "Verification agent spawned, start it from the dashboard." in multi
    assert "Multi-terminal mode gates on\nphase via the dashboard Play buttons; subagent modes do not." in multi


def test_subagent_self_spawn_phrasing_replaces_the_relay_line() -> None:
    sub = _render(tool="claude-code", exec_mode="claude-code", staging=False)
    assert "reads your reply on its next get_thread_history poll" in sub
    assert "its VERY FIRST call MUST be" in sub




def test_multi_terminal_render_is_byte_identical_to_golden() -> None:
    golden = _GOLDEN.read_text(encoding="utf-8")
    assert _multi_terminal_golden_render() == golden




def test_is_subagent_render_is_the_canonical_signal() -> None:
    assert is_subagent_render("multi_terminal") is False
    assert is_subagent_render("") is False
    assert is_subagent_render(None) is False
    assert is_subagent_render("claude_code_cli") is True
    assert is_subagent_render("codex_cli") is True
    assert is_subagent_render("claude-code") is True
    assert is_subagent_render("gemini") is True
    assert is_subagent_render("some_future_cli") is True
