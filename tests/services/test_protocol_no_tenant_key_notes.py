# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import ast
import re

import pytest

from giljo_mcp.services.protocol_sections.agent_protocol import _generate_agent_protocol
from giljo_mcp.services.protocol_sections.chapters_reference import _build_ch5_reference
from giljo_mcp.services.protocol_sections.chapters_startup import (
    _build_ch1_mission,
    _build_ch2_startup,
)
from tests.helpers.agent_prose_literals import (
    REPO_ROOT,
    all_string_literals,
    interpolated_names,
    prose_literals,
    python_files,
)


JOB_ID = "11111111-1111-1111-1111-111111111111"
TENANT_KEY = "tk_TEST"
EXECUTOR_ID = "22222222-2222-2222-2222-222222222222"
PROJECT_ID = "33333333-3333-3333-3333-333333333333"
PRODUCT_ID = "44444444-4444-4444-4444-444444444444"



_FORBIDDEN_NOTES = [
    "tenant_key auto-injected by server from API key session",
    "tenant_key is auto-injected by the server",
    "tenant_key is auto-injected by server",
    "Do NOT pass it as a parameter",
    "never pass tenant_key",
]

_TENANT_KEY_EXAMPLE_RE = re.compile(r'tenant_key="[^"]+"')


def _assert_clean(text: str, where: str) -> None:
    assert TENANT_KEY not in text, (
        f"{where}: the tenant key VALUE was rendered into agent-facing text. "
        "No prompt or protocol surface may carry it (ADR-009) -- and because this is a "
        "value check, it fires however the code spells its way there."
    )
    for needle in _FORBIDDEN_NOTES:
        assert needle not in text, f"{where}: forbidden vestigial note still present: {needle!r}"
    matches = _TENANT_KEY_EXAMPLE_RE.findall(text)
    leaks = [m for m in matches if "get_context" not in ((text.split(m, 1)[0].splitlines() or [""])[-1])]
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




_PROMPT_SURFACE = (
    "src/giljo_mcp/prompts",
    "src/giljo_mcp/services/protocol_sections",
    "src/giljo_mcp/services/protocol_builder.py",
    "src/giljo_mcp/services/job_lifecycle_service.py",
    "src/giljo_mcp/services/mission_assembly.py",
    "src/giljo_mcp/services/mission_orchestration_builders.py",
    "src/giljo_mcp/services/mission_orchestration_service.py",
    "src/giljo_mcp/tools/tool_accessor/_project_tools.py",
    "src/giljo_mcp/thin_prompt_generator.py",
    "src/giljo_mcp/thin_prompt_lifecycle.py",
    "api/endpoints/prompts.py",
    "api/endpoints/chain_prompt_bootstrap.py",
)


class TestPromptSurfaceNeverMentionsTenantKey:

    def test_no_prompt_generator_prose_names_tenant_key(self):
        hits = []
        for path in python_files(*_PROMPT_SURFACE):
            for lineno, text in prose_literals(path):
                if "tenant_key" in text:
                    rel = path.relative_to(REPO_ROOT)
                    hits.append(f"  {rel}:{lineno}  {text.strip()[:110]!r}")

        assert not hits, (
            "A prompt generator emits prose naming tenant_key:\n"
            + "\n".join(hits)
            + "\n\ntenant_key is the tenancy isolation boundary (ADR-009). The MCP dispatch "
            "auto-injects it from the API-key session and strips it from every tool schema, so "
            "naming it in agent-facing text is at best an instruction the agent cannot follow "
            "and at worst -- when the value is interpolated -- a disclosure. Remove the mention; "
            "do not add an allowlist entry."
        )

    def test_no_prompt_generator_literal_carries_the_token_at_all(self):
        hits = []
        for path in python_files(*_PROMPT_SURFACE):
            for lineno, text in all_string_literals(path):
                if "tenant_key" in text:
                    rel = path.relative_to(REPO_ROOT)
                    hits.append(f"  {rel}:{lineno}  {text.strip()[:110]!r}")

        assert not hits, (
            "A prompt generator emits a literal containing tenant_key:\n"
            + "\n".join(hits)
            + "\n\nThis fires on single tokens too, so an f-string segment like 'tenant_key=' "
            "cannot hide behind the whitespace rule. Remove the mention."
        )

    def test_no_prompt_generator_interpolates_a_tenant_key_expression(self):
        hits = []
        for path in python_files(*_PROMPT_SURFACE):
            for lineno, name in interpolated_names(path):
                if "tenant_key" in name:
                    rel = path.relative_to(REPO_ROOT)
                    hits.append(f"  {rel}:{lineno}  interpolates {name!r}")

        assert not hits, (
            "A prompt generator interpolates the tenancy isolation key into text:\n"
            + "\n".join(hits)
            + "\n\nThis is the shape of the BE-9664 disclosure. The value must not reach text "
            "handed to an agent or rendered to a screen (ADR-009)."
        )


class TestTheGuardCanActuallyFail:

    _VARIANTS = ("v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8", "v9")

    _ALIASED = ("v7", "v9")

    _NOTE_ONLY = ("v5",)

    _FIXTURE = REPO_ROOT / "tests/fixtures/tenant_key_disclosure_variants.py.txt"

    _SENTINEL = "tk_SENTINEL_0123456789"

    def _variant_functions(self) -> dict[str, ast.FunctionDef]:
        tree = ast.parse(self._FIXTURE.read_text(encoding="utf-8"))
        return {
            node.name.split("_")[0]: node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name.startswith("v")
        }

    def _statically_flagged(self) -> set[str]:
        flagged_lines = {ln for ln, text in all_string_literals(self._FIXTURE) if "tenant_key" in text}
        flagged_lines |= {ln for ln, text in prose_literals(self._FIXTURE) if "tenant_key" in text}
        flagged_lines |= {ln for ln, name in interpolated_names(self._FIXTURE) if "tenant_key" in name}
        return {
            name
            for name, node in self._variant_functions().items()
            if flagged_lines & set(range(node.lineno, (node.end_lineno or node.lineno) + 1))
        }

    def _leaking_by_value(self) -> set[str]:
        namespace: dict[str, object] = {}
        exec(compile(self._FIXTURE.read_text(encoding="utf-8"), str(self._FIXTURE), "exec"), namespace)  # noqa: S102

        class _Holder:
            tenant_key = self._SENTINEL

        leaking = set()
        for name in self._variant_functions():
            fn = next(v for k, v in namespace.items() if k.startswith(f"{name}_"))
            parameters = fn.__code__.co_varnames[: fn.__code__.co_argcount]
            arguments = () if not parameters else (_Holder() if "self" in parameters else self._SENTINEL,)
            if self._SENTINEL in fn(*arguments):
                leaking.add(name)
        return leaking

    def test_every_variant_actually_leaks_the_key(self):
        leaking = self._leaking_by_value()
        should_leak = [v for v in self._VARIANTS if v not in self._NOTE_ONLY]
        inert = [v for v in should_leak if v not in leaking]
        assert not inert, (
            f"these fixture variants no longer emit the tenant key and prove nothing: {inert}. "
            "Repair the shape rather than deleting the case."
        )

    def test_static_checks_catch_every_statically_reachable_shape(self):
        flagged = self._statically_flagged()
        expected = [v for v in self._VARIANTS if v not in self._ALIASED]
        missed = [v for v in expected if v not in flagged]
        assert not missed, (
            f"the AST checks no longer catch these disclosure shapes: {missed}. "
            "Read tests/fixtures/tenant_key_disclosure_variants.py.txt -- each defeated a "
            "specific plausible implementation of the check, and each is a real leak."
        )

    def test_aliased_shapes_are_invisible_to_static_analysis(self):
        flagged = self._statically_flagged()
        assert not [v for v in self._ALIASED if v in flagged], (
            "an aliasing shape became statically visible; re-read why _assert_clean asserts "
            "the value, and confirm the value assertion is still carrying these cases"
        )
        leaking = self._leaking_by_value()
        assert all(v in leaking for v in self._ALIASED), (
            f"{self._ALIASED} must still leak by VALUE -- that is the only thing catching them"
        )

    def test_the_fixture_still_holds_every_variant(self):
        names = set(self._variant_functions())
        assert set(self._VARIANTS) <= names, f"fixture lost variants: {set(self._VARIANTS) - names}"


class TestPromptSurfaceScopeCannotGoStale:

    _GENERATOR_MODULES = (
        "spawn_prompt",
        "launch_command_synth",
        "protocol_builder",
        "thin_prompt_generator",
    )

    def test_prompt_surface_scope_cannot_go_stale(self):
        in_scope = {p.resolve() for p in python_files(*_PROMPT_SURFACE)}
        strays = []
        for path in python_files("src", "api"):
            if path.resolve() in in_scope:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                modules = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    modules.append(node.module)
                elif isinstance(node, ast.Import):
                    modules.extend(alias.name for alias in node.names)
                for module in modules:
                    tail = module.rsplit(".", 1)[-1]
                    if tail in self._GENERATOR_MODULES:
                        strays.append(f"  {path.relative_to(REPO_ROOT)}:{node.lineno} imports {module}")

        assert not strays, (
            "These files drive the shared prompt generators but sit OUTSIDE _PROMPT_SURFACE, "
            "so the tenant_key checks never visit them:\n"
            + "\n".join(strays)
            + "\n\nAdd each path to _PROMPT_SURFACE in this module."
        )
