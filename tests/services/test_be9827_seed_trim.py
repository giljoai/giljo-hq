# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re

import pytest

from giljo_mcp.template_seeder import (
    _get_default_templates_v103,
    _get_mcp_bootstrap_section,
    compose_orchestrator_identity,
)


_TOOLS = ("claude-code", "codex", "gemini", "multi_terminal", "antigravity")
_PHASES = ("staging", "implementation", None)
_MASTER_IDENTITY_CHARS = {
    "claude-code": {"staging": 10_674, "implementation": 11_486},
    "codex": {"staging": 9_618, "implementation": 10_430},
}
_HARDCODED_PREFIX = re.compile(r"mcp__(?!<server>__)[a-z0-9_]+__")


def _all_seeded_texts() -> dict[str, str]:
    texts = {"worker bootstrap": _get_mcp_bootstrap_section()}
    for definition in _get_default_templates_v103():
        texts[f"{definition['name']} user_instructions"] = definition["user_instructions"]
    for tool in _TOOLS:
        for phase in _PHASES:
            for role in (None, "conductor"):
                texts[f"identity {tool}/{phase}/{role}"] = compose_orchestrator_identity(
                    None, tool=tool, role=role, phase=phase
                )
    return texts




def test_worker_bootstrap_starts_with_get_job_mission_not_health_check():
    bootstrap = _get_mcp_bootstrap_section()
    assert "health_check" not in bootstrap
    assert '1. Call `get_job_mission(job_id="<your_job_id>")`' in bootstrap


def test_no_seeded_text_asks_for_health_check_or_hardcodes_the_server_prefix():
    for name, text in _all_seeded_texts().items():
        assert "health_check" not in text, name
        assert not _HARDCODED_PREFIX.search(text), f"{name}: {_HARDCODED_PREFIX.search(text).group(0)}"


@pytest.mark.parametrize("phase", ["staging", "implementation"])
@pytest.mark.parametrize("tool", _TOOLS)
def test_orchestrator_identity_is_under_half_of_master(tool, phase):
    master = _MASTER_IDENTITY_CHARS["claude-code" if tool == "claude-code" else "codex"][phase]
    size = len(compose_orchestrator_identity(None, tool=tool, phase=phase))
    assert size <= master // 2, f"{tool}/{phase}: {size} chars, master {master}"



_STAGING_RULES = (
    "STAGING_LOCK",
    "STAGING_END_NO_AGENTS",
    "premortem",
    "If the project uses git:",
    "git add -A",
    "--no-verify",
    "predecessor_job_id",
    "bloat budget",
    "create_project",
    "spill",
)
_IMPLEMENTATION_RULES = (
    "request_approval(reason, options)",
    "awaiting_user",
    'set_agent_status("blocked")',
    "Where the project has tests",
    "the failing test before",
    "third failed try",
    "finalize_job(job_id, caller_job_id=<your job_id>)",
    "dismiss_job(job_id=...)",
    "Reviewer notes are not user approvals",
    "update_project(status='completed')",
    "CONTEXT_RESPONSE:",
    "BLOCKER:",
    "create_project",
)


@pytest.mark.parametrize("tool", _TOOLS)
def test_each_phase_still_carries_its_rules(tool):
    staging = compose_orchestrator_identity(None, tool=tool, phase="staging")
    implementation = compose_orchestrator_identity(None, tool=tool, phase="implementation")
    for needle in _STAGING_RULES:
        assert needle in staging, f"staging lost {needle!r}"
    for needle in _IMPLEMENTATION_RULES:
        assert needle in implementation, f"implementation lost {needle!r}"
    for text in (staging, implementation):
        assert "native tool calls" in text and "tenant_key" in text and "mcp__<server>__<tool>" in text


def test_claude_code_identity_keeps_the_toolsearch_roster_and_the_reminder_override():
    from giljo_mcp.prompts._canonical_tool_list import render_toolsearch_call_one_line

    for phase in _PHASES:
        identity = compose_orchestrator_identity(None, tool="claude-code", phase=phase)
        assert render_toolsearch_call_one_line() in identity
        assert "Do NOT mirror your TODOs" in identity and "recency-keyed" in identity


def test_additions_after_the_seed_survive_both_phases():
    from giljo_mcp.system_prompts.service import ADDITIONS_HEADING, compose_seed_with_additions
    from giljo_mcp.template_seeder import _get_user_facing_orchestrator_seed

    body = compose_seed_with_additions(_get_user_facing_orchestrator_seed(), "ALWAYS RUN THE LINTER.")
    for phase in _PHASES:
        identity = compose_orchestrator_identity(body, tool="codex", phase=phase)
        assert ADDITIONS_HEADING in identity and "ALWAYS RUN THE LINTER." in identity, phase


def test_a_legacy_full_replacement_prompt_is_still_phase_scoped_by_its_old_anchors():
    legacy = (
        "# Old seed\n\n"
        "## Three-Phase Workflow\n\nSTAGING-ONLY-A\n\n"
        "## Core Responsibilities\n\nSHARED\n\n"
        "## Accepting Deliverables\n\nIMPL-ONLY-A\n\n"
        "## Right-Sizing Your Work\n\n"
        "**Context fetching (get_context):** STAGING-ONLY-B\n\n**Deferred follow-ups SHARED2\n\n"
        "## Before Closeout\n\nIMPL-ONLY-B\n\n"
        "Detailed coordination mechanics, message prefixes, priority levels, and tool signatures "
        "are in `full_protocol` from `get_job_mission()`.\n\nADMIN TAIL"
    )
    staging = compose_orchestrator_identity(legacy, tool="codex", phase="staging")
    implementation = compose_orchestrator_identity(legacy, tool="codex", phase="implementation")
    assert "IMPL-ONLY-A" not in staging and "IMPL-ONLY-B" not in staging
    assert "STAGING-ONLY-A" not in implementation and "STAGING-ONLY-B" not in implementation
    for text in (staging, implementation):
        assert "SHARED" in text and "SHARED2" in text and "ADMIN TAIL" in text
