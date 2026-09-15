# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
import uuid
from datetime import UTC

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models import AgentExecution, AgentTemplate, Message, Product, Project
from giljo_mcp.models.tasks import MessageRecipient
from giljo_mcp.services.orchestration_service import OrchestrationService
from giljo_mcp.tenant import TenantManager
from tests.helpers.product_crew_helper import adopt_all_templates




@pytest_asyncio.fixture
async def tenant_key() -> str:
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def agent_templates(db_session, tenant_key):
    template_names = ["specialist-1", "orchestrator"]
    for name in template_names:
        template = AgentTemplate(
            tenant_key=tenant_key,
            name=name,
            role=name,
            description=f"Test template for {name}",
            system_instructions=f"# {name}\nTest agent.",
            is_active=True,
        )
        db_session.add(template)
    await db_session.commit()


@pytest_asyncio.fixture
async def project(db_session, tenant_key, agent_templates) -> Project:
    from datetime import datetime

    _owning_product_proj = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_proj)
    proj = Project(
        id=str(uuid.uuid4()),
        name="Result Storage Test Project",
        description="Integration test project for 0497b",
        mission="Test completion result storage and auto-messaging",
        status="active",
        tenant_key=tenant_key,
        product_id=_owning_product_proj.id,
        execution_mode="multi_terminal",
        implementation_launched_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(proj)
    await db_session.commit()
    await db_session.refresh(proj)
    await adopt_all_templates(db_session, tenant_key, _owning_product_proj.id)
    return proj


@pytest_asyncio.fixture
async def service(db_session, db_manager) -> OrchestrationService:
    tm = TenantManager()
    return OrchestrationService(
        db_manager=db_manager,
        tenant_manager=tm,
        test_session=db_session,
    )




@pytest.mark.asyncio
class TestCompleteJobStoresResult:

    async def test_result_dict_stored_on_execution(self, db_session, service, project, tenant_key):
        spawn = await service.spawn_job(
            agent_display_name="specialist",
            agent_name="specialist-1",
            mission="Do specialized work",
            project_id=project.id,
            tenant_key=tenant_key,
        )

        result_payload = {
            "summary": "Implemented the feature successfully",
            "artifacts": ["src/feature.py", "tests/test_feature.py"],
            "commits": ["abc123"],
        }

        complete_result = await service.complete_job(
            job_id=spawn.job_id,
            result=result_payload,
            tenant_key=tenant_key,
        )

        assert complete_result.status == "success"
        assert complete_result.result_stored is True

        stmt = select(AgentExecution).where(AgentExecution.agent_id == spawn.agent_id)
        res = await db_session.execute(stmt)
        execution = res.scalar_one()

        assert execution.status == "complete"
        assert execution.result is not None
        assert execution.result == result_payload
        assert execution.result["summary"] == "Implemented the feature successfully"
        assert "src/feature.py" in execution.result["artifacts"]




@pytest.mark.asyncio
class TestCompleteJobAutoMessage:

    async def test_completion_report_message_created(self, db_session, service, project, tenant_key):
        orch_spawn = await service.spawn_job(
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            mission="Orchestrate the project",
            project_id=project.id,
            tenant_key=tenant_key,
        )

        spec_spawn = await service.spawn_job(
            agent_display_name="specialist",
            agent_name="specialist-1",
            mission="Do specialized work",
            project_id=project.id,
            tenant_key=tenant_key,
        )

        result_payload = {
            "summary": "Refactored the auth module",
            "artifacts": ["src/auth.py"],
        }

        await service.complete_job(
            job_id=spec_spawn.job_id,
            result=result_payload,
            tenant_key=tenant_key,
        )

        msg_stmt = select(Message).where(
            Message.tenant_key == tenant_key,
            Message.project_id == project.id,
            Message.message_type == "completion_report",
        )
        msg_res = await db_session.execute(msg_stmt)
        messages = msg_res.scalars().all()

        assert len(messages) == 1, f"Expected 1 completion_report message, got {len(messages)}"

        msg = messages[0]
        recip_result = await db_session.execute(select(MessageRecipient).where(MessageRecipient.message_id == msg.id))
        recipients = recip_result.scalars().all()
        assert any(r.agent_id == orch_spawn.agent_id for r in recipients), (
            f"Expected orchestrator {orch_spawn.agent_id} in recipients"
        )
        assert "COMPLETION REPORT" in msg.content
        assert "specialist" in msg.content
        assert "Refactored the auth module" in msg.content
        assert msg.status == "pending"

        assert msg.from_agent_id == str(spec_spawn.agent_id)




@pytest.mark.asyncio
class TestOrchestratorCompletionNoMessage:

    async def test_no_completion_report_for_orchestrator(self, db_session, service, project, tenant_key):
        orch_spawn = await service.spawn_job(
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            mission="Orchestrate everything",
            project_id=project.id,
            tenant_key=tenant_key,
        )

        result_payload = {
            "summary": "Project orchestration complete",
        }

        await service.complete_job(
            job_id=orch_spawn.job_id,
            result=result_payload,
            tenant_key=tenant_key,
        )

        msg_stmt = select(Message).where(
            Message.tenant_key == tenant_key,
            Message.project_id == project.id,
            Message.message_type == "completion_report",
        )
        msg_res = await db_session.execute(msg_stmt)
        messages = msg_res.scalars().all()

        assert len(messages) == 0, (
            f"Expected 0 completion_report messages for orchestrator self-completion, got {len(messages)}"
        )




@pytest.mark.asyncio
class TestGetAgentResult:

    async def test_returns_stored_result_dict(self, db_session, service, project, tenant_key):
        spawn = await service.spawn_job(
            agent_display_name="specialist",
            agent_name="specialist-1",
            mission="Do work",
            project_id=project.id,
            tenant_key=tenant_key,
        )

        result_payload = {
            "summary": "All tests passing",
            "artifacts": ["tests/test_auth.py"],
            "test_results": {"passed": 42, "failed": 0},
        }

        await service.complete_job(
            job_id=spawn.job_id,
            result=result_payload,
            tenant_key=tenant_key,
        )

        stored_result = await service.get_agent_result(
            job_id=spawn.job_id,
            tenant_key=tenant_key,
        )

        assert stored_result is not None
        assert stored_result == result_payload
        assert stored_result["summary"] == "All tests passing"
        assert stored_result["test_results"]["passed"] == 42




@pytest.mark.asyncio
class TestGetAgentResultIncomplete:

    async def test_returns_none_for_working_agent(self, db_session, service, project, tenant_key):
        spawn = await service.spawn_job(
            agent_display_name="specialist",
            agent_name="specialist-1",
            mission="Still working on it",
            project_id=project.id,
            tenant_key=tenant_key,
        )

        stored_result = await service.get_agent_result(
            job_id=spawn.job_id,
            tenant_key=tenant_key,
        )

        assert stored_result is None
