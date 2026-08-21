# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tests for taxonomy-alias prefixing on orchestrator kickoff title.

Covers `StagingPromptBuilder.build_staging_prompt` and
`MultiTerminalPromptBuilder.build_execution_prompt`. When a project carries
structured taxonomy fields (`project_type_id` and/or `series_number`), the
opening title line must read `"<alias> <name>"`. When neither is set, the
title must render the project name alone — never the random 6-char fallback
alias from `Project.taxonomy_alias`.
"""

from types import SimpleNamespace
from uuid import uuid4

from giljo_mcp.prompts.multi_terminal_prompt_builder import MultiTerminalPromptBuilder
from giljo_mcp.prompts.staging_prompt_builder import StagingPromptBuilder


def _project(*, name: str, alias: str, project_type_id, series_number) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        taxonomy_alias=alias,
        project_type_id=project_type_id,
        series_number=series_number,
    )


def test_build_staging_prompt_prefixes_taxonomy_alias_when_set():
    builder = StagingPromptBuilder()
    project = _project(
        name="Token Prefix Feature",
        alias="BE-0042",
        project_type_id=uuid4(),
        series_number=42,
    )

    rendered = builder.build_staging_prompt(
        project=project,
        product=SimpleNamespace(),
        orchestrator_id="job-123",
        project_id="proj-123",
        agent_id="agent-123",
        mcp_url="http://localhost:7272",
    )

    assert 'You are the ORCHESTRATOR for project "BE-0042 Token Prefix Feature"' in rendered


def test_build_staging_prompt_omits_prefix_when_no_taxonomy():
    builder = StagingPromptBuilder()
    project = _project(
        name="Untaxonomied Project",
        alias="abc123",
        project_type_id=None,
        series_number=None,
    )

    rendered = builder.build_staging_prompt(
        project=project,
        product=SimpleNamespace(),
        orchestrator_id="job-123",
        project_id="proj-123",
        agent_id="agent-123",
        mcp_url="http://localhost:7272",
    )

    assert 'You are the ORCHESTRATOR for project "Untaxonomied Project"' in rendered
    assert "abc123" not in rendered


# ---------------------------------------------------------------------------
# CE-0035 — ToolSearch bootstrap on the production staging-orch spawn prompt
# ---------------------------------------------------------------------------
#
# build_staging_prompt is what /api/v1/prompts/staging/{project_id} returns
# to the user (the literal text the operator pastes into a fresh terminal to launch
# the orchestrator). CE-0034 added the ToolSearch bootstrap to build_thin_prompt
# instead — a sibling method on a separate call path that does NOT render the
# user-facing prompt. CE-0035 adds the same block to build_staging_prompt
# (the actual production method) gated on tool == "claude-code".
#
# Audit-discipline rule (codified after three consecutive misses on this item):
# tests must exercise the production path. These tests render the same method
# the user-facing endpoint calls, with the same parameters, and assert against
# the rendered string — not against intermediate constants or sibling helpers.


def _make_project_for_toolsearch() -> SimpleNamespace:
    return _project(
        name="ToolSearch Bootstrap",
        alias="BE-9999",
        project_type_id=uuid4(),
        series_number=9999,
    )


def _render_staging_prompt(tool: str) -> str:
    builder = StagingPromptBuilder()
    return builder.build_staging_prompt(
        project=_make_project_for_toolsearch(),
        product=SimpleNamespace(),
        orchestrator_id="job-123",
        project_id="proj-123",
        agent_id="agent-123",
        mcp_url="https://192.0.2.101:7272",
        tool=tool,
    )


def test_ce_0035_staging_prompt_includes_toolsearch_bootstrap_for_claude_code():
    """CE-0035: Claude Code orch spawn prompt MUST include ToolSearch bootstrap
    so the very first health_check() call doesn't raise InputValidationError."""
    rendered = _render_staging_prompt(tool="claude-code")
    assert "STEP 0 — TOOLSEARCH BOOTSTRAP" in rendered
    assert "select:" in rendered  # render_toolsearch_call_one_line() output
    from giljo_mcp.branding import MCP_ALIAS

    assert f"mcp__{MCP_ALIAS}__" in rendered  # the ToolSearch select: line, still fully prefixed


def test_ce_0035_staging_prompt_toolsearch_precedes_start_now_workflow():
    """The bootstrap MUST appear BEFORE the 'START NOW:' / health_check line —
    otherwise the orch pays the very round-trip the bootstrap is designed to
    eliminate."""
    rendered = _render_staging_prompt(tool="claude-code")
    bootstrap_idx = rendered.index("STEP 0 — TOOLSEARCH BOOTSTRAP")
    start_now_idx = rendered.index("START NOW:")
    # BE-9012d: the START NOW workflow steps render bare tool names now (harness-
    # neutral prose); the anchor moves to the bare `health_check()` call.
    health_check_idx = rendered.index("health_check()", start_now_idx)
    assert bootstrap_idx < start_now_idx < health_check_idx, (
        "Bootstrap order broken: STEP 0 must precede START NOW + health_check"
    )


def test_ce_0035_staging_prompt_omits_toolsearch_for_non_claude_code_harnesses():
    """Codex, Gemini, and universal/multi-terminal harnesses do NOT defer
    schemas the same way; the bootstrap block must NOT appear for them
    (would be noise at best, parse error at worst)."""
    for tool in ("codex", "gemini", "universal", "multi_terminal"):
        rendered = _render_staging_prompt(tool=tool)
        assert "STEP 0 — TOOLSEARCH BOOTSTRAP" not in rendered, f"Bootstrap should NOT appear for tool={tool!r}"
        # Assert against the bootstrap call signature specifically — the bare
        # word "ToolSearch" can legitimately appear in project names / titles,
        # so we check for the canonical select-prefix invocation only.
        assert "select:mcp__giljo_mcp__" not in rendered, f"ToolSearch invocation leaked into tool={tool!r} render"


def test_ce_0035_staging_prompt_default_tool_omits_toolsearch():
    """When no tool is specified (legacy callers), default to no bootstrap —
    safer than emitting Claude-Code-only text for an unknown harness."""
    builder = StagingPromptBuilder()
    rendered = builder.build_staging_prompt(
        project=_make_project_for_toolsearch(),
        product=SimpleNamespace(),
        orchestrator_id="job-123",
        project_id="proj-123",
        agent_id="agent-123",
        mcp_url="https://192.0.2.101:7272",
        # tool intentionally omitted → defaults to "universal"
    )
    assert "STEP 0 — TOOLSEARCH BOOTSTRAP" not in rendered


def test_multi_terminal_prompt_prefixes_taxonomy_alias_when_set():
    builder = MultiTerminalPromptBuilder()
    project = _project(
        name="Token Prefix Feature",
        alias="BE-0042",
        project_type_id=uuid4(),
        series_number=42,
    )

    rendered = builder.build_execution_prompt(
        orchestrator_id="job-123",
        project=project,
        agent_jobs=[],
    )

    assert "You are the ORCHESTRATOR for project 'BE-0042 Token Prefix Feature'." in rendered


def test_multi_terminal_prompt_omits_prefix_when_no_taxonomy():
    builder = MultiTerminalPromptBuilder()
    project = _project(
        name="Untaxonomied Project",
        alias="abc123",
        project_type_id=None,
        series_number=None,
    )

    rendered = builder.build_execution_prompt(
        orchestrator_id="job-123",
        project=project,
        agent_jobs=[],
    )

    assert "You are the ORCHESTRATOR for project 'Untaxonomied Project'." in rendered
    assert "abc123" not in rendered
