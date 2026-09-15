# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import OrchestrationError, ResourceNotFoundError, ValidationError
from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.schemas.service_responses import MissionUpdateResult
from giljo_mcp.services.orchestration_service import OrchestrationService




class TestGetOrchestratorInstructions:

    @pytest.mark.asyncio
    async def test_returns_toggle_based_context(self, db_session: AsyncSession, test_product, test_project):
        test_product.tenant_key = test_project.tenant_key
        await db_session.commit()
        await db_session.refresh(test_product)

        test_project.product_id = test_product.id
        await db_session.commit()
        await db_session.refresh(test_project)

        orchestrator_job = AgentJob(
            job_id=str(uuid4()),
            job_type="orchestrator",
            tenant_key=test_project.tenant_key,
            project_id=test_project.id,
            mission="Orchestrate the project",
            status="active",
            job_metadata={"user_id": str(uuid4())},
        )
        db_session.add(orchestrator_job)
        await db_session.commit()

        orchestrator_execution = AgentExecution(
            agent_id=str(uuid4()),
            job_id=orchestrator_job.job_id,
            tenant_key=test_project.tenant_key,
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            status="waiting",
        )
        db_session.add(orchestrator_execution)
        await db_session.commit()

        service = OrchestrationService(
            db_manager=MagicMock(), tenant_manager=MagicMock(), websocket_manager=MagicMock()
        )
        service._test_session = db_session
        service._mission._test_session = db_session
        service._mission._orchestration._test_session = db_session

        result = await service._mission.get_staging_instructions(
            job_id=orchestrator_job.job_id,
            tenant_key=test_project.tenant_key,
        )

        assert "identity" in result
        assert "job_id" in result["identity"]
        assert "agent_id" in result["identity"]
        assert "project_id" in result["identity"]
        assert "tenant_key" in result["identity"]

        assert "project_description_inline" in result
        assert "description" in result["project_description_inline"]
        assert "mission" in result["project_description_inline"]

        assert "context_fetch_instructions" not in result
        assert "orchestrator_protocol" in result
        assert "get_context" in result["orchestrator_protocol"]["ch2_startup_sequence"]

        assert "agent_templates" in result
        assert isinstance(result["agent_templates"], list)

        assert "mcp_tools_available" in result
        assert isinstance(result["mcp_tools_available"], list)

    @pytest.mark.asyncio
    async def test_serena_guidance_present_when_toggle_on(self, db_session: AsyncSession, test_product, test_project):
        from giljo_mcp.services.settings_service import SettingsService

        test_product.tenant_key = test_project.tenant_key
        await db_session.commit()
        await db_session.refresh(test_product)
        test_project.product_id = test_product.id
        await db_session.commit()
        await db_session.refresh(test_project)

        settings_svc = SettingsService(db_session, test_project.tenant_key)
        await settings_svc.update_settings("integrations", {"serena_mcp": {"use_in_prompts": True}})

        orchestrator_job = AgentJob(
            job_id=str(uuid4()),
            job_type="orchestrator",
            tenant_key=test_project.tenant_key,
            project_id=test_project.id,
            mission="Orchestrate the project",
            status="active",
            job_metadata={},
        )
        db_session.add(orchestrator_job)
        await db_session.commit()

        orchestrator_execution = AgentExecution(
            agent_id=str(uuid4()),
            job_id=orchestrator_job.job_id,
            tenant_key=test_project.tenant_key,
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            status="waiting",
        )
        db_session.add(orchestrator_execution)
        await db_session.commit()

        service = OrchestrationService(
            db_manager=MagicMock(), tenant_manager=MagicMock(), websocket_manager=MagicMock()
        )
        service._test_session = db_session
        service._mission._test_session = db_session
        service._mission._orchestration._test_session = db_session

        result = await service._mission.get_staging_instructions(
            job_id=orchestrator_job.job_id,
            tenant_key=test_project.tenant_key,
        )

        assert result["integrations"]["serena_mcp_enabled"] is True
        assert "serena_guidance" in result
        assert "Serena MCP" in result["serena_guidance"]
        assert "STAGING DISCOVERY" in result["serena_guidance"]
        assert "cover only the language(s) its LSP is configured for in this workspace" in result["serena_guidance"]
        for tool in ("find_symbol", "get_symbols_overview", "find_referencing_symbols", "search_for_pattern"):
            assert tool in result["mcp_tools_available"]

    @pytest.mark.asyncio
    async def test_serena_guidance_absent_when_toggle_off(self, db_session: AsyncSession, test_product, test_project):
        test_product.tenant_key = test_project.tenant_key
        await db_session.commit()
        await db_session.refresh(test_product)
        test_project.product_id = test_product.id
        await db_session.commit()
        await db_session.refresh(test_project)

        orchestrator_job = AgentJob(
            job_id=str(uuid4()),
            job_type="orchestrator",
            tenant_key=test_project.tenant_key,
            project_id=test_project.id,
            mission="Orchestrate the project",
            status="active",
            job_metadata={},
        )
        db_session.add(orchestrator_job)
        await db_session.commit()

        orchestrator_execution = AgentExecution(
            agent_id=str(uuid4()),
            job_id=orchestrator_job.job_id,
            tenant_key=test_project.tenant_key,
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            status="waiting",
        )
        db_session.add(orchestrator_execution)
        await db_session.commit()

        service = OrchestrationService(
            db_manager=MagicMock(), tenant_manager=MagicMock(), websocket_manager=MagicMock()
        )
        service._test_session = db_session
        service._mission._test_session = db_session
        service._mission._orchestration._test_session = db_session

        result = await service._mission.get_staging_instructions(
            job_id=orchestrator_job.job_id,
            tenant_key=test_project.tenant_key,
        )

        assert result["integrations"]["serena_mcp_enabled"] is False
        assert "serena_guidance" not in result
        assert "find_symbol" not in result["mcp_tools_available"]
        assert "get_symbols_overview" not in result["mcp_tools_available"]

    @pytest.mark.asyncio
    async def test_validates_job_id_required(self, db_session: AsyncSession, test_project):
        service = OrchestrationService(
            db_manager=MagicMock(), tenant_manager=MagicMock(), websocket_manager=MagicMock()
        )
        service._test_session = db_session

        with pytest.raises(ValidationError) as exc_info:
            await service._mission.get_staging_instructions(
                job_id="",
                tenant_key=test_project.tenant_key,
            )

        assert "Job ID is required" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_validates_tenant_key_required(self, db_session: AsyncSession):
        service = OrchestrationService(
            db_manager=MagicMock(), tenant_manager=MagicMock(), websocket_manager=MagicMock()
        )
        service._test_session = db_session

        with pytest.raises(ValidationError) as exc_info:
            await service._mission.get_staging_instructions(
                job_id=str(uuid4()),
                tenant_key="",
            )

        assert "Tenant key is required" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_validates_job_is_orchestrator(self, db_session: AsyncSession, test_project):
        implementer_job = AgentJob(
            job_id=str(uuid4()),
            job_type="implementer",
            tenant_key=test_project.tenant_key,
            project_id=test_project.id,
            mission="Implement features",
            status="active",
        )
        db_session.add(implementer_job)
        await db_session.commit()

        implementer_execution = AgentExecution(
            agent_id=str(uuid4()),
            job_id=implementer_job.job_id,
            tenant_key=test_project.tenant_key,
            agent_display_name="implementer",
            agent_name="implementer",
            status="waiting",
        )
        db_session.add(implementer_execution)
        await db_session.commit()

        service = OrchestrationService(
            db_manager=MagicMock(), tenant_manager=MagicMock(), websocket_manager=MagicMock()
        )
        service._test_session = db_session
        service._mission._test_session = db_session
        service._mission._orchestration._test_session = db_session

        with pytest.raises(ValidationError) as exc_info:
            await service._mission.get_staging_instructions(
                job_id=implementer_job.job_id,
                tenant_key=test_project.tenant_key,
            )

        assert "not 'orchestrator'" in str(exc_info.value)
        assert "diagnose_project_state" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_enforces_tenant_isolation(self, db_session: AsyncSession, test_product):
        tenant_a = "tenant-a"
        tenant_b = "tenant-b"

        product_a = Product(
            id=str(uuid4()),
            name="Product A",
            tenant_key=tenant_a,
            is_active=True,
            product_memory={},
        )
        db_session.add(product_a)
        await db_session.commit()

        project_a = Project(
            id=str(uuid4()),
            name="Project A",
            description="Project in tenant A",
            mission="Test mission for tenant A",
            tenant_key=tenant_a,
            product_id=product_a.id,
            series_number=random.randint(1, 9000),
        )
        db_session.add(project_a)
        await db_session.commit()

        orchestrator_job_a = AgentJob(
            job_id=str(uuid4()),
            job_type="orchestrator",
            tenant_key=tenant_a,
            project_id=project_a.id,
            mission="Orchestrate project A",
            status="active",
        )
        db_session.add(orchestrator_job_a)
        await db_session.commit()

        orchestrator_execution_a = AgentExecution(
            agent_id=str(uuid4()),
            job_id=orchestrator_job_a.job_id,
            tenant_key=tenant_a,
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            status="waiting",
        )
        db_session.add(orchestrator_execution_a)
        await db_session.commit()

        service = OrchestrationService(
            db_manager=MagicMock(), tenant_manager=MagicMock(), websocket_manager=MagicMock()
        )
        service._test_session = db_session
        service._mission._test_session = db_session
        service._mission._orchestration._test_session = db_session

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service._mission.get_staging_instructions(
                job_id=orchestrator_job_a.job_id,
                tenant_key=tenant_b,
            )

        assert "not found" in str(exc_info.value).lower()






class TestUpdateAgentMission:

    @pytest.mark.asyncio
    async def test_updates_job_mission(self, db_session: AsyncSession, test_project):
        agent_job = AgentJob(
            job_id=str(uuid4()),
            job_type="orchestrator",
            tenant_key=test_project.tenant_key,
            project_id=test_project.id,
            mission="Original mission",
            status="active",
        )
        db_session.add(agent_job)
        await db_session.commit()

        service = OrchestrationService(
            db_manager=MagicMock(), tenant_manager=MagicMock(), websocket_manager=MagicMock()
        )
        service._test_session = db_session
        service._mission._test_session = db_session
        service._mission._orchestration._test_session = db_session

        new_mission = "Updated mission with execution plan"
        result = await service._mission.update_agent_mission(
            job_id=agent_job.job_id,
            tenant_key=test_project.tenant_key,
            mission=new_mission,
        )

        assert isinstance(result, MissionUpdateResult)
        assert result.mission_updated is True
        assert result.mission_length == len(new_mission)

        await db_session.refresh(agent_job)
        assert agent_job.mission == new_mission

    @pytest.mark.asyncio
    async def test_returns_not_found_for_invalid_job(self, db_session: AsyncSession, test_project):
        service = OrchestrationService(
            db_manager=MagicMock(), tenant_manager=MagicMock(), websocket_manager=MagicMock()
        )
        service._test_session = db_session
        service._mission._test_session = db_session

        with pytest.raises(OrchestrationError) as exc_info:
            await service._mission.update_agent_mission(
                job_id=str(uuid4()),
                tenant_key=test_project.tenant_key,
                mission="New mission",
            )

        assert "failed to update agent mission" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_enforces_tenant_isolation(self, db_session: AsyncSession, test_product):
        tenant_a = "tenant-a"
        tenant_b = "tenant-b"

        product_a = Product(
            id=str(uuid4()),
            name="Product A",
            tenant_key=tenant_a,
            is_active=True,
            product_memory={},
        )
        db_session.add(product_a)
        await db_session.commit()

        project_a = Project(
            id=str(uuid4()),
            name="Project A",
            description="Project in tenant A",
            mission="Test mission for tenant A",
            tenant_key=tenant_a,
            product_id=product_a.id,
            series_number=random.randint(1, 9000),
        )
        db_session.add(project_a)
        await db_session.commit()

        job_a = AgentJob(
            job_id=str(uuid4()),
            job_type="orchestrator",
            tenant_key=tenant_a,
            project_id=project_a.id,
            mission="Original mission in tenant A",
            status="active",
        )
        db_session.add(job_a)
        await db_session.commit()

        service = OrchestrationService(
            db_manager=MagicMock(), tenant_manager=MagicMock(), websocket_manager=MagicMock()
        )
        service._test_session = db_session
        service._mission._test_session = db_session

        with pytest.raises(OrchestrationError) as exc_info:
            await service._mission.update_agent_mission(
                job_id=job_a.job_id,
                tenant_key=tenant_b,
                mission="Malicious mission update",
            )

        assert "failed to update agent mission" in str(exc_info.value).lower()

        await db_session.refresh(job_a)
        assert job_a.mission == "Original mission in tenant A"
