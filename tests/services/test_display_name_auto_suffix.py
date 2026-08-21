# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
TDD Tests for v1.1.6: Auto-Suffix Agent Display Names on Collision.

RED PHASE - These tests verify:
1. Basic dedup: spawn two agents with same display_name, second gets -2
2. Triple spawn: three with same name -> names are base, -2, -3
3. Reuse freed name: spawn base + -2, complete -2, spawn again -> gets -2
4. No false suffix: spawn when no collision -> name unchanged (no -1)
5. Pre-suffixed name: spawn implementer-2 when implementer active but implementer-2 free
6. Orchestrator unchanged: second orchestrator still raises AlreadyExistsError
7. Spawn result contains resolved name (agent_display_name field)
8. Suffix cap: verify error when suffix exceeds 50
"""

import random
import uuid
from datetime import UTC

import pytest
import pytest_asyncio

from giljo_mcp.exceptions import AlreadyExistsError, ValidationError
from giljo_mcp.models import AgentExecution, AgentJob, AgentTemplate, Product, Project
from giljo_mcp.services.orchestration_service import OrchestrationService
from giljo_mcp.tenant import TenantManager


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest_asyncio.fixture
async def suffix_tenant_key() -> str:
    """Generate unique tenant key for test isolation."""
    return f"tk_test_{uuid.uuid4().hex[:16]}"


@pytest_asyncio.fixture
async def suffix_templates(db_session, suffix_tenant_key):
    """Create agent templates needed for display name suffix tests."""
    for name in ["implementer", "analyzer", "orchestrator"]:
        template = AgentTemplate(
            tenant_key=suffix_tenant_key,
            name=name,
            role=name,
            description=f"Test template for {name}",
            system_instructions=f"# {name}\nTest agent.",
            is_active=True,
        )
        db_session.add(template)
    await db_session.commit()


@pytest_asyncio.fixture
async def suffix_project(db_session, suffix_tenant_key, suffix_templates) -> Project:
    """Create test project for display name suffix tests."""
    from datetime import datetime

    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=suffix_tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        id=str(uuid.uuid4()),
        name="Display Name Suffix Test Project",
        description="Test project for auto-suffix display names",
        mission="Test auto-suffix logic",
        status="active",
        tenant_key=suffix_tenant_key,
        product_id=_owning_product_project.id,
        execution_mode="multi_terminal",
        implementation_launched_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest_asyncio.fixture
async def suffix_service(db_session, db_manager) -> OrchestrationService:
    """Create OrchestrationService with shared test session."""
    tm = TenantManager()
    return OrchestrationService(
        db_manager=db_manager,
        tenant_manager=tm,
        test_session=db_session,
    )


# ============================================================================
# Test Class: Auto-Suffix Display Name Resolution
# ============================================================================


@pytest.mark.asyncio
class TestDisplayNameAutoSuffix:
    """Tests that spawn_job auto-suffixes duplicate display names."""

    async def test_no_collision_no_suffix(self, suffix_service, suffix_project, suffix_tenant_key):
        """No false suffix: spawn when no collision -> name unchanged (no -1)."""
        result = await suffix_service.spawn_job(
            agent_display_name="implementer",
            agent_name="implementer",
            mission="Implement feature",
            project_id=suffix_project.id,
            tenant_key=suffix_tenant_key,
        )

        assert result.agent_display_name == "implementer"

    async def test_basic_dedup_second_gets_suffix_2(self, suffix_service, suffix_project, suffix_tenant_key):
        """Basic dedup: spawn two agents with same display_name, second gets -2."""
        result1 = await suffix_service.spawn_job(
            agent_display_name="implementer",
            agent_name="implementer",
            mission="Implement feature 1",
            project_id=suffix_project.id,
            tenant_key=suffix_tenant_key,
        )
        result2 = await suffix_service.spawn_job(
            agent_display_name="implementer",
            agent_name="implementer",
            mission="Implement feature 2",
            project_id=suffix_project.id,
            tenant_key=suffix_tenant_key,
        )

        assert result1.agent_display_name == "implementer"
        assert result2.agent_display_name == "implementer-2"

    async def test_triple_spawn_sequential_suffixes(self, suffix_service, suffix_project, suffix_tenant_key):
        """Triple spawn: three with same name -> names are base, -2, -3."""
        r1 = await suffix_service.spawn_job(
            agent_display_name="implementer",
            agent_name="implementer",
            mission="Task 1",
            project_id=suffix_project.id,
            tenant_key=suffix_tenant_key,
        )
        r2 = await suffix_service.spawn_job(
            agent_display_name="implementer",
            agent_name="implementer",
            mission="Task 2",
            project_id=suffix_project.id,
            tenant_key=suffix_tenant_key,
        )
        r3 = await suffix_service.spawn_job(
            agent_display_name="implementer",
            agent_name="implementer",
            mission="Task 3",
            project_id=suffix_project.id,
            tenant_key=suffix_tenant_key,
        )

        assert r1.agent_display_name == "implementer"
        assert r2.agent_display_name == "implementer-2"
        assert r3.agent_display_name == "implementer-3"

    async def test_reuse_freed_name(self, suffix_service, suffix_project, suffix_tenant_key, db_session):
        """Reuse freed name: spawn base + -2, complete -2, spawn again -> gets -2."""
        await suffix_service.spawn_job(
            agent_display_name="implementer",
            agent_name="implementer",
            mission="Task 1",
            project_id=suffix_project.id,
            tenant_key=suffix_tenant_key,
        )
        r2 = await suffix_service.spawn_job(
            agent_display_name="implementer",
            agent_name="implementer",
            mission="Task 2",
            project_id=suffix_project.id,
            tenant_key=suffix_tenant_key,
        )

        assert r2.agent_display_name == "implementer-2"

        # Complete the -2 agent (move out of active status)
        await suffix_service.complete_job(
            job_id=r2.job_id,
            result={"summary": "Done"},
            tenant_key=suffix_tenant_key,
        )

        # Spawn again -- should reuse implementer-2 since it's freed
        r3 = await suffix_service.spawn_job(
            agent_display_name="implementer",
            agent_name="implementer",
            mission="Task 3",
            project_id=suffix_project.id,
            tenant_key=suffix_tenant_key,
        )

        assert r3.agent_display_name == "implementer-2"

    async def test_pre_suffixed_name_used_as_is(self, suffix_service, suffix_project, suffix_tenant_key):
        """Pre-suffixed input: spawn implementer-2 when implementer active but implementer-2 free."""
        # Spawn base name first
        await suffix_service.spawn_job(
            agent_display_name="implementer",
            agent_name="implementer",
            mission="Task 1",
            project_id=suffix_project.id,
            tenant_key=suffix_tenant_key,
        )

        # Spawn with explicit pre-suffixed name
        r2 = await suffix_service.spawn_job(
            agent_display_name="implementer-2",
            agent_name="implementer",
            mission="Task 2",
            project_id=suffix_project.id,
            tenant_key=suffix_tenant_key,
        )

        # Should use the name as-is, not double-suffix to implementer-2-2
        assert r2.agent_display_name == "implementer-2"

    async def test_orchestrator_still_raises_on_duplicate(self, suffix_service, suffix_project, suffix_tenant_key):
        """Orchestrator singleton: second orchestrator spawn still raises AlreadyExistsError."""
        await suffix_service.spawn_job(
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            mission="Orchestrate project",
            project_id=suffix_project.id,
            tenant_key=suffix_tenant_key,
        )

        with pytest.raises(AlreadyExistsError):
            await suffix_service.spawn_job(
                agent_display_name="orchestrator",
                agent_name="orchestrator",
                mission="Second orchestrator",
                project_id=suffix_project.id,
                tenant_key=suffix_tenant_key,
            )

    async def test_spawn_result_contains_resolved_name(self, suffix_service, suffix_project, suffix_tenant_key):
        """Spawn result contains resolved display name via agent_display_name field."""
        await suffix_service.spawn_job(
            agent_display_name="implementer",
            agent_name="implementer",
            mission="Task 1",
            project_id=suffix_project.id,
            tenant_key=suffix_tenant_key,
        )

        result = await suffix_service.spawn_job(
            agent_display_name="implementer",
            agent_name="implementer",
            mission="Task 2",
            project_id=suffix_project.id,
            tenant_key=suffix_tenant_key,
        )

        # SpawnResult must expose the resolved name
        assert hasattr(result, "agent_display_name")
        assert result.agent_display_name == "implementer-2"

    async def test_suffix_cap_raises_at_50(self, suffix_service, suffix_project, suffix_tenant_key, db_session):
        """Suffix cap: error when suffix exceeds 50."""
        # Create 50 active agents with names: implementer, implementer-2, ..., implementer-50
        # We do this directly in the DB to avoid spawning 50 agents through the service
        from datetime import datetime

        base_name = "implementer"
        for i in range(50):
            name = base_name if i == 0 else f"{base_name}-{i + 1}"
            job_id = str(uuid.uuid4())
            job = AgentJob(
                job_id=job_id,
                tenant_key=suffix_tenant_key,
                project_id=suffix_project.id,
                job_type=name,
                mission=f"Mission {i}",
                status="active",
                created_at=datetime.now(UTC),
            )
            db_session.add(job)
            execution = AgentExecution(
                agent_id=str(uuid.uuid4()),
                job_id=job_id,
                tenant_key=suffix_tenant_key,
                agent_display_name=name,
                agent_name="implementer",
                status="working",
                started_at=datetime.now(UTC),
            )
            db_session.add(execution)

        await db_session.commit()

        # Now the 51st spawn should fail with ValidationError (cap at 50)
        with pytest.raises(ValidationError, match="suffix cap"):
            await suffix_service.spawn_job(
                agent_display_name="implementer",
                agent_name="implementer",
                mission="Task 51",
                project_id=suffix_project.id,
                tenant_key=suffix_tenant_key,
            )
