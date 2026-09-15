# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from sqlalchemy import text

from giljo_mcp.database import tenant_session_context
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _svc(db_manager, db_session) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed_product_project(db_session, tenant: str, project_id: str, series: int) -> None:
    with tenant_session_context(db_session, tenant):
        await db_session.execute(
            text(
                "INSERT INTO products (id, tenant_key, name, is_active) "
                "VALUES (:pid, :tk, 'P', true) ON CONFLICT (id) DO NOTHING"
            ),
            {"pid": f"prod_{tenant}", "tk": tenant},
        )
        await db_session.execute(
            text(
                "INSERT INTO projects (id, tenant_key, product_id, name, alias, description, mission, series_number) "
                "VALUES (:id, :tk, :prod, 'n', :alias, 'd', 'm', :s)"
            ),
            {"id": project_id, "tk": tenant, "prod": f"prod_{tenant}", "alias": f"P{series:05d}", "s": series},
        )
        await db_session.flush()


async def _count_thread(db_session, tenant: str, tid: str, *, project_null: bool = False) -> int:
    extra = " AND project_id IS NULL" if project_null else ""
    with tenant_session_context(db_session, tenant):
        res = await db_session.execute(text(f"SELECT COUNT(*) FROM comm_threads WHERE id = :tid{extra}"), {"tid": tid})
    return res.scalar()


async def test_project_purge_cascades_empty_bound_thread(db_manager, db_session):
    tenant = "tk_be9012d_cascade"
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
    await _seed_product_project(db_session, tenant, "pj_cascade", 1)

    svc = _svc(db_manager, db_session)
    thread = await svc.create_thread(
        subject="(project comms)", creator_id="alpha", project_id="pj_cascade", tenant_key=tenant
    )
    tid = thread["thread_id"]
    assert await _count_thread(db_session, tenant, tid) == 1

    with tenant_session_context(db_session, tenant):
        await db_session.execute(text("DELETE FROM projects WHERE id = 'pj_cascade'"))
        await db_session.flush()

    assert await _count_thread(db_session, tenant, tid) == 0, "bound thread should CASCADE away on project purge"
    assert await _count_thread(db_session, tenant, tid, project_null=True) == 0, (
        "thread must not be orphaned into the town square (the old SET NULL bug)"
    )


async def test_project_purge_cascades_bound_thread_with_posts(db_manager, db_session):
    tenant = "tk_be9012d_cascade_posts"
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
    await _seed_product_project(db_session, tenant, "pj_posts", 1)

    svc = _svc(db_manager, db_session)
    thread = await svc.create_thread(
        subject="(project comms)", creator_id="alpha", project_id="pj_posts", tenant_key=tenant
    )
    tid = thread["thread_id"]
    await svc.post_to_thread(thread_id=tid, content="hello", from_agent="alpha", tenant_key=tenant)

    with tenant_session_context(db_session, tenant):
        await db_session.execute(text("DELETE FROM messages WHERE project_id = 'pj_posts'"))
        await db_session.execute(text("DELETE FROM projects WHERE id = 'pj_posts'"))
        await db_session.flush()
        remaining_msgs = (
            await db_session.execute(text("SELECT COUNT(*) FROM messages WHERE thread_id = :tid"), {"tid": tid})
        ).scalar()
        remaining_parts = (
            await db_session.execute(
                text("SELECT COUNT(*) FROM comm_participants WHERE thread_id = :tid"), {"tid": tid}
            )
        ).scalar()

    assert await _count_thread(db_session, tenant, tid) == 0, "bound thread cascades on purge"
    assert remaining_msgs == 0, "thread posts cascade with the thread (messages.thread_id CASCADE)"
    assert remaining_parts == 0, "participants cascade with the thread (comm_participants CASCADE)"


async def test_soft_delete_keeps_bound_thread(db_manager, db_session):
    tenant = "tk_be9012d_softdelete"
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
    await _seed_product_project(db_session, tenant, "pj_soft", 1)

    svc = _svc(db_manager, db_session)
    thread = await svc.create_thread(
        subject="(project comms)", creator_id="alpha", project_id="pj_soft", tenant_key=tenant
    )
    tid = thread["thread_id"]

    with tenant_session_context(db_session, tenant):
        await db_session.execute(
            text("UPDATE projects SET status = 'deleted', deleted_at = now() WHERE id = 'pj_soft'")
        )
        await db_session.flush()

    assert await _count_thread(db_session, tenant, tid) == 1, "soft delete must NOT touch the bound thread"
    with tenant_session_context(db_session, tenant):
        still_bound = (
            await db_session.execute(text("SELECT project_id FROM comm_threads WHERE id = :tid"), {"tid": tid})
        ).scalar()
    assert still_bound == "pj_soft", "thread stays bound to the soft-deleted project (restore keeps it)"
