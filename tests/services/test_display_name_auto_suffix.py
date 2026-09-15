# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
import uuid
from datetime import UTC

import pytest
import pytest_asyncio

from giljo_mcp.exceptions import AlreadyExistsError, ValidationError
from giljo_mcp.models import AgentExecution, AgentJob, AgentTemplate, Product, Project
from giljo_mcp.services.orchestration_service import OrchestrationService
from giljo_mcp.tenant import TenantManager
from tests.helpers.product_crew_helper import adopt_all_templates




@pytest_asyncio.fixture
async def suffix_tenant_key() -> str:
    return f"tk_test_{uuid.uuid4().hex[:16]}"


@pytest_asyncio.fixture
async def suffix_templates(db_session, suffix_tenant_key):
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
    from datetime import datetime

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
    await adopt_all_templates(db_session, suffix_tenant_key, _owning_product_project.id)
    return project


@pytest_asyncio.fixture
async def suffix_service(db_session, db_manager) -> OrchestrationService:
    tm = TenantManager()
    return OrchestrationService(
        db_manager=db_manager,
        tenant_manager=tm,
        test_session=db_session,
    )




@pytest.mark.asyncio
class TestDisplayNameAutoSuffix:

    async def test_no_collision_no_suffix(self, suffix_service, suffix_project, suffix_tenant_key):
        result = await suffix_service.spawn_job(
            agent_display_name="implementer",
            agent_name="implementer",
            mission="Implement feature",
            project_id=suffix_project.id,
            tenant_key=suffix_tenant_key,
        )

        assert result.agent_display_name == "implementer"

    async def test_basic_dedup_second_gets_suffix_2(self, suffix_service, suffix_project, suffix_tenant_key):
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

        await suffix_service.complete_job(
            job_id=r2.job_id,
            result={"summary": "Done"},
            tenant_key=suffix_tenant_key,
        )

        r3 = await suffix_service.spawn_job(
            agent_display_name="implementer",
            agent_name="implementer",
            mission="Task 3",
            project_id=suffix_project.id,
            tenant_key=suffix_tenant_key,
        )

        assert r3.agent_display_name == "implementer-2"

    async def test_pre_suffixed_name_used_as_is(self, suffix_service, suffix_project, suffix_tenant_key):
        await suffix_service.spawn_job(
            agent_display_name="implementer",
            agent_name="implementer",
            mission="Task 1",
            project_id=suffix_project.id,
            tenant_key=suffix_tenant_key,
        )

        r2 = await suffix_service.spawn_job(
            agent_display_name="implementer-2",
            agent_name="implementer",
            mission="Task 2",
            project_id=suffix_project.id,
            tenant_key=suffix_tenant_key,
        )

        assert r2.agent_display_name == "implementer-2"

    async def test_orchestrator_still_raises_on_duplicate(self, suffix_service, suffix_project, suffix_tenant_key):
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

        assert hasattr(result, "agent_display_name")
        assert result.agent_display_name == "implementer-2"

    async def test_suffix_cap_raises_at_50(self, suffix_service, suffix_project, suffix_tenant_key, db_session):
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

        with pytest.raises(ValidationError, match="suffix cap"):
            await suffix_service.spawn_job(
                agent_display_name="implementer",
                agent_name="implementer",
                mission="Task 51",
                project_id=suffix_project.id,
                tenant_key=suffix_tenant_key,
            )
