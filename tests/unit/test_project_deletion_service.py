# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tests for ProjectDeletionService (Sprint 002f -- P2 core).

Covers:
- delete_project (soft delete happy path, not found, no tenant)
- nuclear_delete_project (happy path, not found, deactivation of active project)
- restore_project (happy path, not found)
- purge_all_deleted_projects (empty, with projects)
- Tenant isolation on every query
"""

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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TENANT_KEY = "test-tenant"
PROJECT_ID = "proj-001"


def _make_session():
    """Create a mock async session configured as a context manager."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = Mock()
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    session.info = {}  # tenant_session_context save/restore target
    return session


def _make_project(
    project_id=PROJECT_ID,
    status="active",
    tenant_key=TENANT_KEY,
    product_id="prod-1",
    deleted_at=None,
):
    """Create a mock Project model."""
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
    """Create a ProjectDeletionService with injected test session."""
    db_manager = Mock()
    db_manager.get_session_async = Mock(return_value=session)
    tenant_manager = Mock()
    tenant_manager.get_current_tenant = Mock(return_value=tenant_key)
    return ProjectDeletionService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=session,
    )


# ---------------------------------------------------------------------------
# delete_project (soft delete) tests
# ---------------------------------------------------------------------------


class TestDeleteProject:
    """Tests for ProjectDeletionService.delete_project (soft delete)."""

    @pytest.mark.asyncio
    async def test_delete_no_tenant_raises(self):
        """Raises ValidationError when tenant is not set."""
        session = _make_session()
        service = _make_service(session)
        service.tenant_manager.get_current_tenant.return_value = None

        with pytest.raises(ValidationError, match="No tenant context"):
            await service.delete_project(PROJECT_ID)

    @pytest.mark.asyncio
    async def test_delete_not_found_raises(self):
        """Raises ResourceNotFoundError when project does not exist."""
        session = _make_session()

        # First call: project lookup returns None
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ResourceNotFoundError, match="not found or already deleted"):
            await service.delete_project(PROJECT_ID)

    @pytest.mark.asyncio
    async def test_delete_sets_status_and_timestamp(self):
        """Soft delete sets status='deleted' and deleted_at timestamp."""
        project = _make_project(status="active")
        session = _make_session()

        # First call: find project. Second call: find executions to decommission.
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
        """Soft delete decommissions active agent executions."""
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


# ---------------------------------------------------------------------------
# nuclear_delete_project tests
# ---------------------------------------------------------------------------


class TestNuclearDeleteProject:
    """Tests for ProjectDeletionService.nuclear_delete_project."""

    @pytest.mark.asyncio
    async def test_nuclear_no_tenant_raises(self):
        """Raises ValidationError when tenant is not set."""
        session = _make_session()
        service = _make_service(session)
        service.tenant_manager.get_current_tenant.return_value = None

        with pytest.raises(ValidationError, match="No tenant context"):
            await service.nuclear_delete_project(PROJECT_ID)

    @pytest.mark.asyncio
    async def test_nuclear_not_found_raises(self):
        """Raises ResourceNotFoundError when project does not exist."""
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ResourceNotFoundError, match="not found or access denied"):
            await service.nuclear_delete_project(PROJECT_ID)

    @pytest.mark.asyncio
    async def test_nuclear_deactivates_active_project(self):
        """Deactivates project if it's active before deletion."""
        project = _make_project(status="active", product_id=None)
        session = _make_session()

        # All queries return empty lists except the first (project lookup)
        call_count = 0
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_empty = MagicMock()
        mock_empty_scalars = MagicMock()
        mock_empty_scalars.all.return_value = []
        mock_empty.scalars.return_value = mock_empty_scalars
        # BE-9144: the bulk-delete repo methods now read result.rowcount (an int)
        # instead of len(SELECT); give the mocked delete result an integer count.
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

        # Project should be deactivated (set to inactive before deletion)
        assert project.status == "inactive"
        session.flush.assert_called()
        assert result.project_name == "Test Project"


# ---------------------------------------------------------------------------
# restore_project tests
# ---------------------------------------------------------------------------


class TestRestoreProject:
    """Tests for ProjectDeletionService.restore_project."""

    @pytest.mark.asyncio
    async def test_restore_not_found_raises(self):
        """Raises ResourceNotFoundError when project does not exist (BE-6049b: get_by_id -> None)."""
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ResourceNotFoundError, match="not found or access denied"):
            await service.restore_project(PROJECT_ID, TENANT_KEY)

    @pytest.mark.asyncio
    async def test_restore_cancelled_keeps_number(self):
        """A cancelled project (deleted_at IS NULL) restores without re-allocating its serial.

        BE-6049b decision C: only soft-deleted projects freed their serial; cancelled/completed
        keep their number. The restore path must NOT touch series_number here.
        """
        session = _make_session()
        project = _make_project(status="cancelled", deleted_at=None)
        project.series_number = 42
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        result = await service.restore_project(PROJECT_ID, TENANT_KEY)

        assert "restored successfully" in result.message
        assert project.series_number == 42  # unchanged — not re-allocated
        assert project.deleted_at is None
        session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# purge_all_deleted_projects tests
# ---------------------------------------------------------------------------


class TestPurgeAllDeletedProjects:
    """Tests for ProjectDeletionService.purge_all_deleted_projects."""

    @pytest.mark.asyncio
    async def test_purge_no_tenant_raises(self):
        """Raises ValidationError when tenant is not set."""
        session = _make_session()
        service = _make_service(session)
        service.tenant_manager.get_current_tenant.return_value = None

        with pytest.raises(ValidationError, match="No tenant context"):
            await service.purge_all_deleted_projects()

    @pytest.mark.asyncio
    async def test_purge_empty_returns_zero(self):
        """Returns purged_count=0 when no deleted projects exist."""
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


# ---------------------------------------------------------------------------
# Regression (BE-6238): purge must clear user_approvals before the cascade.
#
# These tests run against a REAL database. The bug is a DB-level RESTRICT FK
# violation (user_approvals -> agent_executions / agent_jobs / projects), which
# a mocked session cannot reproduce. Before the fix, nuclear_delete_project
# deleted agent_jobs (cascading agent_executions) WITHOUT first clearing the
# referencing user_approvals row, so PostgreSQL raised RestrictViolationError
# and the expired soft-deleted project was never purged.
# ---------------------------------------------------------------------------


async def _seed_project_with_approval(session, tenant_key):
    """Create product -> project -> agent_job -> agent_execution -> user_approval."""
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
    """ProjectDeletionService bound to the shared test session and tenant."""
    tenant_manager.set_current_tenant(tenant_key)
    return ProjectDeletionService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )


class TestPurgeClearsUserApprovals:
    """BE-6238: a project with a user_approvals row must purge without violating RESTRICT."""

    @pytest.mark.asyncio
    async def test_nuclear_delete_clears_user_approvals(self, db_manager, db_session, tenant_manager, test_tenant_key):
        """nuclear_delete_project succeeds and removes the user_approvals + agent_executions rows.

        Without the fix this raises asyncpg RestrictViolationError on
        ``user_approvals_agent_execution_id_fkey``.
        """
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
        """The soft-delete cascade helper (_purge_project_records) has the same gap; verify it too."""
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


# ---------------------------------------------------------------------------
# BE-9144: nuclear_delete_project batches per-collection deletes.
#
# The former implementation SELECTed each child collection then ORM-deleted it
# one row at a time (N+1 per collection). The fix bulk-deletes user_approvals,
# agent_jobs (+their executions, whose cascade is ORM-level so they go first),
# and messages in one statement each. Tasks stay per-row on purpose (the
# self-referential parent_task_id FK has no DB ondelete). These tests assert the
# deleted_counts + emptiness are unchanged AND the statement count no longer
# scales with the row count of the batched collections.
# ---------------------------------------------------------------------------


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
        """Statements that are a top-level SELECT against ``table`` (excludes a
        subquery SELECT nested inside a DELETE, which starts with DELETE)."""
        upper = table.upper()
        return sum(
            1 for s in self.statements if s.strip().upper().startswith("SELECT") and f"FROM {upper}" in s.upper()
        )


async def _seed_project_with_many_children(session, tenant_key, n=3):
    """product -> project (+ n each of: job/execution/approval, task, message)."""
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
    """BE-9144: batched child deletes preserve results and drop the per-row N+1."""

    @pytest.mark.asyncio
    async def test_nuclear_delete_batches_and_counts_are_equivalent(
        self, db_manager, db_session, tenant_manager, test_tenant_key
    ):
        project = await _seed_project_with_many_children(db_session, test_tenant_key, n=3)
        service = _real_db_service(db_manager, db_session, tenant_manager, test_tenant_key)

        engine = db_manager.async_engine.sync_engine
        with _DeleteStatementCounter(engine) as counter:
            result = await service.nuclear_delete_project(project.id)

        # Result-equivalence: counts reflect the 3 seeded rows per collection.
        assert result.deleted_counts["user_approvals"] == 3
        assert result.deleted_counts["agent_jobs"] == 3
        assert result.deleted_counts["tasks"] == 3
        assert result.deleted_counts["messages"] == 3

        # Batching guard (positive): one bulk DELETE per batched collection.
        assert counter.count("DELETE FROM user_approvals") == 1, counter.statements
        assert counter.count("DELETE FROM agent_executions") == 1, counter.statements
        assert counter.count("DELETE FROM agent_jobs") == 1, counter.statements
        assert counter.count("DELETE FROM messages") == 1, counter.statements
        # Fail-first guards (true N+1 differentiators, uncontaminated by the final
        # ORM session.delete(project) relationship loads):
        #  - user_approvals: the old get_user_approvals_for_project SELECT is gone
        #    (bulk delete reads nothing first); nothing else loads the table.
        #  - agent_executions: the old per-job ORM cascade loaded each job's
        #    executions (one SELECT per job — the N+1); the bulk delete loads none.
        # (agent_jobs/messages are excluded: session.delete(project) loads those
        # relationships in BOTH old and new code. Tasks stay per-row for the
        # self-ref FK and still SELECT by design.)
        assert counter.count_standalone_select_from("user_approvals") == 0, counter.statements
        assert counter.count_standalone_select_from("agent_executions") == 0, counter.statements

        # Every child row is gone.
        with tenant_session_context(db_session, test_tenant_key):
            for model in (UserApproval, AgentJob, AgentExecution, Task, Message):
                left = (
                    (await db_session.execute(select(model).where(model.tenant_key == test_tenant_key))).scalars().all()
                )
                assert left == [], f"{model.__name__} rows not fully deleted: {left}"
