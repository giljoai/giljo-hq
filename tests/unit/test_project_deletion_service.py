# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy import event, select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import (
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.tasks import Message, Task
from giljo_mcp.models.user_approval import UserApproval
from giljo_mcp.services.project_deletion_service import ProjectDeletionService



TENANT_KEY = "test-tenant"
PROJECT_ID = "proj-001"


def _make_session():
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = Mock()
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    session.info = {}
    return session


def _make_project(
    project_id=PROJECT_ID,
    status="active",
    tenant_key=TENANT_KEY,
    product_id="prod-1",
    deleted_at=None,
):
    project = MagicMock()
    project.id = project_id
    project.name = "Test Project"
    project.status = status
    project.tenant_key = tenant_key
    project.product_id = product_id
    project.deleted_at = deleted_at
    project.updated_at = None
    return project


def _make_service(session, tenant_key=TENANT_KEY):
    db_manager = Mock()
    db_manager.get_session_async = Mock(return_value=session)
    tenant_manager = Mock()
    tenant_manager.get_current_tenant = Mock(return_value=tenant_key)
    return ProjectDeletionService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=session,
    )




class TestDeleteProject:

    @pytest.mark.asyncio
    async def test_delete_no_tenant_raises(self):
        session = _make_session()
        service = _make_service(session)
        service.tenant_manager.get_current_tenant.return_value = None

        with pytest.raises(ValidationError, match="No tenant context"):
            await service.delete_project(PROJECT_ID)

    @pytest.mark.asyncio
    async def test_delete_not_found_raises(self):
        session = _make_session()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ResourceNotFoundError, match="not found or already deleted"):
            await service.delete_project(PROJECT_ID)

    @pytest.mark.asyncio
    async def test_delete_sets_status_and_timestamp(self):
        project = _make_project(status="active")
        session = _make_session()

        call_count = 0
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_exec_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_exec_result.scalars.return_value = mock_scalars

        async def side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_project_result
            return mock_exec_result

        session.execute = AsyncMock(side_effect=side_effect)

        service = _make_service(session)
        result = await service.delete_project(PROJECT_ID)

        assert project.status == "deleted"
        assert project.deleted_at is not None
        assert result.message == "Project deleted successfully"
        assert result.decommissioned_jobs == 0
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_decommissions_active_executions(self):
        project = _make_project(status="active")
        exec1 = MagicMock()
        exec1.status = "working"
        exec2 = MagicMock()
        exec2.status = "waiting"

        session = _make_session()

        call_count = 0
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_exec_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [exec1, exec2]
        mock_exec_result.scalars.return_value = mock_scalars

        async def side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_project_result
            return mock_exec_result

        session.execute = AsyncMock(side_effect=side_effect)

        service = _make_service(session)
        result = await service.delete_project(PROJECT_ID)

        assert exec1.status == "decommissioned"
        assert exec2.status == "decommissioned"
        assert result.decommissioned_jobs == 2




class TestNuclearDeleteProject:

    @pytest.mark.asyncio
    async def test_nuclear_no_tenant_raises(self):
        session = _make_session()
        service = _make_service(session)
        service.tenant_manager.get_current_tenant.return_value = None

        with pytest.raises(ValidationError, match="No tenant context"):
            await service.nuclear_delete_project(PROJECT_ID)

    @pytest.mark.asyncio
    async def test_nuclear_not_found_raises(self):
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ResourceNotFoundError, match="not found or access denied"):
            await service.nuclear_delete_project(PROJECT_ID)

    @pytest.mark.asyncio
    async def test_nuclear_deactivates_active_project(self):
        project = _make_project(status="active", product_id=None)
        session = _make_session()

        call_count = 0
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_empty = MagicMock()
        mock_empty_scalars = MagicMock()
        mock_empty_scalars.all.return_value = []
        mock_empty.scalars.return_value = mock_empty_scalars
        mock_empty.rowcount = 0

        async def side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_project_result
            return mock_empty

        session.execute = AsyncMock(side_effect=side_effect)

        service = _make_service(session)
        result = await service.nuclear_delete_project(PROJECT_ID)

        assert project.status == "inactive"
        session.flush.assert_called()
        assert result.project_name == "Test Project"




class TestRestoreProject:

    @pytest.mark.asyncio
    async def test_restore_not_found_raises(self):
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ResourceNotFoundError, match="not found or access denied"):
            await service.restore_project(PROJECT_ID, TENANT_KEY)

    @pytest.mark.asyncio
    async def test_restore_cancelled_keeps_number(self):
        session = _make_session()
        project = _make_project(status="cancelled", deleted_at=None)
        project.series_number = 42
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        result = await service.restore_project(PROJECT_ID, TENANT_KEY)

        assert "restored successfully" in result.message
        assert project.series_number == 42
        assert project.deleted_at is None
        session.commit.assert_called_once()




class TestPurgeAllDeletedProjects:

    @pytest.mark.asyncio
    async def test_purge_no_tenant_raises(self):
        session = _make_session()
        service = _make_service(session)
        service.tenant_manager.get_current_tenant.return_value = None

        with pytest.raises(ValidationError, match="No tenant context"):
            await service.purge_all_deleted_projects()

    @pytest.mark.asyncio
    async def test_purge_empty_returns_zero(self):
        session = _make_session()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        result = await service.purge_all_deleted_projects()

        assert result.purged_count == 0
        assert result.projects == []




async def _seed_project_with_approval(session, tenant_key):
    product = Product(
        id=str(uuid4()),
        name=f"P {uuid4().hex[:6]}",
        description="x",
        tenant_key=tenant_key,
        is_active=True,
    )
    session.add(product)
    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name="P",
        description="x",
        mission="x",
        status="active",
        series_number=random.randint(1, 9000),
    )
    session.add(project)
    await session.flush()
    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="implementer",
        mission="x",
        status="active",
        created_at=datetime.now(UTC),
    )
    session.add(job)
    await session.flush()
    execution = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="implementer",
        status="working",
    )
    session.add(execution)
    await session.flush()
    approval = UserApproval(
        tenant_key=tenant_key,
        agent_execution_id=execution.id,
        job_id=job.job_id,
        project_id=project.id,
        reason="r",
        options=[{"id": "a", "label": "A"}],
        context=None,
        status="pending",
    )
    session.add(approval)
    await session.commit()
    return project, job, execution, approval


def _real_db_service(db_manager, db_session, tenant_manager, tenant_key):
    tenant_manager.set_current_tenant(tenant_key)
    return ProjectDeletionService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )


class TestPurgeClearsUserApprovals:

    @pytest.mark.asyncio
    async def test_nuclear_delete_clears_user_approvals(self, db_manager, db_session, tenant_manager, test_tenant_key):
        project, _job, execution, approval = await _seed_project_with_approval(db_session, test_tenant_key)
        service = _real_db_service(db_manager, db_session, tenant_manager, test_tenant_key)

        result = await service.nuclear_delete_project(project.id)

        assert result.project_name == "P"
        assert result.deleted_counts["user_approvals"] == 1

        with tenant_session_context(db_session, test_tenant_key):
            approvals_left = (
                (await db_session.execute(select(UserApproval).where(UserApproval.id == approval.id))).scalars().all()
            )
            execs_left = (
                (await db_session.execute(select(AgentExecution).where(AgentExecution.id == execution.id)))
                .scalars()
                .all()
            )
            projects_left = (await db_session.execute(select(Project).where(Project.id == project.id))).scalars().all()
        assert approvals_left == []
        assert execs_left == []
        assert projects_left == []

    @pytest.mark.asyncio
    async def test_purge_project_records_clears_user_approvals(
        self, db_manager, db_session, tenant_manager, test_tenant_key
    ):
        project, _job, execution, approval = await _seed_project_with_approval(db_session, test_tenant_key)
        service = _real_db_service(db_manager, db_session, tenant_manager, test_tenant_key)

        async with service._get_session(test_tenant_key) as session:
            info = await service._purge_project_records(session, project)
            await session.commit()

        assert info["id"] == project.id

        with tenant_session_context(db_session, test_tenant_key):
            approvals_left = (
                (await db_session.execute(select(UserApproval).where(UserApproval.id == approval.id))).scalars().all()
            )
            execs_left = (
                (await db_session.execute(select(AgentExecution).where(AgentExecution.id == execution.id)))
                .scalars()
                .all()
            )
        assert approvals_left == []
        assert execs_left == []




class _DeleteStatementCounter:
    def __init__(self, engine):
        self._engine = engine
        self.statements: list[str] = []

    def __enter__(self):
        event.listen(self._engine, "before_cursor_execute", self._on)
        return self

    def __exit__(self, *exc):
        event.remove(self._engine, "before_cursor_execute", self._on)

    def _on(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(statement)

    def count(self, needle: str) -> int:
        upper = needle.upper()
        return sum(1 for s in self.statements if upper in s.upper())

    def count_standalone_select_from(self, table: str) -> int:
        upper = table.upper()
        return sum(
            1 for s in self.statements if s.strip().upper().startswith("SELECT") and f"FROM {upper}" in s.upper()
        )


async def _seed_project_with_many_children(session, tenant_key, n=3):
    product = Product(
        id=str(uuid4()), name=f"P {uuid4().hex[:6]}", description="x", tenant_key=tenant_key, is_active=True
    )
    session.add(product)
    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name="P",
        description="x",
        mission="x",
        status="inactive",
        series_number=random.randint(1, 9000),
    )
    session.add(project)
    await session.flush()

    for _ in range(n):
        job = AgentJob(
            job_id=str(uuid4()),
            tenant_key=tenant_key,
            project_id=project.id,
            job_type="implementer",
            mission="x",
            status="active",
            created_at=datetime.now(UTC),
        )
        session.add(job)
        await session.flush()
        execution = AgentExecution(
            id=str(uuid4()),
            agent_id=str(uuid4()),
            job_id=job.job_id,
            tenant_key=tenant_key,
            agent_display_name="impl",
            status="working",
        )
        session.add(execution)
        await session.flush()
        session.add(
            UserApproval(
                tenant_key=tenant_key,
                agent_execution_id=execution.id,
                job_id=job.job_id,
                project_id=project.id,
                reason="r",
                options=[{"id": "a", "label": "A"}],
                context=None,
                status="pending",
            )
        )
        session.add(
            Task(
                tenant_key=tenant_key,
                product_id=product.id,
                project_id=project.id,
                title=f"t{uuid4().hex[:6]}",
                status="pending",
                hidden=False,
            )
        )
        session.add(Message(tenant_key=tenant_key, project_id=project.id, content="hi"))
    await session.commit()
    return project


class TestNuclearDeleteBatching:

    @pytest.mark.asyncio
    async def test_nuclear_delete_batches_and_counts_are_equivalent(
        self, db_manager, db_session, tenant_manager, test_tenant_key
    ):
        project = await _seed_project_with_many_children(db_session, test_tenant_key, n=3)
        service = _real_db_service(db_manager, db_session, tenant_manager, test_tenant_key)

        engine = db_manager.async_engine.sync_engine
        with _DeleteStatementCounter(engine) as counter:
            result = await service.nuclear_delete_project(project.id)

        assert result.deleted_counts["user_approvals"] == 3
        assert result.deleted_counts["agent_jobs"] == 3
        assert result.deleted_counts["tasks"] == 3
        assert result.deleted_counts["messages"] == 3

        assert counter.count("DELETE FROM user_approvals") == 1, counter.statements
        assert counter.count("DELETE FROM agent_executions") == 1, counter.statements
        assert counter.count("DELETE FROM agent_jobs") == 1, counter.statements
        assert counter.count("DELETE FROM messages") == 1, counter.statements
        assert counter.count_standalone_select_from("user_approvals") == 0, counter.statements
        assert counter.count_standalone_select_from("agent_executions") == 0, counter.statements

        with tenant_session_context(db_session, test_tenant_key):
            for model in (UserApproval, AgentJob, AgentExecution, Task, Message):
                left = (
                    (await db_session.execute(select(model).where(model.tenant_key == test_tenant_key))).scalars().all()
                )
                assert left == [], f"{model.__name__} rows not fully deleted: {left}"
