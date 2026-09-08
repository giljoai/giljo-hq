# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""CE-0031 — orchestrator-feedback polish pass regression tests.

Covers the five MCP-platform fixes shipped by CE-0031 against the test
orchestrator's "still present" friction list from 2026-05-17:

- Task 1: phase-aware ``agent_templates`` filter (tester/reviewer hidden in staging)
- Task 2: protocol-text contradictions resolved (Step 1c/4 ordering,
  complete_job consistency, fetch_context step pin, Blockers-are-urgent uniqueness,
  right-sizing inlined in identity)
- Task 3: Claude-Code harness reminder override present and load-bearing
- Task 5: payload size budget (regression guard against future bloat)
- Task 6: ToolSearch bootstrap hint present for Claude Code orchestrators
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.services.orchestration_service import OrchestrationService
from giljo_mcp.template_seeder import compose_orchestrator_identity


async def _seed_templates(db_session: AsyncSession, tenant_key: str) -> None:
    """Seed implementer + tester + reviewer templates so the filter has
    something to filter. Production runs against template_seeder's defaults;
    the test DB starts bare."""
    for name, role in (
        ("implementer", "implementer"),
        ("tester", "tester"),
        ("reviewer", "reviewer"),
    ):
        db_session.add(
            AgentTemplate(
                tenant_key=tenant_key,
                name=name,
                role=role,
                description=f"{name} template",
                is_active=True,
            )
        )
    await db_session.commit()


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


async def _seed_staging_orchestrator(
    db_session: AsyncSession,
    test_product,
    test_project,
    project_phase: str = "staging",
):
    """Wire up a staging-phase orchestrator job+exec the production way.

    Mirrors the seeding shape from
    ``test_orchestration_service_instructions.test_returns_toggle_based_context``
    so we exercise the real ``_build_orchestrator_response`` data flow, not a
    mocked-template injection.
    """
    test_product.tenant_key = test_project.tenant_key
    await db_session.commit()
    await db_session.refresh(test_product)

    test_project.product_id = test_product.id
    await db_session.commit()
    await db_session.refresh(test_project)

    job = AgentJob(
        job_id=str(uuid4()),
        job_type="orchestrator",
        tenant_key=test_project.tenant_key,
        project_id=test_project.id,
        mission="Orchestrate the project",
        status="active",
        job_metadata={"user_id": str(uuid4())},
    )
    db_session.add(job)
    await db_session.commit()

    execution = AgentExecution(
        agent_id=str(uuid4()),
        job_id=job.job_id,
        tenant_key=test_project.tenant_key,
        agent_display_name="orchestrator",
        agent_name="orchestrator",
        status="waiting",
        project_phase=project_phase,
    )
    db_session.add(execution)
    await db_session.commit()
    return job, execution


def _build_service(db_session: AsyncSession) -> OrchestrationService:
    service = OrchestrationService(db_manager=MagicMock(), tenant_manager=MagicMock(), websocket_manager=MagicMock())
    service._test_session = db_session
    service._mission._test_session = db_session
    service._mission._orchestration._test_session = db_session
    return service


# ----------------------------------------------------------------------------
# Task 1 — phase-aware agent_templates filter
# ----------------------------------------------------------------------------


class TestTask1PhaseAwareTemplates:
    """The staging exec's calling phase determines which templates surface."""

    @pytest.mark.asyncio
    async def test_staging_phase_hides_verification_templates(
        self,
        db_session: AsyncSession,
        test_product,
        test_project,
    ):
        await _seed_templates(db_session, test_project.tenant_key)
        job, _ = await _seed_staging_orchestrator(db_session, test_product, test_project, project_phase="staging")
        service = _build_service(db_session)

        result = await service._mission.get_staging_instructions(
            job_id=job.job_id,
            tenant_key=test_project.tenant_key,
        )

        roles_returned = {t["role"] for t in result["agent_templates"]}
        assert "tester" not in roles_returned, (
            "Staging exec must not see tester template — CE-0031 phase filter regression"
        )
        assert "reviewer" not in roles_returned, (
            "Staging exec must not see reviewer template — CE-0031 phase filter regression"
        )
        # Sanity: implementer (deliverable role) is still in the list.
        assert "implementer" in roles_returned
        assert result["phase_filter_note"], "Staging response must include phase_filter_note explaining the omission"
        assert "staging" in result["phase_filter_note"].lower()

    @pytest.mark.asyncio
    async def test_implementation_phase_shows_all_templates(
        self,
        db_session: AsyncSession,
        test_product,
        test_project,
    ):
        await _seed_templates(db_session, test_project.tenant_key)
        job, _ = await _seed_staging_orchestrator(
            db_session, test_product, test_project, project_phase="implementation"
        )
        service = _build_service(db_session)

        result = await service._mission.get_staging_instructions(
            job_id=job.job_id,
            tenant_key=test_project.tenant_key,
        )

        # Implementation phase: no filter, no advisory note.
        assert result["phase_filter_note"] is None
        roles_returned = {t["role"] for t in result["agent_templates"]}
        # All three seeded roles must surface — the filter is off.
        assert "tester" in roles_returned
        assert "reviewer" in roles_returned
        assert "implementer" in roles_returned


# ----------------------------------------------------------------------------
# Task 2 — protocol-text contradictions
# ----------------------------------------------------------------------------


class TestTask2ProtocolContradictions:
    """Assert against the actual rendered protocol text the agent receives."""

    @pytest.mark.asyncio
    async def test_identity_no_longer_forbids_complete_job(
        self,
        db_session: AsyncSession,
        test_product,
        test_project,
    ):
        job, _ = await _seed_staging_orchestrator(db_session, test_product, test_project)
        service = _build_service(db_session)

        result = await service._mission.get_staging_instructions(
            job_id=job.job_id,
            tenant_key=test_project.tenant_key,
        )

        # CH1 used to say "You do NOT call complete_job() (staging never completes,
        # it transitions)" — that pre-CE-0026 line was deleted.
        ch1 = result["orchestrator_protocol"]["ch1_your_mission"]
        assert "You do NOT call complete_job" not in ch1, (
            "CE-0026 sweep miss: CH1 still forbids complete_job. The post-CE-0026 "
            "canonical instruction is that staging DOES call complete_job."
        )
        assert "complete_job() at end of staging" in ch1 or "DO call complete_job" in ch1, (
            "CH1 must affirm complete_job at end of staging (CE-0026 transition)"
        )

    @pytest.mark.asyncio
    async def test_step_1b_does_not_reference_after_step_4(
        self,
        db_session: AsyncSession,
        test_product,
        test_project,
    ):
        job, _ = await _seed_staging_orchestrator(db_session, test_product, test_project)
        service = _build_service(db_session)

        result = await service._mission.get_staging_instructions(
            job_id=job.job_id,
            tenant_key=test_project.tenant_key,
        )

        ch2 = result["orchestrator_protocol"]["ch2_startup_sequence"]
        # The Step 1b prose used to say "After Step 4 (Create Mission)..." even
        # though Step 1c (where progress init happens) comes BEFORE Step 2.
        assert "After Step 4" not in ch2, (
            "Step ordering contradiction: 1b prose still references Step 4 despite Step 1c being canonical."
        )

    @pytest.mark.asyncio
    async def test_get_staging_instructions_tool_description_drops_step_number(self):
        # get_staging_instructions tool description previously said
        # "Step 1 of staging workflow" but the protocol puts it at Step 2.
        # Resolution: drop the step-number pin.
        # Tool descriptions live on the mcp.tool decorators; grep the module
        # source rather than re-introspect the FastMCP registry.
        import inspect

        from api.endpoints import mcp_sdk_server

        src = inspect.getsource(mcp_sdk_server)
        assert "Step 1 of staging workflow" not in src, "Tool description still pins to a step number — drift risk."

    def test_blockers_are_urgent_appears_exactly_once(self):
        identity = compose_orchestrator_identity(None, tool="claude-code")
        count = identity.count("Blockers are urgent")
        assert count == 1, (
            f"Identity must contain exactly one 'Blockers are urgent' block "
            f"(found {count}). Duplication is a regression — see CE-0031 Task 2."
        )

    def test_right_sizing_guidance_inlined_in_identity(self):
        identity = compose_orchestrator_identity(None, tool="multi_terminal")
        # The orchestrator identity must be self-sufficient: an agent that only
        # reads this prompt should still know the project-vs-task rule and
        # the context-fetch sizing rule. CE-0031 Task 2 inlined both.
        assert "Right-Sizing Your Work" in identity
        assert "create_task" in identity and "create_project" in identity
        assert "get_context" in identity or "fetch context" in identity.lower() or "get_job_mission" in identity


# ----------------------------------------------------------------------------
# Task 3 — harness reminder override
# ----------------------------------------------------------------------------


class TestTask3HarnessReminderOverride:
    """Claude Code harness injects TaskCreate <system-reminder>; identity overrides."""

    def test_claude_code_identity_includes_harness_override(self):
        identity = compose_orchestrator_identity(None, tool="claude-code")
        assert "HARNESS REMINDER OVERRIDE" in identity
        assert "TaskCreate" in identity
        assert "report_progress" in identity

    def test_claude_code_override_forecloses_mirroring(self):
        # BE-6084 spike (2026-06-17): the nudge is RECENCY-keyed, not existence-keyed —
        # an active harness task list does NOT silence it, so mirroring report_progress
        # todos into TaskCreate/TaskUpdate is net-negative (double-write + drift, still
        # incomplete suppression). The override must keep telling the orchestrator NOT to
        # mirror, and must record the recency rationale so a future maintainer doesn't
        # "helpfully" re-introduce mirroring. Lock both into the composed identity.
        identity = compose_orchestrator_identity(None, tool="claude-code")
        assert "do not mirror" in identity.lower()
        assert "recency-keyed" in identity

    def test_non_claude_code_identity_skips_harness_override(self):
        # Codex / Gemini / multi_terminal harnesses don't emit the TaskCreate
        # reminder, so the override would be noise. Gate stays Claude-Code only.
        identity_mt = compose_orchestrator_identity(None, tool="multi_terminal")
        assert "HARNESS REMINDER OVERRIDE" not in identity_mt

        identity_codex = compose_orchestrator_identity(None, tool="codex")
        assert "HARNESS REMINDER OVERRIDE" not in identity_codex


# ----------------------------------------------------------------------------
# Task 5 — payload size budget
# ----------------------------------------------------------------------------


class TestTask5PayloadSize:
    """Catch future bloat. CE-0031 trimmed ~12KB; budget allows some headroom."""

    # 41KB ceiling: CE-0031 set the budget at 35KB. CE-0033 added the
    # discoverability cheat-sheet, continuation-check guidance, product_id
    # glossary entry, Step 7 acknowledge_closeout_todo callout, and CH3
    # subagent phase-ordering note — total ~4KB (35KB → 40KB). BE-6008 then
    # added staged-agent mailbox + mode-gated coordination guidance, pushing
    # the real wire payload (MCP serializes tool results with indent=2) to
    # ~40.4KB. Ceiling raised a second time, deliberately, to 41KB to admit
    # that legitimate guidance. Still tight enough to catch bloat regressions;
    # long-term goal remains the 25KB target via Option A (sub-resource tools
    # split), which is the real lever — bumping the ceiling per feature is not.
    # BE-9563: 41_000 -> 41_500. The shipped tool names are 8 bytes longer than the
    # ones they replace (40,993 -> 41,001 measured), so the growth IS the correctness
    # fix rather than bloat to trim. 41_500 leaves ~500 bytes of headroom: enough that
    # one added sentence is not a crisis, small enough that the ceiling still bites.
    # The 25KB structural-split goal below is unchanged and still the real answer.
    PAYLOAD_BUDGET_BYTES = 41_500

    @pytest.mark.asyncio
    async def test_get_staging_instructions_under_budget(
        self,
        db_session: AsyncSession,
        test_product,
        test_project,
    ):
        job, _ = await _seed_staging_orchestrator(db_session, test_product, test_project)
        service = _build_service(db_session)

        result = await service._mission.get_staging_instructions(
            job_id=job.job_id,
            tenant_key=test_project.tenant_key,
        )

        # Use json.dumps to measure wire format (what the agent actually pays).
        payload_size = len(json.dumps(result))
        assert payload_size < self.PAYLOAD_BUDGET_BYTES, (
            f"get_staging_instructions payload is {payload_size} bytes — "
            f"exceeds {self.PAYLOAD_BUDGET_BYTES} budget. CE-0031 trimmed this from "
            f"~41KB; future bloat must be balanced by trim or a structural split "
            f"(Option A: sub-resource tools)."
        )


# ----------------------------------------------------------------------------
# Task 6 — ToolSearch bootstrap hint
# ----------------------------------------------------------------------------


class TestTask6ToolSearchBootstrap:
    """Fresh Claude Code sessions need the single ToolSearch bootstrap hint."""

    def test_claude_code_identity_lists_bootstrap_tools(self):
        identity = compose_orchestrator_identity(None, tool="claude-code")
        assert "TOOLSEARCH BOOTSTRAP" in identity
        assert "ToolSearch(query=" in identity
        # Sanity: hint must include the load-bearing core tools, not just one.
        from giljo_mcp.branding import MCP_ALIAS

        for tool_name in (
            f"mcp__{MCP_ALIAS}__health_check",
            f"mcp__{MCP_ALIAS}__spawn_job",
            f"mcp__{MCP_ALIAS}__report_progress",
            f"mcp__{MCP_ALIAS}__complete_job",
        ):
            assert tool_name in identity, f"Bootstrap hint missing {tool_name}"

    def test_other_tools_omit_bootstrap_hint(self):
        # Codex/Gemini don't have ToolSearch — the hint would be noise/error.
        for tool in ("codex", "gemini", "multi_terminal"):
            identity = compose_orchestrator_identity(None, tool=tool)
            assert "TOOLSEARCH BOOTSTRAP" not in identity, (
                f"{tool} identity must not include Claude-Code-specific ToolSearch hint"
            )
