# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.platform_registry import PLATFORM_PRESETS
from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_chain_drive
from giljo_mcp.services.protocol_sections.orchestrator_body import (
    LAUNCH_PROMPT_RULE,
    _build_orchestrator_protocol_body,
)


def test_sentence_says_verbatim_first_message_and_never_replace() -> None:
    assert "agent_prompt spawn_job returned" in LAUNCH_PROMPT_RULE
    assert "verbatim, as its first message" in LAUNCH_PROMPT_RULE
    assert "may add to it, never replace it" in LAUNCH_PROMPT_RULE


@pytest.mark.parametrize(
    ("execution_mode", "tool"),
    [
        ("multi_terminal", "multi_terminal"),
        ("subagent", "claude-code"),
        ("subagent", "codex"),
        ("subagent", "generic_mcp"),
    ],
)
@pytest.mark.parametrize("is_chain_conductor", [False, True])
def test_solo_implementation_chapter_carries_the_sentence(
    execution_mode: str, tool: str, is_chain_conductor: bool
) -> None:
    body = _build_orchestrator_protocol_body(
        job_id="JID",
        tenant_key="TK",
        executor_id="AID",
        wake_pattern="<wake>",
        execution_mode=execution_mode,
        tool=tool,
        is_chain_conductor=is_chain_conductor,
    )
    phase2 = body.split("### PHASE 2", 1)[1]
    assert LAUNCH_PROMPT_RULE in phase2


_STEP_A_PATHS = [
    pytest.param("multi_terminal", None, None, id="cli-multi_terminal-full-matrix"),
    pytest.param("multi_terminal", None, "claude-code", id="cli-multi_terminal-claude"),
    pytest.param("multi_terminal", None, "codex", id="cli-multi_terminal-codex"),
    pytest.param("subagent", None, None, id="cli-subagent"),
    *[pytest.param("subagent", preset, None, id=f"preset-{preset.execution_mode}") for preset in PLATFORM_PRESETS],
]


@pytest.mark.parametrize(("execution_mode", "preset", "detected_harness"), _STEP_A_PATHS)
def test_conductor_step_a_carries_the_sentence_on_every_harness_path(execution_mode, preset, detected_harness) -> None:
    rendered = _build_ch_chain_drive(
        run_id="RUN",
        resolved_order=["P1", "P2"],
        current_index=0,
        execution_mode=execution_mode,
        conductor_agent_id="CID",
        job_id="JID",
        preset=preset,
        detected_harness=detected_harness,
    )
    step_a = rendered.split("STEP A", 1)[1].split("STEP B", 1)[0]
    assert LAUNCH_PROMPT_RULE in step_a
