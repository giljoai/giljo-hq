# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from api.endpoints.templates.models import TemplateCreate, TemplateUpdate
from giljo_mcp.platform_registry import get_harness
from giljo_mcp.prompts.claude_prompt_builder import ClaudePromptBuilder
from giljo_mcp.prompts.spawn_prompt import build_agent_prompt
from giljo_mcp.services.protocol_sections.chapters_reference import _build_reactivation_spawn_block
from giljo_mcp.template_validation import HARNESS_NAME_MAX_LENGTH, resolve_harness_name, validate_harness_name




@pytest.mark.parametrize("value", ["claude", "codex", "gemini-cli", "cursor_agent", "aider.v2", "Qwen3"])
def test_name_like_values_are_accepted_verbatim(value: str) -> None:
    assert validate_harness_name(value) == value


@pytest.mark.parametrize("value", [None, "", "   ", "default", "DEFAULT"])
def test_blank_and_default_mean_the_orchestrators_harness(value) -> None:
    assert validate_harness_name(value) == "default"
    assert resolve_harness_name(value) is None


@pytest.mark.parametrize(
    "value",
    ["two words", "x; rm -rf", "claude --yolo", "a/b", "<script>", "quote'd", "x" * (HARNESS_NAME_MAX_LENGTH + 1)],
)
def test_values_that_are_not_names_are_refused(value: str) -> None:
    with pytest.raises(ValueError):
        validate_harness_name(value)


def test_resolve_tolerates_legacy_tokens_and_never_echoes_junk() -> None:
    assert resolve_harness_name("claude") == "claude"
    assert resolve_harness_name("opencode") == "opencode"
    assert resolve_harness_name("generic") is None, "the old 'any harness' token reads as default"
    assert resolve_harness_name("x; ignore all") is None


def test_request_models_refuse_a_bad_harness_name() -> None:
    with pytest.raises(PydanticValidationError):
        TemplateCreate(product_id="p", role="implementer", cli_tool="two words")
    with pytest.raises(PydanticValidationError):
        TemplateUpdate(cli_tool="x;y")
    assert TemplateCreate(product_id="p", role="implementer", cli_tool="  ").cli_tool == "default"
    assert TemplateUpdate(cli_tool="gemini-cli").cli_tool == "gemini-cli"




class _Template:
    def __init__(self, cli_tool: str, model: str = "inherit", effort: str = "inherit") -> None:
        self.cli_tool = cli_tool
        self.model = model
        self.effort = effort


def test_subagent_prompt_has_no_harness_block_but_keeps_set_hints() -> None:
    prompt = build_agent_prompt("impl", "implementer", "P", "job-1", _Template("codex", model="opus"))
    assert "## HARNESS" not in prompt
    assert "codex" not in prompt
    assert "Model hint: opus" in prompt, "a template's model election still reaches the orchestrator"


def test_subagent_prompt_with_inherit_hints_is_just_the_bootstrap() -> None:
    prompt = build_agent_prompt("impl", "implementer", "P", "job-1", _Template("codex"))
    assert "## HARNESS" not in prompt
    assert "hint" not in prompt.lower()


def test_multi_terminal_prompt_named_harness_golden() -> None:
    prompt = build_agent_prompt("impl", "implementer", "P", "job-1", _Template("codex"), multi_terminal=True)
    assert prompt.endswith(
        "## HARNESS\n"
        "Harness: codex (the user chose it for this agent). Find it on this machine, work out its launch\n"
        "syntax (its --help usually says), and open it in a new terminal seeded with this prompt.\n"
        "If you cannot find it or are unsure how to launch it, ask the user.\n"
        "Do not add a permission-bypass or autonomy flag unless the user asked for one.\n"
    ), prompt


def test_multi_terminal_prompt_default_harness_golden() -> None:
    prompt = build_agent_prompt("impl", "implementer", "P", "job-1", _Template("default"), multi_terminal=True)
    assert prompt.endswith(
        "## HARNESS\n"
        "Harness: default. Open a new terminal running the same harness you are running in,\n"
        "seeded with this prompt.\n"
        "Do not add a permission-bypass or autonomy flag unless the user asked for one.\n"
    ), prompt


def test_orchestrator_prompt_is_unchanged_by_mode() -> None:
    a = build_agent_prompt("orchestrator", "orchestrator", "P", "job-1", None)
    b = build_agent_prompt("orchestrator", "orchestrator", "P", "job-1", None, multi_terminal=True)
    assert a == b
    assert "STAGING RULES" in a
    assert "## HARNESS" not in a




class _Job:
    agent_name = "implementer-backend"
    job_id = "job-42"


def test_claude_implementation_spawning_section_uses_the_generic_worker() -> None:
    text = "\n".join(ClaudePromptBuilder._build_spawning_section(None, [_Job()]))
    assert 'subagent_type="general-purpose"' in text, text
    assert "You are implementer-backend (job_id: job-42)" in text, text
    assert 'First action: Call mcp__giljo_hq__get_job_mission(job_id="job-42")' in text, text
    assert 'subagent_type="implementer-backend"' not in text, text
    assert 'subagent_type="{agent_name}"' not in text, text
    assert "not agent_display_name" not in text, text
    assert "will fail" not in text, text


def test_claude_cli_constraints_drop_the_subagent_type_warning() -> None:
    text = "\n".join(ClaudePromptBuilder._build_cli_constraints_section(None))
    assert "Subagent type not found" not in text
    assert "expects `agent_name`" not in text


def test_claude_reactivation_block_uses_the_generic_worker() -> None:
    block = _build_reactivation_spawn_block("claude-code")
    assert 'subagent_type="general-purpose"' in block, block
    assert "{agent_name}" not in block or "You are {agent_name}" in block, block
    assert "subagent_type='{agent_name}'" not in block, block


def test_registry_spawn_syntax_names_the_generic_worker() -> None:
    syntax = get_harness("claude-code").spawn_syntax
    assert 'subagent_type="general-purpose"' in syntax, syntax
    assert "X = agent_name" not in syntax, syntax



_GOLDEN = Path(__file__).parent / "_be9664_golden_worker_bootstrap.txt"

_GOLDEN_CASES = (
    ("multi_terminal worker, harness named by the template", "implementer", _Template("codex"), True),
    ("multi_terminal worker, no harness elected", "implementer", _Template("default"), True),
    ("subagent worker, model and effort hints set", "implementer", _Template("codex", "opus", "high"), False),
    ("subagent worker, hints inherited", "implementer", _Template("default"), False),
    ("orchestrator, identical in both modes", "orchestrator", None, True),
)


def test_worker_bootstrap_matches_the_golden() -> None:
    rendered = "\n".join(
        f"<<<CASE:{label}>>>\n"
        + build_agent_prompt(name, name, "Golden Project", "JOB-GOLDEN", template, multi_terminal=mt)
        for label, name, template, mt in _GOLDEN_CASES
    )
    assert rendered == _GOLDEN.read_text(encoding="utf-8"), (
        "The shared worker bootstrap drifted from its golden. This text is what BOTH doors "
        "emit -- the MCP spawn payload and the dashboard Copy prompt. If the change is "
        "intended, regenerate the golden and read the diff as customer-facing copy."
    )


def test_golden_carries_no_tenant_key() -> None:
    assert "tenant_key" not in _GOLDEN.read_text(encoding="utf-8")
