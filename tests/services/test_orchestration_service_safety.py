# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
TDD Tests for OrchestrationService Safety Features (Backported from tools layer).

RED PHASE - These tests WILL FAIL initially until the service layer is updated.

Purpose: Verify OrchestrationService.spawn_job() enforces:
1. Duplicate orchestrator prevention (only one active orchestrator per project)
2. Agent name validation (agent_name must match an active AgentTemplate)

Test Coverage:
- test_spawn_duplicate_orchestrator_raises_error
- test_spawn_orchestrator_succession_allowed
- test_spawn_invalid_agent_name_raises_error
- test_spawn_valid_agent_name_succeeds
"""

import random
import uuid
from datetime import UTC

import pytest
import pytest_asyncio

from giljo_mcp.exceptions import AlreadyExistsError, ValidationError
from giljo_mcp.models import AgentTemplate, Product, Project


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest_asyncio.fixture
async def test_tenant_key() -> str:
    """Generate unique tenant key for test isolation."""
    return f"tk_safety_{uuid.uuid4().hex[:16]}"


@pytest_asyncio.fixture
async def test_project(db_session, test_tenant_key) -> Project:
    """Create test project for agent jobs."""
    from datetime import datetime

    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=test_tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        id=str(uuid.uuid4()),
        name="Safety Features Test Project",
        description="Test project for safety feature backport",
        mission="Test mission for safety features",
        status="active",
        tenant_key=test_tenant_key,
        product_id=_owning_product_project.id,
        execution_mode="multi_terminal",
        # Handover 0709: Set implementation_launched_at to bypass phase gate
        implementation_launched_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest_asyncio.fixture
async def test_agent_template(db_session, test_tenant_key) -> AgentTemplate:
    """Create an active agent template for validation tests."""
    template = AgentTemplate(
        tenant_key=test_tenant_key,
        name="tdd-implementor",
        description="TDD Implementor Agent",
        is_active=True,
    )
    db_session.add(template)
    await db_session.commit()
    await db_session.refresh(template)
    return template


@pytest_asyncio.fixture
async def orchestration_service(db_manager, db_session):
    """Create OrchestrationService with test session."""
    from giljo_mcp.services.orchestration_service import OrchestrationService
    from giljo_mcp.tenant import TenantManager

    tenant_manager = TenantManager()
    return OrchestrationService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )


# ============================================================================
# Test Class: Duplicate Orchestrator Prevention
# ============================================================================


@pytest.mark.asyncio
class TestDuplicateOrchestratorPrevention:
    """
    Tests that spawn_job prevents duplicate orchestrators for the same project.

    Expected Behavior:
    - Only one active orchestrator (status "waiting" or "working") per project
    - Raises AlreadyExistsError if a duplicate is attempted
    - Succession (parent_job_id matches existing orchestrator's agent_id) is allowed
    """

    async def test_spawn_duplicate_orchestrator_raises_error(
        self, orchestration_service, test_project, test_tenant_key
    ):
        """Spawning a second orchestrator for the same project raises AlreadyExistsError."""
        # First orchestrator - should succeed
        result1 = await orchestration_service.spawn_job(
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            mission="First orchestrator mission",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )
        assert result1.job_id
        assert result1.agent_id

        # Second orchestrator - should raise AlreadyExistsError
        with pytest.raises(AlreadyExistsError) as exc_info:
            await orchestration_service.spawn_job(
                agent_display_name="orchestrator",
                agent_name="orchestrator",
                mission="Second orchestrator mission",
                project_id=test_project.id,
                tenant_key=test_tenant_key,
            )

        assert "already exists" in str(exc_info.value).lower()

    async def test_spawn_orchestrator_succession_allowed(self, orchestration_service, test_project, test_tenant_key):
        """Spawning with parent_job_id matching existing orchestrator's agent_id succeeds (handover succession)."""
        # First orchestrator
        result1 = await orchestration_service.spawn_job(
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            mission="Original orchestrator mission",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )
        existing_agent_id = result1.agent_id

        # Successor orchestrator with parent_job_id = existing orchestrator's agent_id
        result2 = await orchestration_service.spawn_job(
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            mission="Successor orchestrator mission",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
            parent_job_id=existing_agent_id,
        )

        assert result2.job_id
        assert result2.agent_id
        # Successor should be a different executor
        assert result2.agent_id != existing_agent_id


# ============================================================================
# Test Class: Agent Name Validation
# ============================================================================


@pytest.mark.asyncio
class TestAgentNameValidation:
    """
    Tests that spawn_job validates agent_name against active AgentTemplate records.

    Expected Behavior:
    - agent_name must match an active template's name for the tenant
    - Raises ValidationError with the list of valid names if invalid
    - Orchestrators are exempt from this check (agent_display_name == "orchestrator")
    """

    async def test_spawn_invalid_agent_name_raises_error(
        self, orchestration_service, test_project, test_tenant_key, test_agent_template
    ):
        """Spawning with agent_name not matching any active template raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            await orchestration_service.spawn_job(
                agent_display_name="implementer",
                agent_name="nonexistent-agent-xyz",
                mission="Some mission",
                project_id=test_project.id,
                tenant_key=test_tenant_key,
            )

        error_message = str(exc_info.value).lower()
        assert "invalid" in error_message or "agent_name" in error_message

    async def test_spawn_valid_agent_name_succeeds(
        self, orchestration_service, test_project, test_tenant_key, test_agent_template
    ):
        """Spawning with agent_name matching an active template succeeds."""
        result = await orchestration_service.spawn_job(
            agent_display_name="implementer",
            agent_name="tdd-implementor",
            mission="Implement feature with TDD",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )

        assert result.job_id
        assert result.agent_id
        # Verify the agent was actually created
        from giljo_mcp.schemas.service_responses import SpawnResult

        assert isinstance(result, SpawnResult)
