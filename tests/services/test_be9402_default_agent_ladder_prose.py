# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9402: a missing agent template must never STOP the orchestrator.

The repealed prose told the orchestrator to halt over a missing FILE:

    "If a gil-* template is missing, STOP and report the mismatch: do not
     substitute a generic agent"          -- codex_prompt_builder.py:60
    "If a gil-* template is missing or unavailable, STOP and report the error.
     Do not substitute."                  -- chapters_reference.py:71

Every supported harness runs its own default subagent natively (Claude Code's
Task tool, Codex's spawn_agent), so a missing install is a setup gap to mention
once, not a reason to stop working.

NEGATIVE-GUARD PATTERN: :func:`test_no_harness_surface_still_stops_on_a_missing_template`
greps the SOURCE of every harness prompt builder and every protocol chapter rather
than the two known sites, so a third surface that copies the old prose is caught
too. It fails against the pre-BE-9402 tree (both sites match).

DoD #3 is covered here as well: the ``cli_tool``-based harness selection in
multi_terminal spawn synthesis must be untouched by this change.

Project: BE-9402.
"""

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


# The exact sentence the operator specified. Pinned as a literal here on purpose:
# the constant is derived from branding.PRODUCT_NAME, so if the brand flips without
# anyone revisiting this notice, this assertion is where it surfaces.
_EXPECTED_NOTICE = (
    "No Giljo HQ agent templates installed — using default agents. Run giljo_setup to install tuned agents."
)

# Every surface that tells an orchestrator how to spawn an agent.
_HARNESS_PROSE_DIRS = (
    Path("src/giljo_mcp/prompts"),
    Path("src/giljo_mcp/services/protocol_sections"),
)

# A STOP tied to a MISSING TEMPLATE -- not any STOP. The health-check and staging
# failure paths ("If failed, STOP and report error") are unrelated and must survive,
# so the pattern requires the template/substitution context on the same line.
_STOP_ON_MISSING_TEMPLATE = re.compile(
    r"(?:template is missing|template is missing or unavailable|gil-\* template)[^\n]*\bSTOP\b"
    r"|\bSTOP and report\b[^\n]*(?:mismatch|substitute)",
    re.IGNORECASE,
)

# The ladder prose says the words "template", "missing" and "stop" too -- in the
# NEGATIVE ("do NOT stop"). Matching the directive without checking whether it is
# negated would flag the fix itself as the defect.
_STOP_IS_NEGATED = re.compile(r"\b(?:do not|do n't|don't|never|instead of)\s+stop", re.IGNORECASE)

# The module whose entire purpose is to document what was repealed necessarily
# quotes the repealed sentence. It renders one constant and no spawn prose, so it
# is not a surface an orchestrator reads instructions from.
_RATIONALE_DOC = "default_agent_ladder.py"


def _prose_sources() -> list[Path]:
    files: list[Path] = []
    for directory in _HARNESS_PROSE_DIRS:
        assert directory.is_dir(), f"Expected prose directory {directory} to exist -- has the layout moved?"
        files.extend(sorted(p for p in directory.glob("*.py") if p.name not in ("__init__.py", _RATIONALE_DOC)))
    assert files, "Swept no files at all -- the guard would pass vacuously."
    return files


def test_no_harness_surface_still_stops_on_a_missing_template() -> None:
    """No prompt builder or protocol chapter may tell an orchestrator to halt.

    Fails against the pre-BE-9402 tree, where ``codex_prompt_builder.py`` and
    ``chapters_reference.py`` both carry the STOP.
    """
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
    """One canonical sentence, pinned. Both render sites import this constant."""
    assert MISSING_AGENT_TEMPLATES_NOTICE == _EXPECTED_NOTICE, (
        "The default-agent notice drifted from the specified wording. It is the only thing telling a "
        f"user why their agents are generic and how to fix it.\nGot:      {MISSING_AGENT_TEMPLATES_NOTICE!r}\n"
        f"Expected: {_EXPECTED_NOTICE!r}"
    )
    assert "giljo_setup" in MISSING_AGENT_TEMPLATES_NOTICE, (
        "The notice must name giljo_setup -- it is the canonical sync, and without it the notice "
        "states a problem with no remedy."
    )


@pytest.mark.parametrize(
    ("surface", "rendered"),
    [
        ("codex_prompt_builder", "\n".join(CodexPromptBuilder()._build_spawning_section([]))),
        ("chapters_reference CH3 codex", _CH3_CODEX[2]),
    ],
)
def test_each_repealed_surface_now_renders_the_ladder(surface: str, rendered: str) -> None:
    """Repeal is not deletion: each site must actively say what to do instead."""
    assert MISSING_AGENT_TEMPLATES_NOTICE in rendered, (
        f"{surface} dropped the STOP without replacing it. An orchestrator reading this has no "
        "instruction for a missing template at all, which is worse than the halt it replaced."
    )
    # Line-wrapped differently at each site, so compare on collapsed whitespace.
    assert "DEFAULT subagent" in " ".join(rendered.split()), (
        f"{surface} must name the fallback explicitly -- 'spawn the harness's DEFAULT subagent'. "
        "Without it the notice explains a situation but not the action."
    )
    # The ladder's FIRST rung survives: the installed template still wins when it exists.
    assert "gil-" in rendered, f"{surface} must still prefer the installed gil-* template when present."


def test_the_prefix_shadowing_warning_survives_the_repeal() -> None:
    """Guard against over-repeal.

    ``NEVER use agent='implementer'`` was never about missing templates -- built-in
    Codex roles SHADOW unprefixed names, so dropping this alongside the STOP would
    silently route work to a built-in role while the tuned template sat installed.
    """
    for surface, rendered in (
        ("codex_prompt_builder", "\n".join(CodexPromptBuilder()._build_spawning_section([]))),
        ("chapters_reference CH3 codex", _CH3_CODEX[2]),
    ):
        assert "unprefixed" in rendered.lower(), (
            f"{surface} lost the unprefixed-name warning. That rule guards against Codex's built-in "
            "roles shadowing an INSTALLED template -- a different failure from a missing one."
        )


# ---------------------------------------------------------------------------
# DoD #3 -- cli_tool harness selection in multi_terminal spawn synthesis, unchanged.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("cli_tool", "expected_binary"), sorted(CLI_BINARIES.items()))
def test_cli_tool_still_selects_its_own_harness_binary(cli_tool: str, expected_binary: str) -> None:
    """BE-9402 gates the IDENTITY, never the harness choice.

    A template's ``cli_tool`` picks the binary each multi_terminal agent launches
    into. Every registry row must still map to its own binary -- if this collapses,
    every agent launches into claude regardless of what the user configured.
    """
    assert resolve_binary(cli_tool) == expected_binary, (
        f"cli_tool {cli_tool!r} no longer resolves to its own launcher binary."
    )


def test_unknown_or_missing_cli_tool_still_defaults_to_claude() -> None:
    """The documented advisory fallback, unchanged: unset/unknown means claude."""
    assert resolve_binary(None) == CLI_BINARIES[DEFAULT_CLI_TOOL]
    assert resolve_binary("") == CLI_BINARIES[DEFAULT_CLI_TOOL]
    assert resolve_binary("not-a-real-harness") == CLI_BINARIES[DEFAULT_CLI_TOOL]


def test_spawn_synthesis_launches_each_agent_into_its_configured_harness() -> None:
    """End of the selection path: the chosen binary reaches the real launch command."""
    launch = synthesize_agent_launch(
        {"agent": "tester", "cli_tool": "codex", "job_id": "job-1", "seed_prompt": "load your mission"}
    )

    assert launch["cli_tool"] == "codex", "The synthesized spec must echo the configured cli_tool."
    for os_name, command in launch["commands"].items():
        assert "codex" in command, (
            f"The {os_name} launch command does not invoke the configured harness binary. Got: {command!r}"
        )
