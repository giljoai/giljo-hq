# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re
from pathlib import Path

import pytest

from giljo_mcp.platform_registry import CLI_BINARIES
from giljo_mcp.prompts.codex_prompt_builder import CodexPromptBuilder
from giljo_mcp.prompts.default_agent_ladder import MISSING_AGENT_TEMPLATES_NOTICE
from giljo_mcp.prompts.launch_command_synth import (
    DEFAULT_CLI_TOOL,
    resolve_binary,
    synthesize_agent_launch,
)
from giljo_mcp.services.protocol_sections.chapters_reference import _CH3_CODEX


_EXPECTED_NOTICE = (
    "No Giljo HQ agent templates are defined for this product — using default agents. "
    "Create agents in the Template Manager to get tuned ones."
)

_HARNESS_PROSE_DIRS = (
    Path("src/giljo_mcp/prompts"),
    Path("src/giljo_mcp/services/protocol_sections"),
)

_STOP_ON_MISSING_TEMPLATE = re.compile(
    r"(?:template is missing|template is missing or unavailable|gil-\* template)[^\n]*\bSTOP\b"
    r"|\bSTOP and report\b[^\n]*(?:mismatch|substitute)",
    re.IGNORECASE,
)

_STOP_IS_NEGATED = re.compile(r"\b(?:do not|do n't|don't|never|instead of)\s+stop", re.IGNORECASE)

_INSTALL_AGENTS_REMEDY = re.compile(
    r"\binstall(?:s|ed|ing)?\b[^\n]{0,40}\b(?:agent|gil-\*|template)",
    re.IGNORECASE,
)

_INSTALL_IS_NEGATED = re.compile(
    r"\b(?:do not|don't|never|no longer|not|nothing|no)\b[^\n]{0,60}\binstall",
    re.IGNORECASE,
)

_RATIONALE_DOC = "default_agent_ladder.py"


def _prose_sources() -> list[Path]:
    files: list[Path] = []
    for directory in _HARNESS_PROSE_DIRS:
        assert directory.is_dir(), f"Expected prose directory {directory} to exist -- has the layout moved?"
        files.extend(sorted(p for p in directory.glob("*.py") if p.name not in ("__init__.py", _RATIONALE_DOC)))
    assert files, "Swept no files at all -- the guard would pass vacuously."
    return files


def test_no_harness_surface_still_stops_on_a_missing_template() -> None:
    offenders: list[str] = []
    for path in _prose_sources():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _STOP_ON_MISSING_TEMPLATE.search(line) and not _STOP_IS_NEGATED.search(line):
                offenders.append(f"{path.as_posix()}:{lineno}: {line.strip()}")

    assert not offenders, (
        "A harness surface still halts the orchestrator over a missing agent template. A missing "
        "install must degrade to the harness's DEFAULT subagent plus one notice, never stop the run:\n"
        + "\n".join(offenders)
    )


def test_the_notice_text_is_exactly_what_the_operator_specified() -> None:
    assert MISSING_AGENT_TEMPLATES_NOTICE == _EXPECTED_NOTICE, (
        "The default-agent notice drifted from the specified wording. It is the only thing telling a "
        f"user why their agents are generic and how to fix it.\nGot:      {MISSING_AGENT_TEMPLATES_NOTICE!r}\n"
        f"Expected: {_EXPECTED_NOTICE!r}"
    )
    assert "Template Manager" in MISSING_AGENT_TEMPLATES_NOTICE, (
        "The notice must name the remedy -- without one it states a problem the reader cannot act on."
    )
    assert "giljo_setup" not in MISSING_AGENT_TEMPLATES_NOTICE, (
        "DOC-9605d: giljo_setup no longer installs agents (BE-9605c), so naming it here sends the "
        "user to a tool that cannot fix this."
    )


def test_no_harness_surface_offers_an_agent_install_remedy() -> None:
    offenders: list[str] = []
    for path in _prose_sources():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _INSTALL_AGENTS_REMEDY.search(line) and not _INSTALL_IS_NEGATED.search(line):
                offenders.append(f"{path.as_posix()}:{lineno}: {line.strip()}")

    assert not offenders, (
        "A harness surface tells the orchestrator to install agent files. BE-9605c retired that "
        "path: every agent receives its profile from get_job_mission's agent_profile, and there is "
        "nothing to install:\n" + "\n".join(offenders)
    )


@pytest.mark.parametrize(
    ("surface", "rendered"),
    [
        ("codex_prompt_builder", "\n".join(CodexPromptBuilder()._build_spawning_section([]))),
        ("chapters_reference CH3 codex", _CH3_CODEX[2]),
    ],
)
def test_each_repealed_surface_now_renders_the_ladder(surface: str, rendered: str) -> None:
    assert MISSING_AGENT_TEMPLATES_NOTICE in rendered, (
        f"{surface} dropped the STOP without replacing it. An orchestrator reading this has no "
        "instruction for a missing template at all, which is worse than the halt it replaced."
    )
    assert "DEFAULT subagent" in " ".join(rendered.split()), (
        f"{surface} must name the fallback explicitly -- 'spawn the harness's DEFAULT subagent'. "
        "Without it the notice explains a situation but not the action."
    )
    assert "gil-" in rendered, f"{surface} must still prefer the tenant's own gil-* agent when present."


def test_the_prefix_shadowing_warning_survives_the_repeal() -> None:
    for surface, rendered in (
        ("codex_prompt_builder", "\n".join(CodexPromptBuilder()._build_spawning_section([]))),
        ("chapters_reference CH3 codex", _CH3_CODEX[2]),
    ):
        assert "unprefixed" in rendered.lower(), (
            f"{surface} lost the unprefixed-name warning. That rule guards against Codex's built-in "
            "roles shadowing the tenant's own agent -- a different failure from having none."
        )




@pytest.mark.parametrize(("cli_tool", "expected_binary"), sorted(CLI_BINARIES.items()))
def test_cli_tool_still_selects_its_own_harness_binary(cli_tool: str, expected_binary: str) -> None:
    assert resolve_binary(cli_tool) == expected_binary, (
        f"cli_tool {cli_tool!r} no longer resolves to its own launcher binary."
    )


def test_unknown_or_missing_cli_tool_still_defaults_to_claude() -> None:
    assert resolve_binary(None) == CLI_BINARIES[DEFAULT_CLI_TOOL]
    assert resolve_binary("") == CLI_BINARIES[DEFAULT_CLI_TOOL]
    assert resolve_binary("not-a-real-harness") == CLI_BINARIES[DEFAULT_CLI_TOOL]


def test_spawn_synthesis_launches_each_agent_into_its_configured_harness() -> None:
    launch = synthesize_agent_launch(
        {"agent": "tester", "cli_tool": "codex", "job_id": "job-1", "seed_prompt": "load your mission"}
    )

    assert launch["cli_tool"] == "codex", "The synthesized spec must echo the configured cli_tool."
    for os_name, command in launch["commands"].items():
        assert "codex" in command, (
            f"The {os_name} launch command does not invoke the configured harness binary. Got: {command!r}"
        )
