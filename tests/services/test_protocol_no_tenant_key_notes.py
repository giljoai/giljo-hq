# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re

import pytest

from giljo_mcp.services.protocol_sections.agent_protocol import _generate_agent_protocol
from giljo_mcp.services.protocol_sections.chapters_reference import _build_ch5_reference
from giljo_mcp.services.protocol_sections.chapters_startup import (
    _build_ch1_mission,
    _build_ch2_startup,
)


JOB_ID = "11111111-1111-1111-1111-111111111111"
TENANT_KEY = "tk_TEST"
EXECUTOR_ID = "22222222-2222-2222-2222-222222222222"
PROJECT_ID = "33333333-3333-3333-3333-333333333333"
PRODUCT_ID = "44444444-4444-4444-4444-444444444444"



_FORBIDDEN_NOTES = [
    "tenant_key auto-injected by server from API key session",
    "tenant_key is auto-injected by the server",
    "Do NOT pass it as a parameter",
    "never pass tenant_key",
]

_TENANT_KEY_EXAMPLE_RE = re.compile(r'tenant_key="[^"]+"')


def _assert_clean(text: str, where: str) -> None:
    for needle in _FORBIDDEN_NOTES:
        assert needle not in text, f"{where}: forbidden vestigial note still present: {needle!r}"
    matches = _TENANT_KEY_EXAMPLE_RE.findall(text)
    leaks = [m for m in matches if "get_context" not in text.split(m, 1)[0].splitlines()[-1]]
    assert not leaks, f'{where}: tenant_key="..." example signature still rendered: {leaks!r}'




class TestNoTenantKeyAutoInjectNotes:

    def test_ch1_mission_default(self):
        rendered = _build_ch1_mission(tool="multi_terminal")
        _assert_clean(rendered, "CH1 mission (multi_terminal)")

    @pytest.mark.parametrize("tool", ["claude-code", "codex", "gemini", "multi_terminal"])
    def test_ch1_mission_all_platforms(self, tool):
        rendered = _build_ch1_mission(tool=tool)
        _assert_clean(rendered, f"CH1 mission ({tool})")

    def test_ch1_no_duplicate_implementation_warning(self):
        rendered = _build_ch1_mission(tool="multi_terminal")
        count = rendered.count("You do NOT execute implementation work")
        assert count == 1, f"CH1 multi_terminal: duplicate-line bug regressed (count={count})"

    def test_ch2_startup_sized(self):
        rendered = _build_ch2_startup(
            orchestrator_id=JOB_ID,
            project_id=PROJECT_ID,
            field_toggles={"product_core": True, "tech_stack": True},
            depth_config={},
            product_id=PRODUCT_ID,
            tenant_key=TENANT_KEY,
        )
        _assert_clean(rendered, "CH2 startup (sized)")

    def test_ch2_startup_unsized(self):
        rendered = _build_ch2_startup(
            orchestrator_id=JOB_ID,
            project_id=PROJECT_ID,
        )
        _assert_clean(rendered, "CH2 startup (unsized)")

    def test_ch5_reference_git_off(self):
        rendered = _build_ch5_reference(
            project_id=PROJECT_ID,
            orchestrator_id=JOB_ID,
            tool="multi_terminal",
            git_integration_enabled=False,
        )
        _assert_clean(rendered, "CH5 reference (git off)")

    def test_ch5_reference_git_on(self):
        rendered = _build_ch5_reference(
            project_id=PROJECT_ID,
            orchestrator_id=JOB_ID,
            tool="multi_terminal",
            git_integration_enabled=True,
        )
        _assert_clean(rendered, "CH5 reference (git on)")

    @pytest.mark.parametrize("tool", ["claude-code", "codex", "gemini", "multi_terminal"])
    def test_worker_protocol_all_platforms(self, tool):
        rendered = _generate_agent_protocol(
            job_id=JOB_ID,
            tenant_key=TENANT_KEY,
            agent_name="implementer",
            agent_id=EXECUTOR_ID,
            execution_mode=tool,
            git_integration_enabled=False,
            job_type="agent",
            tool=tool,
        )
        _assert_clean(rendered, f"worker protocol ({tool})")

    @pytest.mark.parametrize("execution_mode", ["claude-code", "codex", "gemini", "multi_terminal"])
    def test_orchestrator_protocol_all_modes(self, execution_mode):
        rendered = _generate_agent_protocol(
            job_id=JOB_ID,
            tenant_key=TENANT_KEY,
            agent_name="orchestrator",
            agent_id=EXECUTOR_ID,
            execution_mode=execution_mode,
            git_integration_enabled=False,
            job_type="orchestrator",
            tool=execution_mode if execution_mode in ("codex", "gemini", "claude-code") else "multi_terminal",
        )
        _assert_clean(rendered, f"orchestrator protocol ({execution_mode})")


class TestThinPromptHasNoTenantKeyNote:

    def test_thin_prompt(self):
        from giljo_mcp.services.job_lifecycle_service import JobLifecycleService

        prompt = JobLifecycleService._build_agent_prompt(
            None,
            agent_name="implementer",
            agent_display_name="implementer",
            project_name="Test Project",
            job_id=JOB_ID,
        )
        _assert_clean(prompt, "thin agent prompt")
