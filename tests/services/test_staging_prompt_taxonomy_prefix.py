# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    rendered = _render_staging_prompt(tool="claude-code")
    assert "STEP 0 — TOOLSEARCH BOOTSTRAP" in rendered
    assert "select:" in rendered
    from giljo_mcp.branding import MCP_ALIAS

    assert f"mcp__{MCP_ALIAS}__" in rendered


def test_ce_0035_staging_prompt_toolsearch_precedes_start_now_workflow():
    rendered = _render_staging_prompt(tool="claude-code")
    bootstrap_idx = rendered.index("STEP 0 — TOOLSEARCH BOOTSTRAP")
    start_now_idx = rendered.index("START NOW:")
    health_check_idx = rendered.index("health_check()", start_now_idx)
    assert bootstrap_idx < start_now_idx < health_check_idx, (
        "Bootstrap order broken: STEP 0 must precede START NOW + health_check"
    )


def test_ce_0035_staging_prompt_omits_toolsearch_for_non_claude_code_harnesses():
    for tool in ("codex", "gemini", "universal", "multi_terminal"):
        rendered = _render_staging_prompt(tool=tool)
        assert "STEP 0 — TOOLSEARCH BOOTSTRAP" not in rendered, f"Bootstrap should NOT appear for tool={tool!r}"
        assert "select:mcp__giljo_mcp__" not in rendered, f"ToolSearch invocation leaked into tool={tool!r} render"


def test_ce_0035_staging_prompt_default_tool_omits_toolsearch():
    builder = StagingPromptBuilder()
    rendered = builder.build_staging_prompt(
        project=_make_project_for_toolsearch(),
        product=SimpleNamespace(),
        orchestrator_id="job-123",
        project_id="proj-123",
        agent_id="agent-123",
        mcp_url="https://192.0.2.101:7272",
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
