# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6086: task-domain transaction-ownership regression tests.

The final repo in the BE-3006b/c transaction-ownership chain. ``task_repository``
was the last repository still committing inside the repo layer (4 sites:
``add_and_commit`` / ``commit`` / ``commit_and_refresh`` / ``delete_and_commit``).
It is now flush-only (``add_and_flush`` / ``flush`` / ``flush_and_refresh`` /
``delete_and_flush``); the session OWNER (the service entry-point scope) commits.

These tests pin the convention at the layer the change occurred -- TWO-SIDED, as
the manifest requires for a shared-write path:

* Forced-failure / no-partial-state (the repo flushes, never commits, so the
  owner's rollback discards everything):
  - ``test_add_and_flush_failure_leaves_no_partial_task`` -- a task-only write.
  - ``test_conversion_failure_after_flush_leaves_no_partial_state`` -- the
    task->project CONVERSION path: a failure after the converted flush rolls
    back the new project AND leaves the original task intact (atomic unit).
* Happy-path / persists (the load-bearing half -- prove the owner actually
  commits, not merely that the repo stopped committing):
  - ``test_log_task_happy_path_persists`` -- task create.
  - ``test_update_task_happy_path_persists_and_broadcasts_after_commit`` --
    task update (Shape B: the owner commits explicitly BEFORE the task:updated
    broadcast; the broadcast fires only after the write is durable).
  - ``test_change_status_happy_path_persists`` -- flush_and_refresh path.
  - ``test_convert_to_project_happy_path_persists`` -- conversion commits the
    whole unit (new project persists, original task is gone).

Parallel-safe: every test owns its setup under a freshly generated, unique
tenant key (no shared fixtures, no module-level mutable state, no ordering
deps). Happy-path tests commit real rows and purge their tenant in a finally
block. Forced-failure tests commit nothing that must survive, but still purge
their seed product/task for hygiene.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from giljo_mcp.exceptions import BaseGiljoError
from giljo_mcp.models.auth import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.tasks import Task
from giljo_mcp.repositories.task_repository import TaskRepository
from giljo_mcp.services.task_service import TaskService
from giljo_mcp.tenant import TenantManager


# ---------------------------------------------------------------------------
# Helpers -- pure functions (no module-level mutable state). Real committing
# sessions via db_manager.get_session_async so the commit-vs-flush distinction
# is observable (the shared transactional fixture would hide it).
# ---------------------------------------------------------------------------


def _make_task_service(db_manager, tenant_key, websocket_manager=None):
    """Build a TaskService bound to a real (committing) session path.

    No injected session -> the service uses db_manager.get_session_async, whose
    scope-exit auto-commit (or the explicit owner commit on the update path) is
    exactly the owner-commit behaviour under test.
    """
    tm = MagicMock()
    tm.get_current_tenant.return_value = tenant_key
    return TaskService(
        db_manager=db_manager,
        tenant_manager=tm,
        session=None,
        websocket_manager=websocket_manager,
    )


async def _seed_product(db_manager, tenant_key) -> str:
    """Create one active product (committed). Returns its id."""
    product_id = str(uuid4())
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Product(
                id=product_id,
                name=f"BE6086 Product {uuid4().hex[:6]}",
                description="txn-ownership test product",
                tenant_key=tenant_key,
                is_active=True,
                created_at=datetime.now(UTC),
            )
        )
    return product_id


async def _seed_task(db_manager, tenant_key, product_id, created_by_user_id=None) -> str:
    """Create one task (committed, untyped). Returns its id."""
    task_id = str(uuid4())
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Task(
                id=task_id,
                tenant_key=tenant_key,
                product_id=product_id,
                title="BE6086 task",
                description="txn-ownership test task",
                status="pending",
                priority="medium",
                created_by_user_id=created_by_user_id,
                created_at=datetime.now(UTC),
            )
        )
    return task_id


async def _seed_admin_user(db_manager, tenant_key) -> str:
    """Create an org + admin user (committed) for the conversion permission check.

    Returns the user id. Admin role makes the creator-or-admin gate pass.
    """
    org_id = str(uuid4())
    user_id = str(uuid4())
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Organization(
                id=org_id,
                tenant_key=tenant_key,
                name=f"BE6086 Org {uuid4().hex[:6]}",
                slug=f"be6086-org-{uuid4().hex[:8]}",
                is_active=True,
            )
        )
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=f"be6086_admin_{uuid4().hex[:6]}",
                email=f"be6086_{uuid4().hex[:6]}@example.com",
                password_hash="x",  # not exercised; gate uses role/id only
                full_name="BE6086 Admin",
                role="admin",
                tenant_key=tenant_key,
                org_id=org_id,
                is_active=True,
                created_at=datetime.now(UTC),
            )
        )
    return user_id


async def _purge_tenant(db_manager, tenant_key) -> None:
    """Delete every row this suite could have committed for a tenant (FK order)."""
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        await session.execute(delete(Task).where(Task.tenant_key == tenant_key))
        await session.execute(delete(Project).where(Project.tenant_key == tenant_key))
        await session.execute(delete(Product).where(Product.tenant_key == tenant_key))
        await session.execute(delete(User).where(User.tenant_key == tenant_key))
        await session.execute(delete(Organization).where(Organization.tenant_key == tenant_key))


async def _task_exists(db_manager, tenant_key, task_id) -> bool:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        found = await TaskRepository().get_task_by_id(session, task_id, tenant_key)
    return found is not None


# ---------------------------------------------------------------------------
# Forced-failure (no partial state)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_and_flush_failure_leaves_no_partial_task(db_manager):
    """Task-only path: a failure after add_and_flush (before owner commit) leaves no row.

    Pre-fix the repo committed inside add_and_commit, so the row would survive
    this rollback and the assertion would fail.
    """
    tenant_key = TenantManager.generate_tenant_key()
    product_id = await _seed_product(db_manager, tenant_key)
    task_id = str(uuid4())
    repo = TaskRepository()

    async def _flush_then_fail():
        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            task = Task(
                id=task_id,
                tenant_key=tenant_key,
                product_id=product_id,
                title="forced-failure task",
                description="must not persist",
                status="pending",
                priority="medium",
                created_at=datetime.now(UTC),
            )
            await repo.add_and_flush(session, task)
            # Failure AFTER the flush-only add, BEFORE the owner commits.
            raise RuntimeError("boom before owner commit")

    try:
        with pytest.raises(RuntimeError, match="boom before owner commit"):
            await _flush_then_fail()

        assert not await _task_exists(db_manager, tenant_key, task_id), (
            "partial task persisted despite a failure before the owner commit -- add_and_flush must flush, not commit"
        )
    finally:
        await _purge_tenant(db_manager, tenant_key)


@pytest.mark.asyncio
async def test_conversion_failure_after_flush_leaves_no_partial_state(db_manager):
    """Conversion path: a failure after the converted flush rolls the WHOLE unit back.

    The new project (flushed early to obtain its id) must NOT persist and the
    original task must NOT be deleted -- the task->project conversion commits as
    one transaction owned by the service, or rolls back wholly.
    """
    tenant_key = TenantManager.generate_tenant_key()
    try:
        product_id = await _seed_product(db_manager, tenant_key)
        user_id = await _seed_admin_user(db_manager, tenant_key)
        task_id = await _seed_task(db_manager, tenant_key, product_id, created_by_user_id=user_id)

        service = _make_task_service(db_manager, tenant_key)

        # Inject a failure AFTER the converted flush: the conversion impl calls
        # repo.flush(...) then repo.refresh(...). Make refresh raise so the
        # failure lands after the flush but before the owner (scope-exit) commit.
        async def _boom(*_a, **_kw):
            raise RuntimeError("boom after converted flush")

        service._conversion._repo.refresh = _boom

        with pytest.raises(BaseGiljoError):
            await service.convert_to_project(
                task_id=task_id,
                project_name="Should Not Persist",
                strategy="create_new",
                include_subtasks=False,
                user_id=user_id,
            )

        # The original task must still exist (its delete rolled back)...
        assert await _task_exists(db_manager, tenant_key, task_id), (
            "original task was lost -- conversion rollback must restore it"
        )
        # ...and NO project may have been persisted.
        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            result = await session.execute(select(Project).where(Project.tenant_key == tenant_key))
            projects = result.scalars().all()
        assert projects == [], "partial project persisted despite a failure before the owner commit"
    finally:
        await _purge_tenant(db_manager, tenant_key)


# ---------------------------------------------------------------------------
# Happy path (persists -- the load-bearing half)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_task_happy_path_persists(db_manager):
    """Create: log_task succeeds AND the row is durable (owner scope-exit commit)."""
    tenant_key = TenantManager.generate_tenant_key()
    try:
        product_id = await _seed_product(db_manager, tenant_key)
        service = _make_task_service(db_manager, tenant_key)

        task_id = await service.log_task(
            content="persist me",
            product_id=product_id,
            tenant_key=tenant_key,
        )

        assert task_id
        assert await _task_exists(db_manager, tenant_key, task_id), (
            "task did not persist -- the owner must commit after the repo flush"
        )
    finally:
        await _purge_tenant(db_manager, tenant_key)


@pytest.mark.asyncio
async def test_update_task_happy_path_persists_and_broadcasts_after_commit(db_manager):
    """Update (Shape B): the row persists AND task:updated fires after the commit.

    This is the trickiest caller -- it emits a WebSocket event inside the
    session scope, so the owner must commit EXPLICITLY before the broadcast. A
    converted-but-uncommitted bug would make the change silently not persist.
    """
    tenant_key = TenantManager.generate_tenant_key()
    mock_ws = MagicMock()
    mock_ws.broadcast_to_tenant = AsyncMock()
    try:
        product_id = await _seed_product(db_manager, tenant_key)
        task_id = await _seed_task(db_manager, tenant_key, product_id)
        service = _make_task_service(db_manager, tenant_key, websocket_manager=mock_ws)

        result = await service.update_task(task_id, status="in_progress", priority="high")

        assert "status" in result.updated_fields
        assert "priority" in result.updated_fields

        # Persisted at the owner?
        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            reloaded = await TaskRepository().get_task_by_id(session, task_id, tenant_key)
        assert reloaded is not None
        assert reloaded.status == "in_progress"
        assert reloaded.priority == "high"
        assert reloaded.started_at is not None  # auto-stamped on in_progress

        # Broadcast fired (after the explicit owner commit).
        mock_ws.broadcast_to_tenant.assert_called_once()
        assert mock_ws.broadcast_to_tenant.call_args.kwargs.get("event_type") == "task:updated"
        # BE-9518: task:updated must carry product_id like task:created already does.
        assert mock_ws.broadcast_to_tenant.call_args.kwargs["data"]["product_id"] == product_id
    finally:
        await _purge_tenant(db_manager, tenant_key)


@pytest.mark.asyncio
async def test_change_status_happy_path_persists(db_manager):
    """flush_and_refresh path: change_status succeeds AND persists at the owner."""
    tenant_key = TenantManager.generate_tenant_key()
    try:
        product_id = await _seed_product(db_manager, tenant_key)
        task_id = await _seed_task(db_manager, tenant_key, product_id)
        service = _make_task_service(db_manager, tenant_key)

        task = await service.change_status(task_id, "completed")
        assert task.status == "completed"

        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            reloaded = await TaskRepository().get_task_by_id(session, task_id, tenant_key)
        assert reloaded is not None
        assert reloaded.status == "completed"
        assert reloaded.completed_at is not None
    finally:
        await _purge_tenant(db_manager, tenant_key)


@pytest.mark.asyncio
async def test_convert_to_project_happy_path_persists(db_manager):
    """Conversion atomic commit: the new project persists AND the task is gone."""
    tenant_key = TenantManager.generate_tenant_key()
    try:
        product_id = await _seed_product(db_manager, tenant_key)
        user_id = await _seed_admin_user(db_manager, tenant_key)
        task_id = await _seed_task(db_manager, tenant_key, product_id, created_by_user_id=user_id)

        service = _make_task_service(db_manager, tenant_key)
        result = await service.convert_to_project(
            task_id=task_id,
            project_name="Converted Project",
            strategy="create_new",
            include_subtasks=False,
            user_id=user_id,
        )

        assert result.project_id
        assert result.project_name == "Converted Project"

        # The whole atomic unit committed: project exists, original task deleted.
        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            project = await TaskRepository().get_project_by_id(session, result.project_id, product_id, tenant_key)
        assert project is not None, "converted project did not persist -- owner must commit"
        assert not await _task_exists(db_manager, tenant_key, task_id), (
            "original task survived conversion -- the delete must persist atomically"
        )
    finally:
        await _purge_tenant(db_manager, tenant_key)
