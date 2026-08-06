# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tests for OrchestrationService instruction-related methods (Handover 0451 - Phase 1: RED).

These methods are being moved from tool_accessor.py to OrchestrationService:
- get_staging_instructions() - Returns orchestrator context with framing-based instructions
- update_agent_mission() - Updates AgentJob.mission field

NOTE: check_succession_status() tests removed in Handover 0461a (manual succession only).
NOTE: create_successor_orchestrator() tests removed - tool deleted (succession via UI only).

All tests should FAIL initially (RED phase) since the methods don't exist yet in OrchestrationService.
"""

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


# ============================================================================
# TestGetOrchestratorInstructions
# ============================================================================


class TestGetOrchestratorInstructions:
    """Tests for get_staging_instructions() method."""

    @pytest.mark.asyncio
    async def test_returns_toggle_based_context(self, db_session: AsyncSession, test_product, test_project):
        """Test returns identity, project_description_inline, orchestrator_protocol (with CH2 fetch calls), agent_templates."""
        # Ensure test_product uses same tenant_key as test_project
        test_product.tenant_key = test_project.tenant_key
        await db_session.commit()
        await db_session.refresh(test_product)

        # Link test_project to test_product
        test_project.product_id = test_product.id
        await db_session.commit()
        await db_session.refresh(test_project)

        # Setup: Create orchestrator job and execution
        orchestrator_job = AgentJob(
            job_id=str(uuid4()),
            job_type="orchestrator",
            tenant_key=test_project.tenant_key,
            project_id=test_project.id,
            mission="Orchestrate the project",
            status="active",  # AgentJob status: active, completed, cancelled
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

        # Create service
        service = OrchestrationService(
            db_manager=MagicMock(), tenant_manager=MagicMock(), websocket_manager=MagicMock()
        )
        service._test_session = db_session
        service._mission._test_session = db_session
        service._mission._orchestration._test_session = db_session

        # Act: Get orchestrator instructions
        result = await service._mission.get_staging_instructions(
            job_id=orchestrator_job.job_id,
            tenant_key=test_project.tenant_key,
        )

        # Assert: Returns framing-based context structure
        assert "identity" in result
        assert "job_id" in result["identity"]
        assert "agent_id" in result["identity"]
        assert "project_id" in result["identity"]
        assert "tenant_key" in result["identity"]

        assert "project_description_inline" in result
        assert "description" in result["project_description_inline"]
        assert "mission" in result["project_description_inline"]

        # Handover 0823: context_fetch_instructions removed, fetch calls now inline in CH2 protocol
        assert "context_fetch_instructions" not in result
        assert "orchestrator_protocol" in result
        assert "get_context" in result["orchestrator_protocol"]["ch2_startup_sequence"]

        assert "agent_templates" in result
        assert isinstance(result["agent_templates"], list)

        assert "mcp_tools_available" in result
        assert isinstance(result["mcp_tools_available"], list)

    @pytest.mark.asyncio
    async def test_serena_guidance_present_when_toggle_on(self, db_session: AsyncSession, test_product, test_project):
        """INF-6007: serena_guidance + Serena tool names appear when the toggle is ON."""
        from giljo_mcp.services.settings_service import SettingsService

        test_product.tenant_key = test_project.tenant_key
        await db_session.commit()
        await db_session.refresh(test_product)
        test_project.product_id = test_product.id
        await db_session.commit()
        await db_session.refresh(test_project)

        # Toggle Serena ON for this tenant.
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
        # Orchestrator-specific framing must be present (not the generic notice).
        assert "STAGING DISCOVERY" in result["serena_guidance"]
        # BE-9260: the caveat is now workspace-conditional rather than asserting
        # "Python-only" as a universal fact -- see serena_instructions.py.
        assert "cover only the language(s) its LSP is configured for in this workspace" in result["serena_guidance"]
        # Serena tool names advertised in the tool list.
        for tool in ("find_symbol", "get_symbols_overview", "find_referencing_symbols", "search_for_pattern"):
            assert tool in result["mcp_tools_available"]

    @pytest.mark.asyncio
    async def test_serena_guidance_absent_when_toggle_off(self, db_session: AsyncSession, test_product, test_project):
        """INF-6007: serena_guidance + Serena tool names are absent when the toggle is OFF."""
        test_product.tenant_key = test_project.tenant_key
        await db_session.commit()
        await db_session.refresh(test_product)
        test_project.product_id = test_product.id
        await db_session.commit()
        await db_session.refresh(test_project)

        # No integrations setting written → toggle defaults OFF.
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
        # Serena symbol tools must NOT leak into the tool list when off.
        assert "find_symbol" not in result["mcp_tools_available"]
        assert "get_symbols_overview" not in result["mcp_tools_available"]

    @pytest.mark.asyncio
    async def test_validates_job_id_required(self, db_session: AsyncSession, test_project):
        """Test raises ValidationError if job_id is empty."""
        # Create service
        service = OrchestrationService(
            db_manager=MagicMock(), tenant_manager=MagicMock(), websocket_manager=MagicMock()
        )
        service._test_session = db_session

        # Handover 0730b: Exception-based error handling
        with pytest.raises(ValidationError) as exc_info:
            await service._mission.get_staging_instructions(
                job_id="",
                tenant_key=test_project.tenant_key,
            )

        assert "Job ID is required" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_validates_tenant_key_required(self, db_session: AsyncSession):
        """Test raises ValidationError if tenant_key is empty."""
        # Create service
        service = OrchestrationService(
            db_manager=MagicMock(), tenant_manager=MagicMock(), websocket_manager=MagicMock()
        )
        service._test_session = db_session

        # Handover 0730b: Exception-based error handling
        with pytest.raises(ValidationError) as exc_info:
            await service._mission.get_staging_instructions(
                job_id=str(uuid4()),
                tenant_key="",
            )

        assert "Tenant key is required" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_validates_job_is_orchestrator(self, db_session: AsyncSession, test_project):
        """Test returns error if job_type != 'orchestrator'."""
        # Setup: Create non-orchestrator job (implementer)
        implementer_job = AgentJob(
            job_id=str(uuid4()),
            job_type="implementer",  # NOT orchestrator
            tenant_key=test_project.tenant_key,
            project_id=test_project.id,
            mission="Implement features",
            status="active",  # AgentJob: active, completed, cancelled
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

        # Create service
        service = OrchestrationService(
            db_manager=MagicMock(), tenant_manager=MagicMock(), websocket_manager=MagicMock()
        )
        service._test_session = db_session
        service._mission._test_session = db_session
        service._mission._orchestration._test_session = db_session

        # Handover 0730b: Exception-based error handling
        with pytest.raises(ValidationError) as exc_info:
            await service._mission.get_staging_instructions(
                job_id=implementer_job.job_id,
                tenant_key=test_project.tenant_key,
            )

        # BE-8003b: wrong-state message now names the actual job_type and the
        # corrective tool instead of the bare "not an orchestrator".
        assert "not 'orchestrator'" in str(exc_info.value)
        assert "diagnose_project_state" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_enforces_tenant_isolation(self, db_session: AsyncSession, test_product):
        """Test enforces multi-tenant isolation (wrong tenant returns NOT_FOUND)."""
        tenant_a = "tenant-a"
        tenant_b = "tenant-b"

        # Setup: Create product in tenant A (need product for project)
        product_a = Product(
            id=str(uuid4()),
            name="Product A",
            tenant_key=tenant_a,
            is_active=True,
            product_memory={},
        )
        db_session.add(product_a)
        await db_session.commit()

        # Setup: Create orchestrator in tenant A
        project_a = Project(
            id=str(uuid4()),
            name="Project A",
            description="Project in tenant A",
            mission="Test mission for tenant A",  # Required field
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
            status="active",  # AgentJob: active, completed, cancelled
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

        # Create service
        service = OrchestrationService(
            db_manager=MagicMock(), tenant_manager=MagicMock(), websocket_manager=MagicMock()
        )
        service._test_session = db_session
        service._mission._test_session = db_session
        service._mission._orchestration._test_session = db_session

        # Handover 0730b: Exception-based error handling
        # Tenant B tries to access tenant A's orchestrator - should raise ResourceNotFoundError
        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service._mission.get_staging_instructions(
                job_id=orchestrator_job_a.job_id,
                tenant_key=tenant_b,  # Different tenant
            )

        assert "not found" in str(exc_info.value).lower()


# NOTE: TestCreateSuccessorOrchestrator removed - create_successor_orchestrator tool deleted.
# Succession is now user-triggered via UI button or /gil_handover slash command.


# ============================================================================
# TestUpdateAgentMission
# ============================================================================


class TestUpdateAgentMission:
    """Tests for update_agent_mission() method."""

    @pytest.mark.asyncio
    async def test_updates_job_mission(self, db_session: AsyncSession, test_project):
        """Test mission field updated in database."""
        # Setup: Create agent job with original mission
        agent_job = AgentJob(
            job_id=str(uuid4()),
            job_type="orchestrator",
            tenant_key=test_project.tenant_key,
            project_id=test_project.id,
            mission="Original mission",
            status="active",  # AgentJob: active, completed, cancelled
        )
        db_session.add(agent_job)
        await db_session.commit()

        # Create service
        service = OrchestrationService(
            db_manager=MagicMock(), tenant_manager=MagicMock(), websocket_manager=MagicMock()
        )
        service._test_session = db_session
        service._mission._test_session = db_session
        service._mission._orchestration._test_session = db_session

        # Act: Update mission
        new_mission = "Updated mission with execution plan"
        result = await service._mission.update_agent_mission(
            job_id=agent_job.job_id,
            tenant_key=test_project.tenant_key,
            mission=new_mission,
        )

        # Handover 0731c: Returns MissionUpdateResult typed model
        assert isinstance(result, MissionUpdateResult)
        assert result.mission_updated is True
        assert result.mission_length == len(new_mission)

        # Verify in database
        await db_session.refresh(agent_job)
        assert agent_job.mission == new_mission

    @pytest.mark.asyncio
    async def test_returns_not_found_for_invalid_job(self, db_session: AsyncSession, test_project):
        """Test raises exception for non-existent job."""
        # Create service
        service = OrchestrationService(
            db_manager=MagicMock(), tenant_manager=MagicMock(), websocket_manager=MagicMock()
        )
        service._test_session = db_session
        service._mission._test_session = db_session

        # Handover 0730b: Exception-based error handling
        # update_agent_mission wraps ResourceNotFoundError in OrchestrationError
        with pytest.raises(OrchestrationError) as exc_info:
            await service._mission.update_agent_mission(
                job_id=str(uuid4()),  # Non-existent
                tenant_key=test_project.tenant_key,
                mission="New mission",
            )

        # Assert: Proper exception raised (wrapped in OrchestrationError)
        assert "failed to update agent mission" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_enforces_tenant_isolation(self, db_session: AsyncSession, test_product):
        """Test wrong tenant returns NOT_FOUND."""
        tenant_a = "tenant-a"
        tenant_b = "tenant-b"

        # Setup: Create product in tenant A
        product_a = Product(
            id=str(uuid4()),
            name="Product A",
            tenant_key=tenant_a,
            is_active=True,
            product_memory={},
        )
        db_session.add(product_a)
        await db_session.commit()

        # Setup: Create job in tenant A
        project_a = Project(
            id=str(uuid4()),
            name="Project A",
            description="Project in tenant A",
            mission="Test mission for tenant A",  # Required field
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
            status="active",  # AgentJob: active, completed, cancelled
        )
        db_session.add(job_a)
        await db_session.commit()

        # Create service
        service = OrchestrationService(
            db_manager=MagicMock(), tenant_manager=MagicMock(), websocket_manager=MagicMock()
        )
        service._test_session = db_session
        service._mission._test_session = db_session

        # Handover 0730b: Exception-based error handling
        # Tenant B tries to update tenant A's job - should raise OrchestrationError
        # (update_agent_mission wraps ResourceNotFoundError in OrchestrationError)
        with pytest.raises(OrchestrationError) as exc_info:
            await service._mission.update_agent_mission(
                job_id=job_a.job_id,
                tenant_key=tenant_b,  # Different tenant
                mission="Malicious mission update",
            )

        assert "failed to update agent mission" in str(exc_info.value).lower()

        # Verify original mission unchanged
        await db_session.refresh(job_a)
        assert job_a.mission == "Original mission in tenant A"
