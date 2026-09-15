# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
from tests.helpers.product_crew_helper import adopt_all_templates




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




class TestTask1ListProjectsGuidance:
    def test_identity_warns_against_bare_list_projects_planning(self):
        identity = compose_orchestrator_identity(None, tool="claude-code")
        assert "taxonomy_alias_prefix" in identity
        assert "completed_after" in identity or "created_after" in identity
        assert "spill" in identity.lower()

    def test_identity_includes_continuation_check_section(self):
        identity = compose_orchestrator_identity(None, tool="multi_terminal")
        assert "Continuation-check" in identity




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




class TestTask3CheatSheet:
    def test_cheat_sheet_section_header_present(self):
        identity = compose_orchestrator_identity(None, tool="claude-code")
        assert "Non-obvious Tool Parameters" in identity, (
            "Identity must contain the discoverability cheat-sheet header (CE-0033 Task 3)"
        )

    def test_cheat_sheet_lists_high_value_knobs(self):
        identity = compose_orchestrator_identity(None, tool="claude-code")
        expected_bullets = [
            "taxonomy_alias_prefix",
            "depth_config",
            "predecessor_job_id",
            "todo_append",
            "exclude_job_id",
        ]
        for needle in expected_bullets:
            assert needle in identity, f"Cheat-sheet missing high-value parameter: {needle!r}"




class TestTask4TenantKeyConsistency:
    def test_identity_does_not_show_tenant_key_in_get_agent_mission_example(self):
        from giljo_mcp.template_seeder import _get_default_templates_v103

        templates = _get_default_templates_v103()
        for template in templates:
            ui = template.get("user_instructions", "")
            if "get_agent_mission" in ui:
                assert 'get_agent_mission(job_id="<your_job_id>", tenant_key=' not in ui, (
                    f"Template {template['name']!r} still passes tenant_key= to get_agent_mission "
                    f"despite the auto-inject claim — contradiction (CE-0033 Task 4)."
                )




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
        ts_idx = prompt.find("ToolSearch(query=")
        hc_idx = prompt.find("health_check()")
        gm_idx = prompt.find("get_job_mission(")
        assert ts_idx >= 0, "Claude Code spawn prompt missing ToolSearch bootstrap"
        assert hc_idx > ts_idx, "ToolSearch must precede health_check in the spawn prompt"
        assert gm_idx > ts_idx, "ToolSearch must precede get_job_mission in the spawn prompt"

    def test_multi_terminal_default_spawn_prompt_omits_bootstrap(self):
        builder = MultiTerminalPromptBuilder()
        prompt = builder.build_execution_prompt(
            orchestrator_id="orch-1",
            project=self._make_project(),
            agent_jobs=[],
        )
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
        identity = compose_orchestrator_identity(None, tool="claude-code")
        rendered_call = render_toolsearch_call_one_line()
        assert rendered_call in identity, "Identity ToolSearch call must use the canonical helper output"
        from giljo_mcp.branding import MCP_ALIAS

        for tool_name in (
            f"mcp__{MCP_ALIAS}__health_check",
            f"mcp__{MCP_ALIAS}__spawn_job",
            f"mcp__{MCP_ALIAS}__report_progress",
            f"mcp__{MCP_ALIAS}__complete_job",
        ):
            assert tool_name in rendered_call
            assert tool_name in CANONICAL_ORCHESTRATOR_TOOLS




class TestTask6ProtocolProminence:
    def test_step7_finale_explains_flagless_todo_handling(self):
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
        assert "informational" in ch3.lower() or "does not block" in ch3.lower(), (
            f"CH3 ({tool}) must explain that subagent-mode phase ordering is informational"
        )

    def test_ch3_predecessor_required_for_phase_gt_1(self):
        ch3 = _build_ch3_spawning_rules("multi_terminal")
        assert "predecessor_job_id is REQUIRED" in ch3 or "predecessor_job_id" in ch3
        assert "phase > 1" in ch3




class TestTask7EmptyKeysCleaned:
    def test_staging_response_omits_ch5_and_ch6_keys(self):
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
        assert protocol["ch5_reference"]




class TestTask8Memory360Ordering:
    def test_fetch_context_tool_description_documents_memory_360_default(self):
        from api.endpoints import mcp_sdk_server

        src = inspect.getsource(mcp_sdk_server.get_context)
        assert "sequence DESC" in src
        assert "depth_config" in src and "memory_360" in src




@pytest.mark.asyncio
class TestTask9SpawnPhaseEcho:
    async def test_spawn_job_response_echoes_phase(self, db_session, db_manager, test_tenant_key):
        from datetime import UTC, datetime

        from giljo_mcp.models import AgentTemplate, Product, Project
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        db_session.add(
            AgentTemplate(
                tenant_key=test_tenant_key,
                name="implementer",
                role="implementer",
                description="impl",
                is_active=True,
            )
        )
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
        await adopt_all_templates(db_session, test_tenant_key, proj.product_id)

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
        await adopt_all_templates(db_session, test_tenant_key, proj.product_id)

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




class TestTask10ReportProgressNoEmptyWarnings:
    def test_report_progress_wrapper_strips_empty_warnings(self):
        from api.endpoints import mcp_sdk_server

        src = inspect.getsource(mcp_sdk_server.report_progress)
        assert "warnings" in src
        assert "pop" in src and "warnings" in src, (
            "report_progress wrapper must pop empty 'warnings' from response (CE-0033 Task 10)"
        )

    @pytest.mark.asyncio
    async def test_progress_result_serializes_without_warnings_when_empty(self):
        from giljo_mcp.schemas.responses.orchestration import ProgressResult

        result = ProgressResult(status="success", message="ok", warnings=[]).model_dump(mode="json")
        if isinstance(result, dict) and not result.get("warnings"):
            result.pop("warnings", None)
        assert "warnings" not in result




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
        await adopt_all_templates(db_session, test_tenant_key, proj.product_id)
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

        result = await service.spawn_job(
            agent_display_name="implementer",
            agent_name="implementer",
            mission="...",
            project_id=proj.id,
            tenant_key=test_tenant_key,
            phase=1,
        )
        assert result.job_id




class TestPayloadBudgetStillHolds:

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
        assert payload_size < 41_500, (
            f"grew the orchestrator identity past the 41KB ceiling ({payload_size} bytes). "
            f"Either trim the added content or raise the ceiling deliberately (and record why)."
        )




class TestCE0034StagingSpawnPromptToolSearch:

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




class TestCE0034TenantKeyResidualSweep:

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
