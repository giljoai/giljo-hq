# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from giljo_mcp.platform_registry import (
    GENERIC_HARNESS,
    GENERIC_SUBAGENT_SPAWN_SYNTAX,
    HARNESS_CLAUDE_CODE,
    HARNESS_CODEX,
    HARNESS_OPENCODE,
    get_harness,
)
from giljo_mcp.thin_prompt_generator import ThinClientPromptGenerator
from giljo_mcp.thin_prompt_lifecycle import (
    _IMPLEMENTATION_PROMPT_TYPE_MAP,
    _TOOL_TYPE_TO_PROMPT_TYPE,
    SUBAGENT_EXECUTION_PROMPT_TYPE,
    select_implementation_prompt_type,
)


_MULTI_TERMINAL_SEED_MARKERS = ("PER-SESSION AGENT SEED", "Open a NEW SESSION")

_ALL_HARNESS_CASES = [
    HARNESS_CLAUDE_CODE,
    HARNESS_CODEX,
    HARNESS_OPENCODE,
    GENERIC_HARNESS,
    None,
]


def _mock_project():
    project = MagicMock()
    project.name = "Test Project"
    project.id = str(uuid4())
    project.product_id = str(uuid4())
    project.taxonomy_alias = "TSTPRJ"
    return project


def _mock_agent_jobs(n: int = 1) -> list:
    jobs = []
    for i in range(n):
        agent = MagicMock()
        agent.agent_name = f"implementer-{i}"
        agent.agent_display_name = "implementer"
        agent.job_id = str(uuid4())
        agent.status = "waiting"
        agent.job = MagicMock()
        agent.job.mission = f"Do task {i}"
        jobs.append(agent)
    return jobs


def _render(execution_mode: str, detected_harness: str | None) -> str:
    prompt_type, resolved_harness = select_implementation_prompt_type(execution_mode, detected_harness)
    gen = ThinClientPromptGenerator(db=MagicMock(), tenant_key="tenant-test")
    return gen.generate_implementation_prompt(
        prompt_type=prompt_type,
        resolved_harness=resolved_harness,
        orchestrator_id=str(uuid4()),
        project=_mock_project(),
        agent_jobs=_mock_agent_jobs(2),
        git_enabled=False,
    )




class TestSelectImplementationPromptType:
    @pytest.mark.parametrize(
        ("detected", "expected_prompt_type", "expected_resolved"),
        [
            (HARNESS_CLAUDE_CODE, "claude_code_execution", HARNESS_CLAUDE_CODE),
            (HARNESS_CODEX, "codex_execution", HARNESS_CODEX),
            (HARNESS_OPENCODE, SUBAGENT_EXECUTION_PROMPT_TYPE, HARNESS_OPENCODE),
            (GENERIC_HARNESS, SUBAGENT_EXECUTION_PROMPT_TYPE, GENERIC_HARNESS),
            (None, SUBAGENT_EXECUTION_PROMPT_TYPE, GENERIC_HARNESS),
        ],
    )
    def test_subagent_resolves_detected_beats_declared(self, detected, expected_prompt_type, expected_resolved):
        prompt_type, resolved = select_implementation_prompt_type("subagent", detected)
        assert prompt_type == expected_prompt_type
        assert resolved == expected_resolved

    @pytest.mark.parametrize("detected", _ALL_HARNESS_CASES)
    def test_multi_terminal_is_mode_fixed_and_harness_agnostic(self, detected):
        prompt_type, resolved = select_implementation_prompt_type("multi_terminal", detected)
        assert prompt_type == "multi_terminal_orchestrator"
        assert resolved is None

    @pytest.mark.parametrize("detected", _ALL_HARNESS_CASES)
    def test_multi_terminal_orchestrator_unreachable_from_subagent(self, detected):
        prompt_type, _ = select_implementation_prompt_type("subagent", detected)
        assert prompt_type != "multi_terminal_orchestrator"

    @pytest.mark.parametrize(
        ("legacy_mode", "expected_prompt_type"),
        [
            ("generic_mcp", SUBAGENT_EXECUTION_PROMPT_TYPE),
            ("claude_code_cli", "claude_code_execution"),
            ("codex_cli", "codex_execution"),
            ("gemini_cli", SUBAGENT_EXECUTION_PROMPT_TYPE),
            ("antigravity_cli", SUBAGENT_EXECUTION_PROMPT_TYPE),
        ],
    )
    def test_legacy_declared_modes_undetected(self, legacy_mode, expected_prompt_type):
        prompt_type, _ = select_implementation_prompt_type(legacy_mode, None)
        assert prompt_type == expected_prompt_type
        assert prompt_type != "multi_terminal_orchestrator"




class TestPromptTypeMaps:
    def test_generic_and_opencode_route_to_neutral_subagent_builder(self):
        assert _TOOL_TYPE_TO_PROMPT_TYPE[GENERIC_HARNESS] == SUBAGENT_EXECUTION_PROMPT_TYPE
        assert _TOOL_TYPE_TO_PROMPT_TYPE[HARNESS_OPENCODE] == SUBAGENT_EXECUTION_PROMPT_TYPE

    def test_only_multi_terminal_maps_to_multi_terminal_builder(self):
        multi_terminal_keys = [k for k, v in _TOOL_TYPE_TO_PROMPT_TYPE.items() if v == "multi_terminal_orchestrator"]
        assert multi_terminal_keys == ["multi_terminal"]

    def test_canonical_subagent_mode_is_covered_and_neutral(self):
        assert _IMPLEMENTATION_PROMPT_TYPE_MAP["subagent"] == SUBAGENT_EXECUTION_PROMPT_TYPE

    def test_no_subagent_family_mode_maps_to_multi_terminal(self):
        from giljo_mcp.platform_registry import SUBAGENT_EXECUTION_MODES

        for mode in SUBAGENT_EXECUTION_MODES:
            assert _IMPLEMENTATION_PROMPT_TYPE_MAP[mode] != "multi_terminal_orchestrator", mode




class TestRenderedSubagentContent:
    @pytest.mark.parametrize("detected", _ALL_HARNESS_CASES)
    def test_subagent_render_never_contains_multi_terminal_seed(self, detected):
        prompt = _render("subagent", detected)
        for marker in _MULTI_TERMINAL_SEED_MARKERS:
            assert marker not in prompt, f"harness={detected!r} leaked multi_terminal seed marker {marker!r}"
        assert "get_job_mission" in prompt

    def test_neutral_builder_renders_registry_generic_spawn_prose(self):
        prompt = _render("subagent", None)
        assert GENERIC_SUBAGENT_SPAWN_SYNTAX in prompt
        assert "Subagent Mode" in prompt

    def test_neutral_builder_renders_opencode_registry_spawn_syntax(self):
        opencode = get_harness(HARNESS_OPENCODE)
        assert opencode is not None
        prompt = _render("subagent", HARNESS_OPENCODE)
        assert opencode.spawn_syntax in prompt
        for marker in _MULTI_TERMINAL_SEED_MARKERS:
            assert marker not in prompt




class TestMultiTerminalByteParity:
    @pytest.mark.parametrize("detected", _ALL_HARNESS_CASES)
    def test_multi_terminal_render_is_identical_regardless_of_harness(self, detected):
        project = _mock_project()
        agents = _mock_agent_jobs(2)
        orch_id = str(uuid4())
        gen = ThinClientPromptGenerator(db=MagicMock(), tenant_key="tenant-test")

        def render(harness):
            prompt_type, resolved = select_implementation_prompt_type("multi_terminal", harness)
            return gen.generate_implementation_prompt(
                prompt_type=prompt_type,
                resolved_harness=resolved,
                orchestrator_id=orch_id,
                project=project,
                agent_jobs=agents,
                git_enabled=False,
            )

        assert render(detected) == render(None)

    def test_multi_terminal_still_carries_the_per_session_seed(self):
        prompt = _render("multi_terminal", None)
        assert "PER-SESSION AGENT SEED" in prompt
