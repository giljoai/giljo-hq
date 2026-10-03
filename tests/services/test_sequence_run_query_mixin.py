# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import itertools
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

_MODE = "claude_code_cli"


@pytest_asyncio.fixture
async def cleanup_tenants(db_manager):
    tenants: list[str] = []
    yield tenants
    for tk in tenants:
        async with db_manager.get_session_async(tenant_key=tk) as session:
            await session.execute(delete(AgentExecution).where(AgentExecution.tenant_key == tk))
            await session.execute(delete(AgentJob).where(AgentJob.tenant_key == tk))
            await session.execute(delete(SequenceRun).where(SequenceRun.tenant_key == tk))
            await session.execute(delete(Project).where(Project.tenant_key == tk))
            await session.execute(delete(Product).where(Product.tenant_key == tk))
            await session.commit()


def _seq_svc(session: AsyncSession) -> SequenceRunService:
    return SequenceRunService(db_manager=None, tenant_manager=None, session=session)


async def _create_product(session: AsyncSession, tenant_key: str) -> str:
    product_id = str(uuid.uuid4())
    session.add(Product(id=product_id, tenant_key=tenant_key, name="Query Mixin Test Product"))
    await session.commit()
    return product_id


_SERIALS = itertools.count(1)


async def _create_project(session: AsyncSession, tenant_key: str, product_id: str) -> str:
    project_id = str(uuid.uuid4())
    session.add(
        Project(
            id=project_id,
            product_id=product_id,
            name="Query Mixin Test Project",
            description="query mixin regression",
            mission="query mixin regression mission",
            status="completed",
            tenant_key=tenant_key,
            execution_mode="multi_terminal",
            series_number=next(_SERIALS),
        )
    )
    await session.commit()
    return project_id


async def _create_run(session: AsyncSession, tenant_key: str, project_ids: list[str]) -> dict:
    return await _seq_svc(session).create(
        project_ids=project_ids,
        resolved_order=project_ids,
        execution_mode=_MODE,
        status="running",
        project_statuses=dict.fromkeys(project_ids, "completed"),
        tenant_key=tenant_key,
    )


async def test_get_resolves_via_mixin_and_is_tenant_scoped(
    db_session: AsyncSession, cleanup_tenants: list[str]
) -> None:
    tenant = TenantManager.generate_tenant_key()
    cleanup_tenants.append(tenant)

    product_id = await _create_product(db_session, tenant)
    p1 = await _create_project(db_session, tenant, product_id)
    p2 = await _create_project(db_session, tenant, product_id)
    run = await _create_run(db_session, tenant, [p1, p2])
    run_id = run["id"]
    svc = _seq_svc(db_session)

    got = await svc.get(run_id=run_id, tenant_key=tenant)
    assert got["id"] == run_id

    other_tenant = TenantManager.generate_tenant_key()
    with pytest.raises(ResourceNotFoundError):
        await svc.get(run_id=run_id, tenant_key=other_tenant)


async def _set_run(session: AsyncSession, run_id: str, **values) -> None:
    await session.execute(update(SequenceRun).where(SequenceRun.id == run_id).values(**values))
    await session.commit()


async def test_list_review_pending_surfaces_terminal_unreviewed_and_excludes_active(
    db_session: AsyncSession, cleanup_tenants: list[str]
) -> None:
    tenant = TenantManager.generate_tenant_key()
    cleanup_tenants.append(tenant)

    product_id = await _create_product(db_session, tenant)
    p1 = await _create_project(db_session, tenant, product_id)
    p2 = await _create_project(db_session, tenant, product_id)

    active = await _seq_svc(db_session).create(
        project_ids=[p1],
        resolved_order=[p1],
        execution_mode=_MODE,
        status="running",
        project_statuses={p1: "completed"},
        tenant_key=tenant,
    )
    term = await _create_run(db_session, tenant, [p1, p2])
    await _set_run(db_session, term["id"], status="completed")

    svc = _seq_svc(db_session)
    pending = await svc.list_review_pending(tenant_key=tenant)
    ids = [r["id"] for r in pending]

    assert term["id"] in ids
    assert active["id"] not in ids

    other_tenant = TenantManager.generate_tenant_key()
    assert await svc.list_review_pending(tenant_key=other_tenant) == []


async def test_list_review_pending_drops_fully_reviewed_run(
    db_session: AsyncSession, cleanup_tenants: list[str]
) -> None:
    tenant = TenantManager.generate_tenant_key()
    cleanup_tenants.append(tenant)

    product_id = await _create_product(db_session, tenant)
    p1 = await _create_project(db_session, tenant, product_id)
    p2 = await _create_project(db_session, tenant, product_id)

    term = await _create_run(db_session, tenant, [p1, p2])
    svc = _seq_svc(db_session)

    await _set_run(db_session, term["id"], status="completed")
    assert [r["id"] for r in await svc.list_review_pending(tenant_key=tenant)] == [term["id"]]

    await _set_run(db_session, term["id"], reviewed_project_ids=[p1, p2])
    assert await svc.list_review_pending(tenant_key=tenant) == []


async def test_list_review_pending_drops_run_whose_completed_members_are_gone(
    db_session: AsyncSession, cleanup_tenants: list[str]
) -> None:
    from datetime import UTC, datetime

    tenant = TenantManager.generate_tenant_key()
    cleanup_tenants.append(tenant)

    product_id = await _create_product(db_session, tenant)
    p1 = await _create_project(db_session, tenant, product_id)
    p2 = await _create_project(db_session, tenant, product_id)
    ghost = await _create_run(db_session, tenant, [p1, p2])
    await _set_run(db_session, ghost["id"], status="cancelled", project_statuses={p1: "completed"})

    p3 = await _create_project(db_session, tenant, product_id)
    soft = await _create_run(db_session, tenant, [p3])
    await _set_run(db_session, soft["id"], status="completed")

    svc = _seq_svc(db_session)
    before = {r["id"] for r in await svc.list_review_pending(tenant_key=tenant)}
    assert {ghost["id"], soft["id"]} <= before

    await db_session.execute(delete(Project).where(Project.id.in_([p1, p2])))
    await db_session.execute(
        update(Project).where(Project.id == p3).values(deleted_at=datetime.now(UTC), status="deleted")
    )
    await db_session.commit()

    after = [r["id"] for r in await svc.list_review_pending(tenant_key=tenant)]
    assert ghost["id"] not in after
    assert soft["id"] not in after


async def test_listed_runs_carry_their_members_product_id(db_session: AsyncSession, cleanup_tenants: list[str]) -> None:
    tenant = TenantManager.generate_tenant_key()
    cleanup_tenants.append(tenant)

    product_a = await _create_product(db_session, tenant)
    product_b = await _create_product(db_session, tenant)
    gone = await _create_project(db_session, tenant, product_a)
    live_b = await _create_project(db_session, tenant, product_b)
    await db_session.execute(update(Project).where(Project.id == live_b).values(status="inactive"))
    await db_session.commit()
    active = await _create_run(db_session, tenant, [gone, live_b])
    await db_session.execute(delete(Project).where(Project.id == gone))
    await db_session.commit()

    done_a = await _create_project(db_session, tenant, product_a)
    term = await _create_run(db_session, tenant, [done_a])
    await _set_run(db_session, term["id"], status="completed")

    svc = _seq_svc(db_session)
    listed = {r["id"]: r for r in await svc.list_active(tenant_key=tenant)}
    assert listed[active["id"]]["product_id"] == product_b

    pending = {r["id"]: r for r in await svc.list_review_pending(tenant_key=tenant)}
    assert pending[term["id"]]["product_id"] == product_a


async def test_chain_review_stamps_the_same_project_field_and_group_display_is_unchanged(
    db_session: AsyncSession, cleanup_tenants: list[str]
) -> None:
    tenant = TenantManager.generate_tenant_key()
    cleanup_tenants.append(tenant)

    product_id = await _create_product(db_session, tenant)
    p1 = await _create_project(db_session, tenant, product_id)
    p2 = await _create_project(db_session, tenant, product_id)
    term = await _create_run(db_session, tenant, [p1, p2])
    await _set_run(db_session, term["id"], status="completed")
    svc = _seq_svc(db_session)

    async def stamp(pid: str):
        return (await db_session.execute(select(Project.reviewed_at).where(Project.id == pid))).scalar_one()

    assert await stamp(p1) is None
    await svc.mark_member_reviewed(run_id=term["id"], project_id=p1, tenant_key=tenant)
    assert await stamp(p1) is not None
    assert await stamp(p2) is None
    assert [r["id"] for r in await svc.list_review_pending(tenant_key=tenant)] == [term["id"]]

    await svc.mark_member_reviewed(run_id=term["id"], project_id=p2, tenant_key=tenant)
    assert await stamp(p2) is not None
    assert await svc.list_review_pending(tenant_key=tenant) == []
