# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.services.protocol_sections.agent_lifecycle import _generate_orchestrator_protocol


_MULTI_TERMINAL_ONLY = (
    '   - "Copy agent prompts from the dashboard to start them."',
    "  → Tell user to start the new prompt in a new agent session (terminal, desktop, or web tab)",
    "**If waiting for user to start agents (multi-terminal):**",
)


def _proto(*, execution_mode: str, tool: str) -> str:
    return _generate_orchestrator_protocol(
        job_id="job-6209c",
        tenant_key="tk_6209c",
        executor_id="exec-6209c",
        execution_mode=execution_mode,
        tool=tool,
        is_chain_conductor=False,
    )


def test_multi_terminal_render_keeps_today_strings_byte_identical() -> None:
    multi = _proto(execution_mode="multi_terminal", tool="multi_terminal")
    for s in _MULTI_TERMINAL_ONLY:
        assert s in multi, f"multi_terminal render must keep verbatim: {s!r}"


def test_subagent_render_drops_multi_terminal_only_fragments() -> None:
    sub = _proto(execution_mode="claude-code", tool="claude-code")
    for s in _MULTI_TERMINAL_ONLY:
        assert s not in sub, f"subagent render must NOT carry multi-terminal-only fragment: {s!r}"


def test_subagent_render_uses_self_spawn_phrasing() -> None:
    sub = _proto(execution_mode="claude-code", tool="claude-code")
    assert 'I will spawn each agent directly via Task(subagent_type="general-purpose")' in sub
    assert "no dashboard copy/paste needed" in sub
    assert 'Launch the replacement directly via Task(subagent_type="general-purpose")' in sub
    assert "**If your spawned subagents are running (nothing actionable right now):**" in sub


def test_subagent_self_spawn_syntax_is_tool_aware() -> None:
    codex = _proto(execution_mode="codex", tool="codex")
    assert "spawn_agent(name=...)" in codex
    assert "Task(subagent_type=" not in codex

    generic = _proto(execution_mode="some_future_cli", tool="some_future_cli")
    assert "your CLI's in-process subagent syntax" in generic
    for s in _MULTI_TERMINAL_ONLY:
        assert s not in generic
