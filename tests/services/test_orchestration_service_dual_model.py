# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
TDD Tests for OrchestrationService Dual-Model Migration (Handover 0358b).

RED PHASE - These tests WILL FAIL initially.

Purpose: Verify OrchestrationService correctly uses AgentJob + AgentExecution
         instead of monolithic MCPAgentJob model.

Key Semantic Changes:
- job_id: Now refers to WORK ORDER (persists across succession)
- agent_id: NEW - Refers to EXECUTOR (changes on succession)
- spawned_by: Now points to agent_id (executor), not job_id
- succeeded_by: Renamed from handover_to (points to agent_id)

Design Philosophy:
- AgentJob: Persistent work order (mission, scope) - WHAT
- AgentExecution: Executor instance (who, when, status) - WHO
- Succession: New execution, SAME job (job_id persists, agent_id changes)

Test Coverage:
1. spawn_job creates BOTH AgentJob and AgentExecution
2. Succession creates new execution, NOT new job
3. Query methods correctly join AgentJob + AgentExecution
4. Update methods target AgentExecution (not AgentJob)
"""

import random
import uuid
from datetime import UTC

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models import AgentExecution, AgentJob, AgentTemplate, Product, Project


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest_asyncio.fixture
async def test_tenant_key() -> str:
    """Generate unique tenant key for test isolation."""
    return f"tk_test_{uuid.uuid4().hex[:16]}"


@pytest_asyncio.fixture
async def test_agent_templates(db_session, test_tenant_key):
    """Create agent templates matching agent_name values used in tests."""
    template_names = ["impl-1", "auth-impl", "test-1", "impl-waiting", "test-working", "tester-1"]
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
    """Create test project for agent jobs (depends on test_agent_templates)."""
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
        name="Dual Model Test Project",
        description="Test project for dual-model migration",
        mission="Test mission for dual-model migration",
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


# ============================================================================
# Test Class: spawn_job Creates BOTH Job and Execution
# ============================================================================


@pytest.mark.asyncio
class TestSpawnAgentJobDualModel:
    """
    Tests that spawn_job creates BOTH AgentJob and AgentExecution.

    Expected Behavior:
    - Creates AgentJob record (work order)
    - Creates AgentExecution record (executor)
    - job_id and agent_id are DIFFERENT UUIDs
    - mission stored in AgentJob only (not duplicated)
    - Returns dict with both job_id and agent_id keys
    """

    async def test_spawn_creates_both_job_and_execution(self, db_session, db_manager, test_project, test_tenant_key):
        """Verify spawn_job creates BOTH AgentJob and AgentExecution."""
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        result = await service.spawn_job(
            agent_display_name="implementer",
            agent_name="impl-1",
            mission="Implement authentication system",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )

        # Handover 0731c: Returns SpawnResult typed model
        from giljo_mcp.schemas.service_responses import SpawnResult

        assert isinstance(result, SpawnResult)
        assert result.job_id
        assert result.agent_id

        # Verify job_id and agent_id are DIFFERENT UUIDs
        assert result.job_id != result.agent_id
        assert isinstance(uuid.UUID(result.job_id), uuid.UUID)
        assert isinstance(uuid.UUID(result.agent_id), uuid.UUID)

        # Verify AgentJob was created
        job_stmt = select(AgentJob).where(AgentJob.job_id == result.job_id)
        job_result = await db_session.execute(job_stmt)
        job = job_result.scalar_one_or_none()
        assert job is not None
        # DB stores mission (may include template injection prefix)
        assert "Implement authentication system" in job.mission
        assert job.job_type == "implementer"
        assert job.tenant_key == test_tenant_key
        assert job.project_id == test_project.id

        # Verify AgentExecution was created
        exec_stmt = select(AgentExecution).where(AgentExecution.agent_id == result.agent_id)
        exec_result = await db_session.execute(exec_stmt)
        execution = exec_result.scalar_one_or_none()
        assert execution is not None
        assert execution.job_id == result.job_id
        assert execution.agent_display_name == "implementer"
        assert execution.tenant_key == test_tenant_key

    async def test_spawn_stores_mission_in_job_not_execution(
        self, db_session, db_manager, test_project, test_tenant_key
    ):
        """Verify mission is stored in AgentJob, NOT duplicated in AgentExecution."""
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        mission = "Build OAuth2 authentication with JWT tokens"
        result = await service.spawn_job(
            agent_display_name="implementer",
            agent_name="auth-impl",
            mission=mission,
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )

        # Verify mission in AgentJob (may include template injection prefix)
        job_stmt = select(AgentJob).where(AgentJob.job_id == result.job_id)
        job_result = await db_session.execute(job_stmt)
        job = job_result.scalar_one()
        assert mission in job.mission

        # Verify AgentExecution does NOT have mission field
        exec_stmt = select(AgentExecution).where(AgentExecution.agent_id == result.agent_id)
        exec_result = await db_session.execute(exec_stmt)
        execution = exec_result.scalar_one()
        # AgentExecution should NOT have a 'mission' attribute
        assert not hasattr(execution, "mission")

    async def test_spawn_returns_both_ids(self, db_session, db_manager, test_project, test_tenant_key):
        """Verify spawn_job returns dict with both job_id and agent_id."""
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        result = await service.spawn_job(
            agent_display_name="tester",
            agent_name="test-1",
            mission="Write integration tests",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )

        # Handover 0731c: Returns SpawnResult typed model
        from giljo_mcp.schemas.service_responses import SpawnResult

        assert isinstance(result, SpawnResult)
        assert result.job_id
        assert result.agent_id

        # Verify both IDs are valid UUIDs
        try:
            uuid.UUID(result.job_id)
            uuid.UUID(result.agent_id)
        except ValueError:
            pytest.fail("job_id or agent_id is not a valid UUID")


# NOTE: TestSuccessionDualModel removed - create_successor_orchestrator tool deleted.
# Succession is now user-triggered via UI button or /gil_handover slash command.


# ============================================================================
# Test Class: Query Methods Correctly Join Job + Execution
# ============================================================================


@pytest.mark.asyncio
class TestQueryMethodsDualModel:
    """
    Tests that query methods correctly join AgentJob + AgentExecution.

    Expected Behavior:
    - list_jobs returns both job_id and agent_id
    - get_pending_jobs filters by AgentExecution.status (not AgentJob)
    - get_workflow_status aggregates across executions correctly
    - get_agent_mission returns mission from AgentJob (joined)
    """

    async def test_list_jobs_returns_both_ids(self, db_session, db_manager, test_project, test_tenant_key):
        """Verify list_jobs returns both job_id and agent_id."""
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        # Spawn an agent
        result = await service.spawn_job(
            agent_display_name="implementer",
            agent_name="impl-1",
            mission="Implement feature X",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )

        # Handover 0731c: list_jobs returns JobListResult typed model
        jobs_result = await service.list_jobs(tenant_key=test_tenant_key)
        jobs = jobs_result.jobs

        assert len(jobs) >= 1
        job_entry = next((j for j in jobs if j["job_id"] == result.job_id), None)
        assert job_entry is not None
        assert "job_id" in job_entry
        assert "agent_id" in job_entry
        assert job_entry["job_id"] == result.job_id
        assert job_entry["agent_id"] == result.agent_id

    async def test_get_pending_jobs_filters_by_execution_status(
        self, db_session, db_manager, test_project, test_tenant_key
    ):
        """Verify get_pending_jobs filters by AgentExecution.status."""
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        # Spawn waiting agent
        waiting_result = await service.spawn_job(
            agent_display_name="implementer",
            agent_name="impl-waiting",
            mission="Waiting task",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )

        # Spawn working agent
        working_result = await service.spawn_job(
            agent_display_name="tester",
            agent_name="test-working",
            mission="Working task",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )

        # Update working agent to "working" status
        working_exec_stmt = select(AgentExecution).where(AgentExecution.agent_id == working_result.agent_id)
        working_exec_result = await db_session.execute(working_exec_stmt)
        working_exec = working_exec_result.scalar_one()
        working_exec.status = "working"
        await db_session.commit()

        # Handover 0731c: get_pending_jobs returns PendingJobsResult typed model
        pending_result = await service.get_pending_jobs(agent_display_name="implementer", tenant_key=test_tenant_key)
        pending_jobs = pending_result.jobs

        # Verify only waiting job of type implementer is returned
        pending_job_ids = [j["job_id"] for j in pending_jobs]
        assert waiting_result.job_id in pending_job_ids
        assert working_result.job_id not in pending_job_ids

    async def test_get_agent_mission_returns_mission_from_job(
        self, db_session, db_manager, test_project, test_tenant_key
    ):
        """Verify get_agent_mission returns mission from AgentJob (joined)."""
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        mission = "Build comprehensive test suite"
        result = await service.spawn_job(
            agent_display_name="tester",
            agent_name="tester-1",
            mission=mission,
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )

        # Handover 0731c: get_agent_mission returns MissionResponse typed model
        fetched_mission = await service.get_agent_mission(job_id=result.job_id, tenant_key=test_tenant_key)

        # No success wrapper after 0730b refactor
        # Mission includes team context header prefix, so check it ends with the original mission
        assert mission in fetched_mission.mission

    async def test_get_workflow_status_aggregates_across_executions(
        self, db_session, db_manager, test_project, test_tenant_key
    ):
        """Verify get_workflow_status aggregates across all executions correctly."""
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        # Spawn multiple agents
        await service.spawn_job(
            agent_display_name="implementer",
            agent_name="impl-1",
            mission="Task 1",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )
        await service.spawn_job(
            agent_display_name="tester",
            agent_name="test-1",
            mission="Task 2",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )

        # Get workflow status
        status = await service.get_workflow_status(project_id=test_project.id, tenant_key=test_tenant_key)

        # Handover 0731c: get_workflow_status returns WorkflowStatus typed model
        from giljo_mcp.schemas.service_responses import WorkflowStatus

        assert isinstance(status, WorkflowStatus)
        assert status.total_agents >= 2


# ============================================================================
# Test Class: Update Methods Target AgentExecution
# ============================================================================


@pytest.mark.asyncio
class TestUpdateMethodsDualModel:
    """
    Tests that update methods target AgentExecution (not AgentJob).

    Expected Behavior:
    - complete_job updates AgentExecution.status, not AgentJob.status
    - report_progress updates AgentExecution fields

    HANDOVER 0422: Removed test_update_context_usage_updates_execution because update_context_usage()
    was removed from OrchestrationService (dead token budget cleanup).
    """

    async def test_complete_job_updates_execution_status(self, db_session, db_manager, test_project, test_tenant_key):
        """Verify complete_job updates AgentExecution.status, not AgentJob.status."""
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        result = await service.spawn_job(
            agent_display_name="implementer",
            agent_name="impl-1",
            mission="Implement feature",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )
        agent_id = result.agent_id
        job_id = result.job_id

        # Complete job (requires job_id and result dict)
        complete_result = await service.complete_job(
            job_id=job_id, result={"output": "Task done"}, tenant_key=test_tenant_key
        )

        # Handover 0731c: Returns CompleteJobResult typed model
        assert complete_result.status == "success"

        # Verify AgentExecution.status is "complete"
        exec_stmt = select(AgentExecution).where(AgentExecution.agent_id == agent_id)
        exec_result = await db_session.execute(exec_stmt)
        execution = exec_result.scalar_one()
        assert execution.status == "complete"

        # Verify AgentJob.status is now "completed" (job completes when last execution completes)
        job_stmt = select(AgentJob).where(AgentJob.job_id == job_id)
        job_result = await db_session.execute(job_stmt)
        job = job_result.scalar_one()
        assert job.status == "completed"  # Job completes with last execution

    async def test_report_progress_updates_execution_fields(
        self, db_session, db_manager, test_project, test_tenant_key
    ):
        """Verify report_progress updates AgentExecution fields."""
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        result = await service.spawn_job(
            agent_display_name="implementer",
            agent_name="impl-1",
            mission="Implement feature",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )
        agent_id = result.agent_id
        job_id = result.job_id

        # Report progress (requires job_id and progress dict)
        # Note: In test environment, message queue may fail but progress fields still get updated
        await service.report_progress(
            job_id=job_id,
            progress={"percent": 50, "message": "Implementing database schema"},
            tenant_key=test_tenant_key,
        )

        # Progress fields are updated in execution even if message queue fails
        # Verify AgentExecution fields updated by refreshing session
        await db_session.commit()  # Ensure changes are visible
        exec_stmt = select(AgentExecution).where(AgentExecution.agent_id == agent_id)
        exec_result = await db_session.execute(exec_stmt)
        execution = exec_result.scalar_one()
        assert execution.progress == 50
        assert execution.current_task == "Implementing database schema"
        assert execution.last_progress_at is not None
