# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from giljo_mcp.models import AgentJob
from tests.helpers.model_factories import make_project




@pytest.mark.asyncio
class TestSpawnAgentJobPhaseParameter:

    async def test_spawn_stores_phase_on_agent_job(self, db_session, db_manager, test_project, test_tenant_key):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        result = await service.spawn_job(
            agent_display_name="analyzer",
            agent_name="analyzer-1",
            mission="Analyze the codebase",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
            phase=1,
        )

        job_stmt = select(AgentJob).where(AgentJob.job_id == result.job_id)
        job_result = await db_session.execute(job_stmt)
        job = job_result.scalar_one()
        assert job.phase == 1

    async def test_spawn_stores_none_phase_when_omitted(self, db_session, db_manager, test_project, test_tenant_key):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        result = await service.spawn_job(
            agent_display_name="analyzer",
            agent_name="analyzer-1",
            mission="Analyze the codebase",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )

        job_stmt = select(AgentJob).where(AgentJob.job_id == result.job_id)
        job_result = await db_session.execute(job_stmt)
        job = job_result.scalar_one()
        assert job.phase is None

    async def test_spawn_stores_higher_phase_numbers(self, db_session, db_manager, test_project, test_tenant_key):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        predecessor = await service.spawn_job(
            agent_display_name="analyzer",
            agent_name="analyzer-1",
            mission="Predecessor analysis",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
            phase=1,
        )

        result = await service.spawn_job(
            agent_display_name="tester",
            agent_name="tester-1",
            mission="Write integration tests",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
            phase=3,
            predecessor_job_id=predecessor.job_id,
        )

        job_stmt = select(AgentJob).where(AgentJob.job_id == result.job_id)
        job_result = await db_session.execute(job_stmt)
        job = job_result.scalar_one()
        assert job.phase == 3




@pytest.mark.asyncio
class TestSpawnWebSocketBroadcastPhase:

    async def test_websocket_broadcast_includes_phase(self):
        from giljo_mcp.services.orchestration_service import OrchestrationService

        db_manager = MagicMock()
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        session.add = MagicMock()
        session.info = {}
        db_manager.get_session_async = MagicMock(return_value=session)

        mock_ws = AsyncMock()
        tenant_manager = MagicMock()

        service = OrchestrationService(
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            websocket_manager=mock_ws,
        )

        project = make_project(
            id=str(uuid.uuid4()),
            name="Test Project",
            execution_mode="multi_terminal",
        )

        mock_template_row = MagicMock()
        mock_template_row.__getitem__ = lambda self, idx: "analyzer-1"

        project_result = MagicMock()
        project_result.scalar_one_or_none = MagicMock(return_value=project)

        template_validation_result = MagicMock()
        template_validation_result.fetchall = MagicMock(return_value=[mock_template_row])

        duplicate_check_result = MagicMock()
        duplicate_check_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))

        mock_template = MagicMock()
        mock_template.id = str(uuid.uuid4())
        mock_template.system_instructions = "Test instructions"
        mock_template.user_instructions = None
        template_lookup_result = MagicMock()
        template_lookup_result.scalar_one_or_none = MagicMock(return_value=mock_template)

        assignment_probe_result = MagicMock()
        assignment_probe_result.first = MagicMock(return_value=None)

        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return project_result
            if call_count == 2:
                return assignment_probe_result
            if call_count == 3:
                return template_validation_result
            if call_count == 4:
                return duplicate_check_result
            return template_lookup_result

        session.execute = AsyncMock(side_effect=mock_execute)

        await service.spawn_job(
            agent_display_name="analyzer",
            agent_name="analyzer-1",
            mission="Analyze codebase",
            project_id=project.id,
            tenant_key="tk_test",
            phase=1,
        )

        mock_ws.broadcast_to_tenant.assert_called_once()
        call_kwargs = mock_ws.broadcast_to_tenant.call_args
        broadcast_data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
        assert "phase" in broadcast_data
        assert broadcast_data["phase"] == 1

    async def test_websocket_broadcast_includes_none_phase_when_omitted(self):
        from giljo_mcp.services.orchestration_service import OrchestrationService

        db_manager = MagicMock()
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        session.add = MagicMock()
        session.info = {}
        db_manager.get_session_async = MagicMock(return_value=session)

        mock_ws = AsyncMock()
        tenant_manager = MagicMock()

        service = OrchestrationService(
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            websocket_manager=mock_ws,
        )

        project = make_project(
            id=str(uuid.uuid4()),
            name="Test Project",
            execution_mode="multi_terminal",
        )

        mock_template_row = MagicMock()
        mock_template_row.__getitem__ = lambda self, idx: "impl-1"

        project_result = MagicMock()
        project_result.scalar_one_or_none = MagicMock(return_value=project)

        template_validation_result = MagicMock()
        template_validation_result.fetchall = MagicMock(return_value=[mock_template_row])

        duplicate_check_result = MagicMock()
        duplicate_check_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))

        mock_template = MagicMock()
        mock_template.id = str(uuid.uuid4())
        mock_template.system_instructions = "Test instructions"
        mock_template.user_instructions = None
        template_lookup_result = MagicMock()
        template_lookup_result.scalar_one_or_none = MagicMock(return_value=mock_template)

        assignment_probe_result = MagicMock()
        assignment_probe_result.first = MagicMock(return_value=None)

        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return project_result
            if call_count == 2:
                return assignment_probe_result
            if call_count == 3:
                return template_validation_result
            if call_count == 4:
                return duplicate_check_result
            return template_lookup_result

        session.execute = AsyncMock(side_effect=mock_execute)

        await service.spawn_job(
            agent_display_name="implementer",
            agent_name="impl-1",
            mission="Implement feature",
            project_id=project.id,
            tenant_key="tk_test",
        )

        mock_ws.broadcast_to_tenant.assert_called_once()
        call_kwargs = mock_ws.broadcast_to_tenant.call_args
        broadcast_data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
        assert "phase" in broadcast_data
        assert broadcast_data["phase"] is None
