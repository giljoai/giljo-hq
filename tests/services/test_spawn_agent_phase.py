# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
TDD Tests for Handover 0411a: Recommended Execution Order (Phase Labels).

RED PHASE - These tests verify:
1. spawn_job() accepts and stores `phase` parameter
2. spawn_job() populates `template_id` when template found
3. list_jobs() includes `phase` in response
4. get_staging_instructions() includes phase instructions in multi-terminal mode
5. get_staging_instructions() excludes phase instructions in CLI mode
"""

import random
import uuid
from datetime import UTC

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models import AgentJob, AgentTemplate, Product, Project


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest_asyncio.fixture
async def test_tenant_key() -> str:
    """Generate unique tenant key for test isolation."""
    return f"tk_test_{uuid.uuid4().hex[:16]}"


@pytest_asyncio.fixture
async def test_agent_templates(db_session, test_tenant_key):
    """Create agent templates for phase label tests."""
    template_names = ["analyzer", "implementer", "tester"]
    for name in template_names:
        template = AgentTemplate(
            tenant_key=test_tenant_key,
            name=name,
            role=name,
            description=f"Test template for {name}",
            system_instructions=f"# {name}\nTest agent.",
            is_active=True,
        )
        db_session.add(template)
    await db_session.commit()


@pytest_asyncio.fixture
async def test_project(db_session, test_tenant_key, test_agent_templates) -> Project:
    """Create test project with templates pre-seeded."""
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
        name="Phase Label Test Project",
        description="Test project for 0411a phase labels",
        mission="Test mission for phase labels",
        status="active",
        tenant_key=test_tenant_key,
        product_id=_owning_product_project.id,
        execution_mode="multi_terminal",
        implementation_launched_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


# ============================================================================
# Test Class: Phase Parameter on spawn_job
# ============================================================================


@pytest.mark.asyncio
class TestSpawnAgentJobPhase:
    """Tests that spawn_job correctly handles the `phase` parameter."""

    async def test_spawn_job_stores_phase_when_provided(self, db_session, db_manager, test_project, test_tenant_key):
        """Phase value is stored on the AgentJob record when provided."""
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        # CE-0033 Task 11: phase > 1 requires a non-empty predecessor_job_id.
        # Spawn a phase-1 predecessor first, then a phase-2 successor chained to it.
        predecessor = await service.spawn_job(
            agent_display_name="analyzer",
            agent_name="analyzer",
            mission="Analyze first",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
            phase=1,
        )

        result = await service.spawn_job(
            agent_display_name="implementer",
            agent_name="implementer",
            mission="Implement feature X",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
            phase=2,
            predecessor_job_id=predecessor.job_id,
        )

        # Verify AgentJob has phase=2
        job_stmt = select(AgentJob).where(AgentJob.job_id == result.job_id)
        job_result = await db_session.execute(job_stmt)
        job = job_result.scalar_one()
        assert job.phase == 2

    async def test_spawn_job_phase_defaults_to_none(self, db_session, db_manager, test_project, test_tenant_key):
        """Phase defaults to None when not provided (backward compatible)."""
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        result = await service.spawn_job(
            agent_display_name="analyzer",
            agent_name="analyzer",
            mission="Analyze codebase",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )

        # Verify AgentJob has phase=None
        job_stmt = select(AgentJob).where(AgentJob.job_id == result.job_id)
        job_result = await db_session.execute(job_stmt)
        job = job_result.scalar_one()
        assert job.phase is None

    async def test_spawn_job_populates_template_id(self, db_session, db_manager, test_project, test_tenant_key):
        """template_id FK is populated when a matching template is found."""
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        # CE-0033 Task 11: phase > 1 requires a non-empty predecessor_job_id.
        predecessor = await service.spawn_job(
            agent_display_name="implementer",
            agent_name="implementer",
            mission="Implement before tests",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
            phase=1,
        )

        result = await service.spawn_job(
            agent_display_name="tester",
            agent_name="tester",
            mission="Run test suite",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
            phase=3,
            predecessor_job_id=predecessor.job_id,
        )

        # Verify AgentJob.template_id is set
        job_stmt = select(AgentJob).where(AgentJob.job_id == result.job_id)
        job_result = await db_session.execute(job_stmt)
        job = job_result.scalar_one()
        assert job.template_id is not None

        # Verify it matches the actual template
        tmpl_stmt = select(AgentTemplate).where(
            AgentTemplate.name == "tester",
            AgentTemplate.tenant_key == test_tenant_key,
        )
        tmpl_result = await db_session.execute(tmpl_stmt)
        template = tmpl_result.scalar_one()
        assert job.template_id == template.id


# ============================================================================
# Test Class: list_jobs includes phase
# ============================================================================


@pytest.mark.asyncio
class TestListJobsPhase:
    """Tests that list_jobs includes phase in response."""

    async def test_list_jobs_includes_phase_in_response(self, db_session, db_manager, test_project, test_tenant_key):
        """Phase field appears in job dict from list_jobs()."""
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        # Spawn an agent with phase=1
        await service.spawn_job(
            agent_display_name="analyzer",
            agent_name="analyzer",
            mission="Analyze for phase test",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
            phase=1,
        )

        # List jobs
        result = await service.list_jobs(
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )

        assert len(result.jobs) >= 1
        job_dict = result.jobs[0]
        assert "phase" in job_dict
        assert job_dict["phase"] == 1


# ============================================================================
# Test Class: Orchestrator protocol phase instructions
# ============================================================================


@pytest.mark.asyncio
class TestOrchestratorPhaseInstructions:
    """Tests that orchestrator protocol includes/excludes phase instructions based on mode."""

    async def test_phase_instructions_included_in_multi_terminal_mode(self, db_session, db_manager, test_tenant_key):
        """Phase assignment instructions appear in multi-terminal (default) mode."""
        from datetime import datetime

        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        # Create project in multi_terminal mode (default)
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
            name="Multi-Terminal Phase Test",
            description="Test project",
            mission="Test mission",
            status="active",
            tenant_key=test_tenant_key,
            product_id=_owning_product_project.id,
            execution_mode="multi_terminal",
            implementation_launched_at=datetime.now(UTC),
            series_number=random.randint(1, 9000),
        )
        db_session.add(project)

        # Create templates for this tenant
        for name in ["analyzer", "implementer"]:
            template = AgentTemplate(
                tenant_key=test_tenant_key,
                name=name,
                role=name,
                description=f"Test {name}",
                system_instructions=f"# {name}",
                is_active=True,
            )
            db_session.add(template)
        await db_session.commit()

        # Spawn orchestrator job
        result = await service.spawn_job(
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            mission="Orchestrate project",
            project_id=project.id,
            tenant_key=test_tenant_key,
        )

        # Get orchestrator instructions
        instructions = await service._mission.get_staging_instructions(
            job_id=result.job_id,
            tenant_key=test_tenant_key,
        )

        # Phase instructions should be present as a separate key in multi-terminal mode
        phase_instructions = instructions.get("phase_assignment_instructions", "")
        assert "Phase 1" in phase_instructions, (
            "Phase instructions missing from multi-terminal orchestrator instructions"
        )
        assert "phase" in phase_instructions.lower()

    async def test_phase_instructions_excluded_in_cli_mode(self, db_session, db_manager, test_tenant_key):
        """Phase assignment instructions do NOT appear in CLI mode."""
        from datetime import datetime

        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        # Create project in claude_code_cli mode
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
            name="CLI Mode Phase Test",
            description="Test project",
            mission="Test mission",
            status="active",
            tenant_key=test_tenant_key,
            product_id=_owning_product_project.id,
            execution_mode="claude_code_cli",
            implementation_launched_at=datetime.now(UTC),
            series_number=random.randint(1, 9000),
        )
        db_session.add(project)

        # Create templates for this tenant
        for name in ["analyzer", "implementer"]:
            template = AgentTemplate(
                tenant_key=test_tenant_key,
                name=name,
                role=name,
                description=f"Test {name}",
                system_instructions=f"# {name}",
                is_active=True,
            )
            db_session.add(template)
        await db_session.commit()

        # Spawn orchestrator job
        result = await service.spawn_job(
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            mission="Orchestrate project",
            project_id=project.id,
            tenant_key=test_tenant_key,
        )

        # Get orchestrator instructions
        instructions = await service._mission.get_staging_instructions(
            job_id=result.job_id,
            tenant_key=test_tenant_key,
        )

        # Phase assignment instructions should NOT be present in CLI mode
        assert "phase_assignment_instructions" not in instructions, (
            "Phase assignment instructions should NOT appear in CLI mode"
        )
