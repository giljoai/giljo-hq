# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tests for platform-detect routing in protocol generation (HO1020 / Wave 2 Item 2).

Background
----------
The bug: ``mission_service._exec_mode_to_tool.get(project_exec_mode, "claude-code")``
silently mapped any unknown execution_mode -- including the model default
``multi_terminal`` -- to ``claude-code``. The downstream worker protocol then injected
``Task(subagent_type=...)`` syntax into agents that have no Claude Code Task tool
available, causing them to fail at startup.

Fix shape
---------
1. Map ``multi_terminal`` to itself in the dict (route to existing generic branch).
2. Flip ALL fallback defaults from ``"claude-code"`` to ``"multi_terminal"`` so an
   unknown execution_mode fails-safe to the platform-neutral MCP-only protocol
   instead of dangerously injecting Task() syntax.
3. Reframe the generic branch around "each terminal is a job order" semantics.

Sites covered
-------------
- ``src/giljo_mcp/services/mission_service.py`` (line ~527)
- ``src/giljo_mcp/services/mission_orchestration_service.py`` (line ~475)
- ``src/giljo_mcp/services/protocol_sections/chapters_reference.py`` (lines 11, 286)
- ``src/giljo_mcp/services/protocol_sections/agent_protocol.py`` (line ~305)
"""

from __future__ import annotations

from giljo_mcp.services.protocol_sections.agent_protocol import _generate_agent_protocol
from giljo_mcp.services.protocol_sections.chapters_reference import (
    _REACTIVATION_SPAWN_BLOCKS,
    _build_ch3_spawning_rules,
    _build_reactivation_spawn_block,
)


# ---- Helpers --------------------------------------------------------------


def _render_orchestrator_protocol(execution_mode: str) -> str:
    """Render the orchestrator-flavor agent protocol for a given execution_mode.

    Mirrors the fork in ``_generate_agent_protocol`` for ``job_type == 'orchestrator'``,
    which selects the constellation wake-pattern that historically leaked Task() syntax
    when execution_mode was misclassified as 'claude-code'.
    """
    return _generate_agent_protocol(
        job_id="job-test",
        tenant_key="tk_test",
        agent_name="orchestrator",
        agent_id="exec-test",
        execution_mode=execution_mode,
        git_integration_enabled=False,
        job_type="orchestrator",
        tool=execution_mode if execution_mode in ("codex", "gemini", "claude-code") else "multi_terminal",
    )


# ---- Worker / orchestrator protocol rendering ----------------------------


class TestExecutionModeRouting:
    """End-to-end protocol rendering must follow execution_mode, not silently
    coerce to claude-code on unknown values."""

    def test_protocol_renders_task_syntax_for_claude_code_cli(self):
        """claude-code execution_mode must still render Task()/subagent_type syntax."""
        ch3 = _build_ch3_spawning_rules(tool="claude-code")
        assert "Task(subagent_type=" in ch3
        assert "CLAUDE CODE CLI" in ch3

    def test_protocol_renders_no_task_syntax_for_multi_terminal(self):
        """multi_terminal must NOT render platform-specific spawn invocation forms.
        HO1025: bare `Task()` / `spawn_agent()` may appear in the cross-platform
        `phase` educational block; gate the actual invocation forms instead."""
        ch3 = _build_ch3_spawning_rules(tool="multi_terminal")
        assert "Task(subagent_type=" not in ch3
        assert "spawn_agent(agent=" not in ch3
        assert "ANY MCP-CONNECTED AGENT" in ch3

    def test_protocol_falls_back_to_generic_for_unknown_mode(self):
        """An unrecognized tool (future mode, typo) must fall back to the generic
        platform-neutral block -- NOT to claude-code."""
        ch3 = _build_ch3_spawning_rules(tool="some_future_mode")
        # Generic else branch signature
        assert "ANY MCP-CONNECTED AGENT" in ch3
        # And NOT the claude-code block
        assert "Task(subagent_type=" not in ch3
        assert "CLAUDE CODE CLI" not in ch3

    def test_protocol_renders_codex_syntax_for_codex_cli(self):
        """Regression guard: codex stays on its own native spawn syntax."""
        ch3 = _build_ch3_spawning_rules(tool="codex")
        assert "spawn_agent(" in ch3
        assert "gil-" in ch3
        assert "CODEX CLI" in ch3
        assert "Task(subagent_type=" not in ch3

    def test_protocol_renders_gemini_syntax_for_gemini_cli(self):
        """Regression guard: gemini stays on @-syntax. HO1025: bare
        `spawn_agent()` may appear in the cross-platform `phase` educational
        block; gate the codex-specific invocation form instead."""
        ch3 = _build_ch3_spawning_rules(tool="gemini")
        assert "@" in ch3
        assert "GEMINI CLI" in ch3
        assert "Task(subagent_type=" not in ch3
        assert "spawn_agent(agent=" not in ch3


# ---- Reactivation spawn block fallback -----------------------------------


class TestReactivationSpawnBlockFallback:
    """``_build_reactivation_spawn_block`` must fail-safe to a subagent-generic block
    (harness-native re-spawn / self-adopt) for an unknown SUBAGENT token — never to
    claude-code's Task() — and to the multi_terminal block only for the non-subagent
    empty/None case (BE-9035c)."""

    def test_reactivation_spawn_block_generic_for_unknown_subagent_tool(self):
        # BE-9035c: an unknown non-empty token is a SUBAGENT context (is_subagent_render
        # fail-safe), so it gets the universal harness-native re-spawn block — NOT the
        # multi_terminal "ask the human to open a session" block (the BE-9033 fix) and
        # never claude-code's Task() syntax.
        from giljo_mcp.services.protocol_sections.chapters_reference import _REACTIVATION_GENERIC

        block = _build_reactivation_spawn_block(tool="unknown")
        assert block == _REACTIVATION_GENERIC
        assert "Task(subagent_type=" not in block
        assert "MANDATORY" in block  # harness-native re-spawn is mandatory when a mechanism exists

    def test_reactivation_spawn_block_multi_terminal_for_empty_tool(self):
        # The empty/None (non-subagent) case still fails safe to the platform-neutral
        # multi_terminal block, which relies only on MCP-level instructions.
        block = _build_reactivation_spawn_block(tool="")
        assert block == _REACTIVATION_SPAWN_BLOCKS["multi_terminal"]
        assert "Task(subagent_type=" not in block

    def test_reactivation_spawn_block_for_known_claude_code(self):
        """Regression guard: explicit claude-code still returns its native block."""
        block = _build_reactivation_spawn_block(tool="claude-code")
        assert block == _REACTIVATION_SPAWN_BLOCKS["claude-code"]
        assert "Task(subagent_type=" in block

    def test_reactivation_spawn_block_for_multi_terminal(self):
        """multi_terminal exists in the dict and renders platform-neutral instructions."""
        block = _build_reactivation_spawn_block(tool="multi_terminal")
        assert "Task(subagent_type=" not in block
        assert "spawn_agent(" not in block
        # Platform-neutral, session-neutral wording (BE-8003h: terminal→session)
        assert "Open a new session" in block


# ---- Generic-branch prose: "each terminal is a job order" framing --------


class TestGenericBranchJobOrderFraming:
    """The multi_terminal generic branch is reworded around the user's framing:
    each terminal is one job order, cross-agent coordination is MCP-only."""

    def test_generic_branch_uses_job_order_framing(self):
        ch3 = _build_ch3_spawning_rules(tool="multi_terminal")
        assert "job order" in ch3.lower()

    def test_generic_branch_is_explicit_about_mcp_only_coordination(self):
        ch3 = _build_ch3_spawning_rules(tool="multi_terminal")
        # The generic branch must reference the MCP coordination tools by name.
        assert "spawn_job" in ch3
        assert "post_to_thread" in ch3  # BE-9012d: bus (send_message) retired, Hub replaces it

    def test_generic_branch_includes_predecessor_handling_guidance(self):
        """multi_terminal CH3 must mention predecessor_job_id so the orchestrator
        knows it can pass a previous agent's job_id when a successor needs to
        read prior output. HO1022: prose collapsed from 2 multi-paragraph blocks
        (CHAINING PHASES + REACTIVATION) into a single PHASE HANDOFF sentence.
        Server now auto-detects chain vs replacement from predecessor status."""
        ch3 = _build_ch3_spawning_rules(tool="multi_terminal")
        assert "predecessor_job_id" in ch3
        assert "PHASE HANDOFF" in ch3

    def test_phase_parameter_block_renders_in_all_branches(self):
        """HO1025: CH3 PARAMETER REQUIREMENTS now documents the `phase` field
        explicitly. Concept (same phase = parallel, higher = sequential) is
        mode-agnostic; enforcement differs (multi_terminal: server/dashboard
        groups by phase; subagent: orchestrator manages ordering inline). The
        block must render in every branch so test-agent friction #4/#5 are
        addressed regardless of which mode the project picks."""
        for tool in ("multi_terminal", "claude-code", "codex", "gemini"):
            ch3 = _build_ch3_spawning_rules(tool=tool)
            assert "── phase (optional" in ch3, f"phase block missing in {tool} branch"
            assert "Same phase number" in ch3
            assert "Higher phase number" in ch3

    def test_predecessor_guidance_is_multi_terminal_only(self):
        """The multi_terminal-specific PHASE HANDOFF prose explaining the
        predecessor preamble injection is gated to the multi_terminal branch.
        Subagent branches still mention predecessor_job_id only in the brief
        cross-platform `phase` educational tip (HO1025), not in the dedicated
        PHASE HANDOFF block. Server silently skips preamble injection in
        subagent modes; orchestrator splices predecessor findings inline using
        its CLI's native return value. HO1022 removed the per-subagent
        PREDECESSOR PARAMETER USAGE blocks since they were teaching the
        orchestrator about a server-internal decision."""
        for tool in ("claude-code", "codex", "gemini"):
            ch3 = _build_ch3_spawning_rules(tool=tool)
            assert "PHASE HANDOFF:" not in ch3, (
                f"{tool} branch must not contain the multi_terminal-specific "
                f"PHASE HANDOFF block -- server skips preamble injection in "
                f"subagent modes"
            )


# ---- Agent protocol signature defaults -----------------------------------


class TestAgentProtocolDefaults:
    """The fail-safe default for ``tool`` must be ``multi_terminal``, not
    ``claude-code``, on every protocol entry point."""

    def test_generate_agent_protocol_default_is_multi_terminal(self):
        """When no execution_mode/tool is supplied, the rendered protocol must
        not leak Task() syntax into the agent's instructions."""
        # Worker protocol path -- defaults must NOT inject Task() syntax.
        protocol = _generate_agent_protocol(
            job_id="job-test",
            tenant_key="tk_test",
            agent_name="implementer",
            agent_id="exec-test",
            # No execution_mode or tool kwargs -- exercise defaults.
            git_integration_enabled=False,
            job_type="agent",
        )
        # Workers do not render CH3 spawning rules at all; they get the 5-phase
        # lifecycle. The default tool flows into _build_conditional_blocks
        # (gil_add command). The fail-safe is that no CLI-specific spawn syntax
        # ever appears in a worker mission rendered with default args.
        assert "Task(subagent_type=" not in protocol
        assert "spawn_agent(agent=" not in protocol

    def test_orchestrator_protocol_default_does_not_leak_task_syntax(self):
        """Orchestrator protocol with a multi_terminal execution_mode must use
        the multi-terminal constellation wake-pattern, NOT claude-code's."""
        protocol = _render_orchestrator_protocol(execution_mode="multi_terminal")
        assert "Task() processes" not in protocol
        assert "spawn_agent() processes" not in protocol


# ---- Service-layer dict mappings (mission_service / mission_orchestration) ----


class TestServiceLayerExecModeMapping:
    """The two parallel dict-fallback sites must agree on the same fail-safe
    default and the same mapping for multi_terminal.

    Implemented as source-text assertions against the service files because
    the bug is a single-character literal (``"claude-code"`` vs
    ``"multi_terminal"``) inside an inline ``.get()`` call. A live render
    test would only catch one half of the regression; the source-text guard
    catches anyone re-introducing either half.
    """

    def test_mission_service_routes_multi_terminal_to_itself(self):
        """multi_terminal must map to itself, NOT be silently re-mapped to
        ``claude-code`` by the .get() fallback.

        BE-3010a unified the two former inline dicts into the single
        PlatformRegistry source -- assert the explicit mapping there."""
        from giljo_mcp.platform_registry import EXECUTION_MODE_TO_TOOL, tool_for_mode

        assert EXECUTION_MODE_TO_TOOL["multi_terminal"] == "multi_terminal"
        assert tool_for_mode("multi_terminal") == "multi_terminal"

    def test_mission_service_fallback_default_is_multi_terminal(self):
        import re
        from pathlib import Path

        src = Path("src/giljo_mcp/services/mission_service.py").read_text(encoding="utf-8")
        # No remaining .get(..., "claude-code") calls in the exec-mode dict block.
        # BE-6041b: the duplicate inline dicts were hoisted to the module-level
        # _EXECUTION_MODE_TO_TOOL constant; the fallback default stays multi_terminal.
        assert '_EXECUTION_MODE_TO_TOOL.get(project_exec_mode, "claude-code")' not in src
        # BE-9335: assert the DEFAULT of every lookup rather than one exact call
        # string. The lookup key is no longer the bare project column (a chain member
        # resolves its mode through effective_execution_mode), and pinning the old
        # literal made this guard fail on a change that never touched the fallback it
        # exists to protect. Matching every call site also widens the guard: a second
        # lookup added later cannot slip in with the wrong default.
        defaults = re.findall(r'_EXECUTION_MODE_TO_TOOL\.get\(.*?,\s*"([\w-]+)"\s*\)', src, re.DOTALL)
        assert defaults, "expected at least one _EXECUTION_MODE_TO_TOOL.get() lookup in mission_service"
        assert set(defaults) == {"multi_terminal"}, f"fail-safe default must be multi_terminal, found {set(defaults)}"

    def test_mission_orchestration_service_fallback_default_is_multi_terminal(self):
        """BE-3010a replaced the inline ``execution_mode_to_tool`` dict + .get()
        fallback in mission_orchestration_service with the registry helper
        ``tool_for_mode()``, whose fail-safe default is ``multi_terminal`` (never
        ``claude-code``). Assert the helper's behavior and that the old buggy
        inline fallback literal is not reintroduced."""
        from pathlib import Path

        from giljo_mcp.platform_registry import tool_for_mode

        assert tool_for_mode("totally_unknown_mode") == "multi_terminal"
        assert tool_for_mode("multi_terminal") == "multi_terminal"
        src = Path("src/giljo_mcp/services/mission_orchestration_service.py").read_text(encoding="utf-8")
        assert 'execution_mode_to_tool.get(execution_mode, "claude-code")' not in src


# ---- Function signature defaults flipped to multi_terminal ---------------


class TestSignatureDefaults:
    """All protocol entry points whose ``tool`` parameter has a default must
    default to ``multi_terminal`` -- the fail-safe option."""

    def test_chapters_reference_ch3_default_is_multi_terminal(self):
        import inspect

        sig = inspect.signature(_build_ch3_spawning_rules)
        assert sig.parameters["tool"].default == "multi_terminal"

    def test_generate_agent_protocol_default_tool_is_multi_terminal(self):
        import inspect

        sig = inspect.signature(_generate_agent_protocol)
        assert sig.parameters["tool"].default == "multi_terminal"


# ---------------------------------------------------------------------------
# BE-6207: multi-terminal /giljo signoff uses the token that MATCHES each
# harness's installed command ($giljo for codex/antigravity, /giljo otherwise).
# Regression: a hardcoded ``tool == "codex"`` check handed Antigravity /giljo.
# ---------------------------------------------------------------------------


class TestGiljoSignoffToken:
    def _giljo_block(self, tool: str) -> str:
        from giljo_mcp.services.protocol_sections.agent_protocol import _build_conditional_blocks

        _git, giljo_block = _build_conditional_blocks(False, "multi_terminal", tool)
        return giljo_block

    def test_antigravity_signoff_uses_dollar_giljo(self):
        block = self._giljo_block("antigravity")
        assert "$giljo" in block and "/giljo" not in block

    def test_codex_signoff_uses_dollar_giljo(self):
        block = self._giljo_block("codex")
        assert "$giljo" in block and "/giljo" not in block

    def test_claude_and_gemini_signoff_use_slash_giljo(self):
        for tool in ("claude", "gemini"):
            block = self._giljo_block(tool)
            assert "/giljo" in block and "$giljo" not in block


# ---------------------------------------------------------------------------
# BE-9260: the ORCHESTRATOR body's own closeout signoff line ("Project complete.
# Use `/giljo` ...") hardcoded "/giljo" unconditionally -- the same class of bug
# TestGiljoSignoffToken above locks for the WORKER giljo_block, just in a
# different render site. Fixed to derive the token from giljo_invocation(tool)
# the same way.
# ---------------------------------------------------------------------------


class TestOrchestratorClosingGiljoSignoffToken:
    def _orchestrator_protocol(self, tool: str) -> str:
        return _generate_agent_protocol(
            job_id="job-test",
            tenant_key="tk_test",
            agent_name="orchestrator",
            agent_id="exec-test",
            execution_mode="subagent",
            git_integration_enabled=False,
            job_type="orchestrator",
            tool=tool,
        )

    def test_codex_and_antigravity_orchestrator_signoff_uses_dollar_giljo(self):
        for tool in ("codex", "antigravity"):
            protocol = self._orchestrator_protocol(tool)
            assert "$giljo" in protocol and "/giljo" not in protocol, f"tool={tool!r}"

    def test_claude_code_and_gemini_orchestrator_signoff_uses_slash_giljo(self):
        for tool in ("claude-code", "gemini"):
            protocol = self._orchestrator_protocol(tool)
            assert "/giljo" in protocol and "$giljo" not in protocol, f"tool={tool!r}"


# ---------------------------------------------------------------------------
# BE-9260: protocol-section text is rendered LIVE to every tenant's agents,
# regardless of what product/tech-stack they run. A non-Claude-Code harness
# (codex, gemini) must never see Claude-Code-only tool names (TodoWrite) or
# THIS repo's own toolchain (pytest/ruff) and protected-file list asserted as
# universal mandates. A claude-code render must still carry the harness-
# specific TodoWrite guidance -- the over-correction check.
# ---------------------------------------------------------------------------


class TestBE9260ProtocolNeutralityByHarness:
    """Render worker / orchestrator / staging prompts for a non-claude-code
    harness and assert no dogfooding contamination leaks through; render for
    claude-code and assert the harness-specific guidance is still present."""

    def _worker_protocol(self, tool: str) -> str:
        return _generate_agent_protocol(
            job_id="job-test",
            tenant_key="tk_test",
            agent_name="implementer",
            agent_id="exec-test",
            execution_mode="subagent",
            git_integration_enabled=True,
            job_type="agent",
            tool=tool,
        )

    def _orchestrator_protocol(self, tool: str) -> str:
        return _generate_agent_protocol(
            job_id="job-test",
            tenant_key="tk_test",
            agent_name="orchestrator",
            agent_id="exec-test",
            execution_mode="subagent",
            git_integration_enabled=True,
            job_type="orchestrator",
            tool=tool,
        )

    def _staging_prompt(self, tool: str) -> str:
        from unittest.mock import MagicMock

        from giljo_mcp.prompts.staging_prompt_builder import StagingPromptBuilder

        builder = StagingPromptBuilder()
        project = MagicMock()
        project.id = "proj-abc"
        project.name = "Test Project"
        project.description = "Test desc"
        project.mission = ""
        project.taxonomy_alias = None
        project.project_type_id = None
        project.series_number = None
        product = MagicMock()
        product.id = "prod-xyz"
        return builder.build_thin_prompt(
            orchestrator_id="orch-1",
            agent_id="agent-1",
            project_id="proj-abc",
            project=project,
            product=product,
            tool=tool,
            field_toggles={},
            depth_config={},
            user_id=None,
        )

    # -- non-claude-code harness: no dogfooding contamination -------------

    def test_worker_protocol_omits_todowrite_for_non_claude_tool(self):
        for tool in ("codex", "gemini"):
            protocol = self._worker_protocol(tool)
            assert "TodoWrite" not in protocol, f"tool={tool!r} leaked Claude-Code TodoWrite wording"

    def test_orchestrator_protocol_omits_todowrite_for_non_claude_tool(self):
        for tool in ("codex", "gemini"):
            protocol = self._orchestrator_protocol(tool)
            assert "TodoWrite" not in protocol, f"tool={tool!r} leaked Claude-Code TodoWrite wording"

    def test_staging_prompt_omits_todowrite_for_non_claude_tool(self):
        for tool in ("codex", "gemini"):
            prompt = self._staging_prompt(tool)
            assert "TodoWrite" not in prompt, f"tool={tool!r} leaked Claude-Code TodoWrite wording"

    def test_orchestrator_protocol_does_not_mandate_pytest_or_ruff(self):
        for tool in ("codex", "gemini"):
            protocol = self._orchestrator_protocol(tool)
            assert "pytest" not in protocol.lower(), f"tool={tool!r} leaked a pytest mandate"
            assert "ruff" not in protocol.lower(), f"tool={tool!r} leaked a ruff mandate"

    def test_orchestrator_protocol_does_not_hardcode_repo_protected_files(self):
        for tool in ("codex", "gemini"):
            protocol = self._orchestrator_protocol(tool)
            assert "CLAUDE.md" not in protocol, f"tool={tool!r} leaked our repo's protected-file list"
            assert "pyproject.toml" not in protocol, f"tool={tool!r} leaked our repo's protected-file list"
            assert "alembic.ini" not in protocol, f"tool={tool!r} leaked our repo's protected-file list"

    def test_orchestrator_protocol_does_not_leak_this_repo_ticket_refs_or_branch(self):
        for tool in ("codex", "gemini"):
            protocol = self._orchestrator_protocol(tool)
            assert "BE-9083c" not in protocol, f"tool={tool!r} leaked an internal ticket ref"
            assert "master bug" not in protocol, f"tool={tool!r} assumed 'master' as THE branch"

    # -- claude-code: over-correction check --------------------------------
    # (The orchestrator's 3-phase coordination protocol never mentioned
    # TodoWrite even before BE-9260 -- it's a worker/staging-prompt concept
    # only -- so there is no orchestrator-side over-correction case to guard.)

    def test_worker_protocol_keeps_todowrite_for_claude_code(self):
        protocol = self._worker_protocol("claude-code")
        assert "TodoWrite" in protocol

    def test_staging_prompt_keeps_todowrite_for_claude_code(self):
        prompt = self._staging_prompt("claude-code")
        assert "TodoWrite" in prompt
