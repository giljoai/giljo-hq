# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.endpoints.prompts import _build_conductor_bootstrap
from giljo_mcp.prompts._canonical_tool_list import (
    CANONICAL_ORCHESTRATOR_TOOLS,
    CANONICAL_WORKER_TOOLS,
    render_toolsearch_call_one_line,
    render_worker_toolsearch_call,
)
from giljo_mcp.prompts.claude_prompt_builder import ClaudePromptBuilder
from giljo_mcp.prompts.codex_prompt_builder import CodexPromptBuilder
from giljo_mcp.prompts.launch_command_synth import build_conductor_thin_prompt, render_harness_launch_block
from giljo_mcp.prompts.multi_terminal_prompt_builder import MultiTerminalPromptBuilder, build_agent_seed_lines
from giljo_mcp.prompts.spawn_prompt import build_agent_prompt
from giljo_mcp.prompts.staging_prompt_builder import StagingPromptBuilder
from giljo_mcp.prompts.subagent_prompt_builder import SubagentPromptBuilder
from giljo_mcp.services.protocol_sections.chapters_reference import _build_ch3_spawning_rules


_SELF_LAUNCH = ("new terminal", "seeded with this prompt", "open it in", "Open a new terminal")

_PROJECT = SimpleNamespace(name="P", id="PID", product_id="PR", taxonomy_alias="BE-1", description="d", mission="m")
_AGENT = SimpleNamespace(
    agent_name="impl",
    agent_display_name="implementer",
    job_id="job-1",
    agent_id="agent-1",
    status="waiting",
    job=SimpleNamespace(mission="m"),
    launch_template=None,
    cli_tool="claude",
)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _staging_thin(tool: str) -> str:
    return StagingPromptBuilder().build_thin_prompt("J", "A", "PID", _PROJECT, None, tool, {}, {}, None)


def _staging_full(tool: str) -> str:
    return StagingPromptBuilder().build_staging_prompt(_PROJECT, None, "J", "PID", "A", "http://x", tool)


def _chain(phase: str, claude: bool) -> str:
    return _build_conductor_bootstrap(
        identity={"job_id": "J", "agent_id": "A", "run_id": "R", "project_id": "PID"},
        mcp_url="http://x",
        phase=phase,
        harness_is_claude=claude,
    )




def test_worker_prompt_never_tells_the_worker_to_launch_itself():
    prompt = build_agent_prompt("impl", "implementer", "P", "job-1", SimpleNamespace(cli_tool="codex"))
    for phrase in _SELF_LAUNCH:
        assert phrase not in prompt, prompt
    assert "## HARNESS" not in prompt


def test_harness_launch_block_is_addressed_to_the_launcher_not_the_worker():
    block = render_harness_launch_block("codex", model=None, effort=None, launched=True)
    flat = _flat(block)
    assert "seeded with this prompt" not in flat
    assert "this prompt" not in flat
    assert "agent_prompt" in flat




@pytest.mark.parametrize("cli_tool", ["claude", "codex", "opencode"])
def test_per_session_seed_does_not_call_health_check(cli_tool):
    assert "health_check" not in "\n".join(build_agent_seed_lines(cli_tool, "job-1"))


def test_conductor_thin_prompt_does_not_call_health_check():
    assert "health_check" not in build_conductor_thin_prompt("run-1")


@pytest.mark.parametrize("builder", [ClaudePromptBuilder(), CodexPromptBuilder(), SubagentPromptBuilder()])
def test_execution_prompts_do_not_mandate_health_check(builder):
    prompt = builder.build_execution_prompt("orch-1", _PROJECT, [_AGENT])
    assert "health_check" not in prompt
    assert "MANDATORY STARTUP" not in prompt


@pytest.mark.parametrize("tool", ["claude-code", "multi_terminal"])
def test_multi_terminal_orchestrator_prompt_does_not_mandate_health_check(tool):
    prompt = MultiTerminalPromptBuilder().build_execution_prompt("orch-1", _PROJECT, [_AGENT], tool=tool)
    assert "health_check" not in prompt
    assert "FIRST ACTION (MANDATORY)" not in prompt


@pytest.mark.parametrize("tool", ["claude-code", "codex"])
def test_staging_prompts_do_not_mention_health_check(tool):
    assert "health_check" not in _staging_thin(tool)
    assert "health_check" not in _staging_full(tool)


@pytest.mark.parametrize("phase", ["staging", "implementation"])
@pytest.mark.parametrize("claude", [True, False])
def test_chain_bootstrap_does_not_mandate_health_check(phase, claude):
    assert "health_check" not in _chain(phase, claude)


def test_worker_prompt_has_no_health_check():
    assert "health_check" not in build_agent_prompt("impl", "implementer", "P", "job-1")




def test_toolsearch_queries_use_bare_names_never_a_hardcoded_server_prefix():
    for call in (render_toolsearch_call_one_line(), render_worker_toolsearch_call()):
        assert "mcp__" not in call
        assert 'query="select:' in call
    assert all("__" not in name for name in CANONICAL_ORCHESTRATOR_TOOLS + CANONICAL_WORKER_TOOLS)


def test_toolsearch_rosters_list_only_what_the_role_calls_first():
    assert "health_check" not in CANONICAL_ORCHESTRATOR_TOOLS
    assert "health_check" not in CANONICAL_WORKER_TOOLS
    assert "join_thread" not in CANONICAL_WORKER_TOOLS
    assert "get_job_mission" in CANONICAL_WORKER_TOOLS
    assert "get_staging_instructions" in CANONICAL_ORCHESTRATOR_TOOLS


@pytest.mark.parametrize(
    "render",
    [
        lambda: _staging_thin("claude-code"),
        lambda: _staging_full("claude-code"),
        lambda: _chain("staging", True),
        lambda: _chain("implementation", True),
        lambda: ClaudePromptBuilder().build_execution_prompt("orch-1", _PROJECT, [_AGENT]),
        lambda: MultiTerminalPromptBuilder().build_execution_prompt("orch-1", _PROJECT, [_AGENT], tool="claude-code"),
        lambda: build_agent_prompt("impl", "implementer", "P", "job-1"),
    ],
)
def test_no_rendered_claude_prompt_hardcodes_the_server_prefix(render):
    text = render()
    assert "mcp__giljo" not in text
    assert "ToolSearch(" in text




def test_both_worker_seeds_load_the_same_tools_and_call_get_job_mission_first():
    spawn_seed = build_agent_prompt("impl", "implementer", "P", "job-1")
    session_seed = "\n".join(build_agent_seed_lines("claude", "job-1"))
    expected = render_worker_toolsearch_call()
    assert expected in spawn_seed
    assert expected in session_seed
    assert 'get_job_mission(job_id="job-1")' in session_seed
    assert "get_job_mission" in spawn_seed




@pytest.mark.parametrize("tool", ["generic_mcp", "opencode"])
def test_generic_orchestrator_chapter_says_pass_agent_prompt_verbatim_up_front(tool):
    chapter = _flat(_build_ch3_spawning_rules(tool))
    assert "agent_prompt" in chapter
    assert "verbatim" in chapter
    assert "never write your own" in chapter.lower()
    assert chapter.index("agent_prompt") < chapter.index("OPTION A")
