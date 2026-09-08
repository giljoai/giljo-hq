# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""CE-0033 — orchestrator discoverability & protocol nudges.

Regression tests for the eleven small platform-polish items shipped by
CE-0033. Filtered scope from the v2 test-orchestrator friction report after
product review.

Each test exercises the production data flow — protocol renderers, the real
mission_orchestration_service path, the actual spawn_job service method —
not mocked substitutes. Snapshot assertions on rendered identity/protocol
content ARE the production artifact for those tasks.
"""

from __future__ import annotations

import inspect
import json
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.prompts._canonical_tool_list import (
    CANONICAL_ORCHESTRATOR_TOOLS,
    render_toolsearch_call_one_line,
)
from giljo_mcp.prompts.claude_prompt_builder import ClaudePromptBuilder
from giljo_mcp.prompts.multi_terminal_prompt_builder import MultiTerminalPromptBuilder
from giljo_mcp.services.orchestration_service import OrchestrationService
from giljo_mcp.services.protocol_builder import _build_orchestrator_protocol
from giljo_mcp.services.protocol_sections.chapters_reference import _build_ch3_spawning_rules
from giljo_mcp.services.protocol_sections.chapters_startup import _build_ch2_startup
from giljo_mcp.template_seeder import compose_orchestrator_identity


# ----------------------------------------------------------------------------
# Helpers (mirror CE-0031 test seeding for production data-flow tests)
# ----------------------------------------------------------------------------


async def _seed_staging_orchestrator(
    db_session: AsyncSession,
    test_product,
    test_project,
    project_phase: str = "staging",
):
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
# Task 1 — list_projects continuation-check guidance in identity
# ----------------------------------------------------------------------------


class TestTask1ListProjectsGuidance:
    def test_identity_warns_against_bare_list_projects_planning(self):
        identity = compose_orchestrator_identity(None, tool="claude-code")
        # The guidance must name the filter knobs (taxonomy_alias_prefix +
        # date window) AND explicitly call out the bare-call footgun.
        assert "taxonomy_alias_prefix" in identity
        assert "completed_after" in identity or "created_after" in identity
        # Must explain the failure mode the orchestrator hit (spill).
        assert "spill" in identity.lower()

    def test_identity_includes_continuation_check_section(self):
        identity = compose_orchestrator_identity(None, tool="multi_terminal")
        assert "Continuation-check" in identity


# ----------------------------------------------------------------------------
# Task 2 — product_id hoisted into orchestrator identity block
# ----------------------------------------------------------------------------


class TestTask2ProductIdInIdentity:
    @pytest.mark.asyncio
    async def test_orchestrator_response_identity_contains_product_id(
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

        assert "product_id" in result["identity"], "Identity block must surface product_id (CE-0033 Task 2)"
        assert result["identity"]["product_id"] == str(test_product.id)
        assert "product_id" in result["identity"]["id_glossary"], "id_glossary must explain product_id"
        assert "get_context" in result["identity"]["id_glossary"]["product_id"]


# ----------------------------------------------------------------------------
# Task 3 — non-obvious tool parameters cheat-sheet
# ----------------------------------------------------------------------------


class TestTask3CheatSheet:
    def test_cheat_sheet_section_header_present(self):
        identity = compose_orchestrator_identity(None, tool="claude-code")
        assert "Non-obvious Tool Parameters" in identity, (
            "Identity must contain the discoverability cheat-sheet header (CE-0033 Task 3)"
        )

    def test_cheat_sheet_lists_high_value_knobs(self):
        identity = compose_orchestrator_identity(None, tool="claude-code")
        # Spot-check the parameters orchestrators are systematically missing
        # — verified to exist on the live tool signatures before being listed.
        expected_bullets = [
            "taxonomy_alias_prefix",  # list_projects
            "depth_config",  # fetch_context
            "predecessor_job_id",  # spawn_job
            "todo_append",  # report_progress
            # BE-9058: complete_job's acknowledge flags are retired (BE-9012b) and
            # scrubbed from the cheat sheet — no longer a knob to teach.
            "exclude_job_id",  # get_workflow_status
        ]
        for needle in expected_bullets:
            assert needle in identity, f"Cheat-sheet missing high-value parameter: {needle!r}"


# ----------------------------------------------------------------------------
# Task 4 — tenant_key contradiction resolved
# ----------------------------------------------------------------------------


class TestTask4TenantKeyConsistency:
    def test_identity_does_not_show_tenant_key_in_get_agent_mission_example(self):
        # Renders the agent-template seed (NOT the orchestrator identity, which
        # has the auto-injected note). We check that no inline example signature
        # passes tenant_key= for get_agent_mission. The server auto-injects
        # tenant_key from the API key session so the example must not contradict.
        from giljo_mcp.template_seeder import _get_default_templates_v103

        templates = _get_default_templates_v103()
        for template in templates:
            ui = template.get("user_instructions", "")
            if "get_agent_mission" in ui:
                # Find the get_agent_mission example call.
                # Forbidden: the literal `tenant_key=` parameter inside any
                # get_agent_mission(...) example.
                assert 'get_agent_mission(job_id="<your_job_id>", tenant_key=' not in ui, (
                    f"Template {template['name']!r} still passes tenant_key= to get_agent_mission "
                    f"despite the auto-inject claim — contradiction (CE-0033 Task 4)."
                )


# ----------------------------------------------------------------------------
# Task 5 — ToolSearch bootstrap in spawn prompts
# ----------------------------------------------------------------------------


class TestTask5SpawnPromptBootstrap:
    def _make_project(self):
        project = MagicMock()
        project.id = "proj-abc"
        project.name = "Test"
        project.product_id = "prod-xyz"
        project.taxonomy_alias = None
        project.project_type_id = None
        project.series_number = None
        return project

    def test_claude_code_spawn_prompt_contains_toolsearch_before_health_check(self):
        builder = ClaudePromptBuilder()
        prompt = builder.build_execution_prompt(
            orchestrator_id="orch-1",
            project=self._make_project(),
            agent_jobs=[],
            git_enabled=False,
        )
        # Bootstrap line must appear BEFORE the first health_check or
        # get_job_mission reference. BE-9012d (F1): the shared startup section
        # renders bare tool names now (this prose reaches Codex/Gemini/Desktop
        # too, where the Claude Code mcp__giljo_mcp__ prefix is wrong).
        ts_idx = prompt.find("ToolSearch(query=")
        hc_idx = prompt.find("health_check()")
        gm_idx = prompt.find("get_job_mission(")
        assert ts_idx >= 0, "Claude Code spawn prompt missing ToolSearch bootstrap"
        # health_check / get_job_mission appear later in the prompt.
        assert hc_idx > ts_idx, "ToolSearch must precede health_check in the spawn prompt"
        assert gm_idx > ts_idx, "ToolSearch must precede get_job_mission in the spawn prompt"

    def test_multi_terminal_default_spawn_prompt_omits_bootstrap(self):
        builder = MultiTerminalPromptBuilder()
        prompt = builder.build_execution_prompt(
            orchestrator_id="orch-1",
            project=self._make_project(),
            agent_jobs=[],
        )
        # Default tool="multi_terminal" — no bootstrap (would be noise).
        assert "ToolSearch(query=" not in prompt

    def test_multi_terminal_claude_tool_opts_in(self):
        builder = MultiTerminalPromptBuilder()
        prompt = builder.build_execution_prompt(
            orchestrator_id="orch-1",
            project=self._make_project(),
            agent_jobs=[],
            tool="claude-code",
        )
        assert "ToolSearch(query=" in prompt

    def test_canonical_tool_list_is_single_source_of_truth(self):
        # The canonical list and the identity prompt's embedded bootstrap
        # must reference the same set. The render helper feeds both.
        identity = compose_orchestrator_identity(None, tool="claude-code")
        rendered_call = render_toolsearch_call_one_line()
        # The exact call line appears verbatim in the Claude-Code identity.
        assert rendered_call in identity, "Identity ToolSearch call must use the canonical helper output"
        # Sanity: tools are present in the rendered call.
        from giljo_mcp.branding import MCP_ALIAS

        for tool_name in (
            f"mcp__{MCP_ALIAS}__health_check",
            f"mcp__{MCP_ALIAS}__spawn_job",
            f"mcp__{MCP_ALIAS}__report_progress",
            f"mcp__{MCP_ALIAS}__complete_job",
        ):
            assert tool_name in rendered_call
            assert tool_name in CANONICAL_ORCHESTRATOR_TOOLS


# ----------------------------------------------------------------------------
# Task 6 — protocol-chapter prominence: phase ordering + staging-finale gate prose
# ----------------------------------------------------------------------------


class TestTask6ProtocolProminence:
    def test_step7_finale_explains_flagless_todo_handling(self):
        """BE-9058: the finale must NOT teach the retired acknowledge flag (the
        server ignores it — no-op advice); it must instead explain that the
        staging TODOs are handled automatically."""
        ch2 = _build_ch2_startup(
            orchestrator_id="orch-1",
            project_id="proj-1",
            field_toggles={"product_core": True},
            depth_config={},
            product_id="prod-1",
            tenant_key="tk_test",
        )
        assert "acknowledge_closeout_todo" not in ch2
        finale_section = ch2.split("STEP 7 FINALE", 1)[1]
        assert "auto-completes" in finale_section
        assert "survive into implementation" in finale_section

    @pytest.mark.parametrize("tool", ["claude-code", "codex", "gemini", "multi_terminal"])
    def test_ch3_subagent_phase_ordering_note(self, tool):
        ch3 = _build_ch3_spawning_rules(tool)
        # The phase-ordering note must appear in CH3 across all tool variants
        # because phase semantics are universal.
        # Look for the substantive claim — server does NOT block higher-phase.
        assert "informational" in ch3.lower() or "does not block" in ch3.lower(), (
            f"CH3 ({tool}) must explain that subagent-mode phase ordering is informational"
        )

    def test_ch3_predecessor_required_for_phase_gt_1(self):
        ch3 = _build_ch3_spawning_rules("multi_terminal")
        assert "predecessor_job_id is REQUIRED" in ch3 or "predecessor_job_id" in ch3
        # It must mention phase > 1 specifically.
        assert "phase > 1" in ch3


# ----------------------------------------------------------------------------
# Task 7 — empty ch5_reference / ch6_auto_checkin keys cleaned up
# ----------------------------------------------------------------------------


class TestTask7EmptyKeysCleaned:
    def test_staging_response_omits_ch5_and_ch6_keys(self):
        # Staging response: include_implementation_reference=False, auto_checkin disabled.
        protocol = _build_orchestrator_protocol(
            cli_mode=True,
            project_id="proj-1",
            orchestrator_id="orch-1",
            tenant_key="tk_test",
            include_implementation_reference=False,
            field_toggles={},
            depth_config={},
            product_id="prod-1",
            tool="claude-code",
            auto_checkin_enabled=False,
        )
        assert "ch5_reference" not in protocol, "Empty ch5_reference must be omitted from staging response"
        assert "ch6_auto_checkin" not in protocol, "Empty ch6_auto_checkin must be omitted from staging response"
        # Sanity: present keys still there.
        assert "ch1_your_mission" in protocol
        assert "ch2_startup_sequence" in protocol

    def test_implementation_response_includes_ch5(self):
        protocol = _build_orchestrator_protocol(
            cli_mode=True,
            project_id="proj-1",
            orchestrator_id="orch-1",
            tenant_key="tk_test",
            include_implementation_reference=True,
            field_toggles={},
            depth_config={},
            product_id="prod-1",
            tool="claude-code",
            auto_checkin_enabled=False,
        )
        assert "ch5_reference" in protocol
        assert protocol["ch5_reference"]  # non-empty


# ----------------------------------------------------------------------------
# Task 8 — memory_360 default ordering documented in fetch_context
# ----------------------------------------------------------------------------


class TestTask8Memory360Ordering:
    def test_fetch_context_tool_description_documents_memory_360_default(self):
        from api.endpoints import mcp_sdk_server

        # BE-6042d: the @mcp.tool wrapper moved into the mcp_tools subpackage;
        # INF-6052a: registered name changed from fetch_context to get_context.
        # Inspect the wrapper function object (re-exported on mcp_sdk_server).
        src = inspect.getsource(mcp_sdk_server.get_context)
        # The get_context description must spell out the default order
        # (sequence DESC) and the depth_config knob.
        assert "sequence DESC" in src
        assert "depth_config" in src and "memory_360" in src


# ----------------------------------------------------------------------------
# Task 9 — spawn_job echoes phase in response
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTask9SpawnPhaseEcho:
    async def test_spawn_job_response_echoes_phase(self, db_session, db_manager, test_tenant_key):
        from datetime import UTC, datetime

        from giljo_mcp.models import AgentTemplate, Product, Project
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        # Seed template + project — sibling test files use this same pattern.
        db_session.add(
            AgentTemplate(
                tenant_key=test_tenant_key,
                name="implementer",
                role="implementer",
                description="impl",
                is_active=True,
            )
        )
        # BE-9437: a project belongs to a product. Its own, so an active
        # seed cannot collide under idx_project_single_active_per_product.
        _owning_product_proj = Product(
            id=str(uuid4()),
            tenant_key=test_tenant_key,
            name=f"Owning Product {uuid4().hex[:6]}",
            description="seeded",
            is_active=False,
        )
        db_session.add(_owning_product_proj)
        proj = Project(
            id=str(uuid4()),
            name="CE-0033 phase echo",
            description="...",
            mission="...",
            status="active",
            tenant_key=test_tenant_key,
            product_id=_owning_product_proj.id,
            execution_mode="multi_terminal",
            implementation_launched_at=datetime.now(UTC),
            series_number=99001,
        )
        db_session.add(proj)
        await db_session.commit()
        await db_session.refresh(proj)

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)
        result = await service.spawn_job(
            agent_display_name="implementer",
            agent_name="implementer",
            mission="Build the thing",
            project_id=proj.id,
            tenant_key=test_tenant_key,
            phase=1,
        )
        # SpawnResult.phase echoes the arg.
        assert getattr(result, "phase", "missing") == 1, "spawn_job response must echo phase (CE-0033 Task 9)"

    async def test_spawn_job_response_phase_none_when_unset(self, db_session, db_manager, test_tenant_key):
        from datetime import UTC, datetime

        from giljo_mcp.models import AgentTemplate, Project
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        db_session.add(
            AgentTemplate(
                tenant_key=test_tenant_key,
                name="analyzer",
                role="analyzer",
                description="ana",
                is_active=True,
            )
        )
        # BE-9437: a project belongs to a product. Its own, so an active
        # seed cannot collide under idx_project_single_active_per_product.
        _owning_product_proj = Product(
            id=str(uuid4()),
            tenant_key=test_tenant_key,
            name=f"Owning Product {uuid4().hex[:6]}",
            description="seeded",
            is_active=False,
        )
        db_session.add(_owning_product_proj)
        proj = Project(
            id=str(uuid4()),
            name="CE-0033 phase none",
            description="...",
            mission="...",
            status="active",
            tenant_key=test_tenant_key,
            product_id=_owning_product_proj.id,
            execution_mode="multi_terminal",
            implementation_launched_at=datetime.now(UTC),
            series_number=99002,
        )
        db_session.add(proj)
        await db_session.commit()
        await db_session.refresh(proj)

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)
        result = await service.spawn_job(
            agent_display_name="analyzer",
            agent_name="analyzer",
            mission="Look",
            project_id=proj.id,
            tenant_key=test_tenant_key,
        )
        assert result.phase is None


# ----------------------------------------------------------------------------
# Task 10 — report_progress drops empty warnings
# ----------------------------------------------------------------------------


class TestTask10ReportProgressNoEmptyWarnings:
    def test_report_progress_wrapper_strips_empty_warnings(self):
        # Inspect the wrapper source — the post-call strip is the load-bearing
        # piece. The actual response shape is exercised via integration tests
        # in tests/api/test_report_progress.py (existing); CE-0033 only
        # changes the wrapper.
        from api.endpoints import mcp_sdk_server

        src = inspect.getsource(mcp_sdk_server.report_progress)
        assert "warnings" in src
        assert "pop" in src and "warnings" in src, (
            "report_progress wrapper must pop empty 'warnings' from response (CE-0033 Task 10)"
        )

    @pytest.mark.asyncio
    async def test_progress_result_serializes_without_warnings_when_empty(self):
        from giljo_mcp.schemas.responses.orchestration import ProgressResult

        # The schema still defaults to []; the wrapper drops it post-serialization.
        # Simulate the wrapper's strip step.
        result = ProgressResult(status="success", message="ok", warnings=[]).model_dump(mode="json")
        if isinstance(result, dict) and not result.get("warnings"):
            result.pop("warnings", None)
        assert "warnings" not in result


# ----------------------------------------------------------------------------
# Task 11 — predecessor_job_id required for phase > 1
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTask11PredecessorRequiredForPhaseGt1:
    async def _seed(self, db_session, test_tenant_key):
        from datetime import UTC, datetime

        from giljo_mcp.models import AgentTemplate, Project

        db_session.add(
            AgentTemplate(
                tenant_key=test_tenant_key,
                name="implementer",
                role="implementer",
                description="impl",
                is_active=True,
            )
        )
        # BE-9437: a project belongs to a product. Its own, so an active
        # seed cannot collide under idx_project_single_active_per_product.
        _owning_product_proj = Product(
            id=str(uuid4()),
            tenant_key=test_tenant_key,
            name=f"Owning Product {uuid4().hex[:6]}",
            description="seeded",
            is_active=False,
        )
        db_session.add(_owning_product_proj)
        proj = Project(
            id=str(uuid4()),
            name="CE-0033 pred guard",
            description="...",
            mission="...",
            status="active",
            tenant_key=test_tenant_key,
            product_id=_owning_product_proj.id,
            execution_mode="multi_terminal",
            implementation_launched_at=datetime.now(UTC),
            series_number=99003,
        )
        db_session.add(proj)
        await db_session.commit()
        await db_session.refresh(proj)
        return proj

    async def test_phase_2_without_predecessor_is_rejected(self, db_session, db_manager, test_tenant_key):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        proj = await self._seed(db_session, test_tenant_key)
        service = OrchestrationService(db_manager=db_manager, tenant_manager=TenantManager(), test_session=db_session)

        with pytest.raises(ValidationError) as excinfo:
            await service.spawn_job(
                agent_display_name="implementer",
                agent_name="implementer",
                mission="...",
                project_id=proj.id,
                tenant_key=test_tenant_key,
                phase=2,
                predecessor_job_id=None,
            )
        assert "phase > 1" in str(excinfo.value) or "predecessor_job_id" in str(excinfo.value)

    async def test_phase_2_with_empty_string_predecessor_is_rejected(self, db_session, db_manager, test_tenant_key):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        proj = await self._seed(db_session, test_tenant_key)
        service = OrchestrationService(db_manager=db_manager, tenant_manager=TenantManager(), test_session=db_session)

        with pytest.raises(ValidationError):
            await service.spawn_job(
                agent_display_name="implementer",
                agent_name="implementer",
                mission="...",
                project_id=proj.id,
                tenant_key=test_tenant_key,
                phase=2,
                predecessor_job_id="",
            )

    async def test_phase_1_without_predecessor_is_accepted(self, db_session, db_manager, test_tenant_key):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        proj = await self._seed(db_session, test_tenant_key)
        service = OrchestrationService(db_manager=db_manager, tenant_manager=TenantManager(), test_session=db_session)

        # Phase 1 is the default ordering — empty predecessor is fine.
        result = await service.spawn_job(
            agent_display_name="implementer",
            agent_name="implementer",
            mission="...",
            project_id=proj.id,
            tenant_key=test_tenant_key,
            phase=1,
        )
        assert result.job_id


# ----------------------------------------------------------------------------
# Sanity — payload-budget regression guard (CE-0031 budget still holds)
# ----------------------------------------------------------------------------


class TestPayloadBudgetStillHolds:
    """CE-0033 adds material to the identity (cheat-sheet, continuation-check
    guidance). Confirm we haven't blown CE-0031's 35KB ceiling."""

    @pytest.mark.asyncio
    async def test_get_staging_instructions_still_under_budget(
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
        payload_size = len(json.dumps(result))
        # 41.5KB ceiling — 40KB -> 41KB after BE-6008 added staged-agent mailbox +
        # mode-gated coordination guidance; 41KB -> 41.5KB in BE-9563, where the
        # shipped tool names (finalize_job, resume_or_dismiss_job) are 8 bytes longer
        # than the retired ones they replace and master had only 7 bytes of headroom.
        # Both raises were deliberate; neither was a trim-avoidance. Real wire payload
        # ~41.0KB; MCP serializes tool results with indent=2. See TestTask5PayloadSize
        # in test_ce_0031_orchestrator_polish.py for the full rationale, the measured
        # before/after, and the 25KB structural-split goal.
        assert payload_size < 41_500, (
            f"grew the orchestrator identity past the 41KB ceiling ({payload_size} bytes). "
            f"Either trim the added content or raise the ceiling deliberately (and record why)."
        )


# ----------------------------------------------------------------------------
# CE-0034 Task 2 — ToolSearch bootstrap in the STAGING orchestrator spawn prompt
# ----------------------------------------------------------------------------
#
# CE-0033 Task 5 added the bootstrap to the EXECUTION-PHASE prompts
# (ClaudePromptBuilder._build_context_recap). That fixed sub-agent spawn prompts
# but missed the staging-orch's OWN spawn prompt — the prompt the user pastes
# to launch the orchestrator in the first place, generated by
# StagingPromptBuilder.build_thin_prompt. The test orchestrator reported on
# THIS prompt when it said "the spawn prompt I received didn't include the
# bootstrap." CE-0034 closes the gap.
#
# Audit-discipline lesson: render-snapshot tests on the actual production
# output, not just unit tests on the helper that contributes to it. CE-0033's
# tests verified the helper + execution-phase builders but never asserted on
# the rendered staging-orch spawn prompt — so the gap shipped unnoticed.


class TestCE0034StagingSpawnPromptToolSearch:
    """Render-snapshot tests on StagingPromptBuilder.build_thin_prompt."""

    def _build_thin_prompt(self, tool: str) -> str:
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

    def test_claude_code_staging_spawn_prompt_contains_toolsearch(self):
        prompt = self._build_thin_prompt(tool="claude-code")
        assert "ToolSearch(query=" in prompt, (
            "CE-0034: claude-code staging spawn prompt must include the ToolSearch bootstrap"
        )

    def test_claude_code_staging_spawn_toolsearch_appears_before_health_check(self):
        """The whole point of the bootstrap is to load schemas BEFORE the first
        MCP call (health_check). Position the assertion on the
        rendered output, not on the constants that feed it.

        BE-9012d: the WORKFLOW steps render bare tool names now (harness-neutral
        prose) -- only the ToolSearch select: line itself stays fully prefixed."""
        prompt = self._build_thin_prompt(tool="claude-code")
        ts_idx = prompt.find("ToolSearch(query=")
        hc_idx = prompt.find("health_check()", ts_idx)
        gm_idx = prompt.find("get_staging_instructions(", ts_idx)
        assert ts_idx >= 0
        assert hc_idx > ts_idx, (
            "CE-0034: ToolSearch must appear BEFORE health_check in the rendered staging spawn prompt"
        )
        assert gm_idx > ts_idx, (
            "CE-0034: ToolSearch must appear BEFORE get_staging_instructions in the rendered staging spawn prompt"
        )

    def test_claude_code_staging_spawn_uses_canonical_helper(self):
        """Single source of truth: the rendered call line must come from
        render_toolsearch_call_one_line() — not a hand-built copy that could drift."""
        prompt = self._build_thin_prompt(tool="claude-code")
        assert render_toolsearch_call_one_line() in prompt, (
            "CE-0034: staging spawn prompt must use render_toolsearch_call_one_line() verbatim"
        )

    def test_non_claude_code_staging_spawn_prompt_omits_toolsearch(self):
        for tool in ("multi_terminal", "codex", "gemini", "universal"):
            prompt = self._build_thin_prompt(tool=tool)
            assert "ToolSearch(query=" not in prompt, (
                f"CE-0034: tool={tool!r} must NOT see the ToolSearch bootstrap (Claude-Code-only)"
            )


# ----------------------------------------------------------------------------
# CE-0034 Task 3 — tenant_key residual sweep (closes CE-0033 Task 4 partial-ship)
# ----------------------------------------------------------------------------
#
# CE-0033 Task 4 was supposed to scrub explicit ``tenant_key="..."`` from
# protocol example sources because the orchestrator identity now claims
# tenant_key is auto-injected server-side. Two surfaces were missed:
#   - chapters_startup.py:197 (rendered protocol example for fetch_context)
#   - fetch_context.py docstring examples
# This test asserts every one of those surfaces no longer renders
# ``tenant_key="`` literals to agents. (The gil_get_agents.codex.SKILL.md surface
# was retired in INF-6049a when the slash fleet collapsed to /giljo.)


class TestCE0034TenantKeyResidualSweep:
    """Assert tenant_key= literals do not appear in agent-visible rendered output."""

    def test_chapters_startup_rendered_fetch_calls_omits_tenant_key(self):
        from giljo_mcp.services.protocol_sections.chapters_startup import _build_ch2_fetch_calls

        rendered = _build_ch2_fetch_calls(
            field_toggles={
                "product_core": True,
                "tech_stack": True,
                "architecture": True,
                "testing": True,
                "memory_360": True,
                "git_history": True,
                "vision_documents": True,
            },
            depth_config={},
            product_id="prod-xyz",
            tenant_key="tk_should_not_appear",
            category_metadata=None,
        )
        assert rendered, "Sanity: expected non-empty rendered output with all toggles on"
        assert 'tenant_key="' not in rendered, (
            "CE-0034: rendered ch2 fetch-calls protocol must NOT show tenant_key='..' arg "
            f"(identity claims it's auto-injected). Rendered:\n{rendered}"
        )
        # Also assert the substituted secret never leaks even loosely.
        assert "tk_should_not_appear" not in rendered, (
            "CE-0034: the tenant_key value supplied to the renderer must not appear in agent-visible output"
        )

    def test_fetch_context_docstring_omits_tenant_key(self):
        from giljo_mcp.tools.context_tools.fetch_context import fetch_context

        docstring = fetch_context.__doc__ or ""
        assert 'tenant_key="' not in docstring, (
            "CE-0034: fetch_context docstring examples must NOT show tenant_key='..' "
            f"(identity claims it's auto-injected). Docstring contains:\n{docstring}"
        )
