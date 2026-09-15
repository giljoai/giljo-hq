# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import Product, Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

_MODE = "claude_code_cli"


@pytest_asyncio.fixture(autouse=True)
async def _wipe_sequence_runs(db_manager):
    yield
    async with db_manager.get_session_async() as session:
        with tenant_isolation_bypass(
            session, reason="test teardown: wipe sequence_runs (per-worker DB)", models=(SequenceRun,)
        ):
            await session.execute(delete(SequenceRun))
        await session.commit()


def _svc(session: AsyncSession, tenant_key: str | None = None) -> SequenceRunService:
    tm = TenantManager()
    if tenant_key:
        tm.set_current_tenant(tenant_key)
    return SequenceRunService(db_manager=None, tenant_manager=tm, session=session)


async def _create(svc: SequenceRunService, tenant: str, *, project_ids: list[str] | None = None, **kw) -> dict:
    pids = project_ids or [str(uuid.uuid4()), str(uuid.uuid4())]
    return await svc.create(
        project_ids=pids,
        resolved_order=list(pids),
        execution_mode=_MODE,
        project_statuses=dict.fromkeys(pids, "pending"),
        tenant_key=tenant,
        **kw,
    )


async def _make_project(session: AsyncSession, tenant: str, *, status: ProjectStatus = ProjectStatus.INACTIVE) -> str:
    product = Product(
        id=str(uuid.uuid4()),
        name="Chain Product",
        description="desc",
        tenant_key=tenant,
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(product)
    await session.flush()
    project = Project(
        id=str(uuid.uuid4()),
        name="Chain Project",
        description="human requirements",
        mission="mission",
        tenant_key=tenant,
        product_id=product.id,
        status=status,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(project)
    await session.flush()
    return project.id




async def test_create_defaults_locked_false(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _svc(db_session, tenant)
    run = await _create(svc, tenant)
    assert run["locked"] is False, "new runs start in the Editing tier (locked=false)"


async def test_stage_sets_locked_unstage_clears(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _svc(db_session, tenant)
    run = await _create(svc, tenant)

    staged = await svc.update(run_id=run["id"], tenant_key=tenant, locked=True)
    assert staged["locked"] is True, "Stage must lock the run"

    unstaged = await svc.update(run_id=run["id"], tenant_key=tenant, locked=False)
    assert unstaged["locked"] is False, "Unstage must unlock the run (chain intact)"
    assert unstaged["project_ids"] == run["project_ids"]




async def test_remove_member_drops_one_project(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _svc(db_session, tenant)
    p1, p2, p3 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    run = await _create(svc, tenant, project_ids=[p1, p2, p3])

    updated = await svc.remove_member(run_id=run["id"], project_id=p2, tenant_key=tenant)
    assert updated["project_ids"] == [p1, p3]
    assert updated["resolved_order"] == [p1, p3]
    assert p2 not in updated["project_statuses"]
    assert updated["status"] == "pending", "still >=2 members -> run stays active"


async def test_remove_member_recomputes_current_index(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _svc(db_session, tenant)
    p1, p2, p3 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    run = await _create(svc, tenant, project_ids=[p1, p2, p3])
    await svc.update(run_id=run["id"], tenant_key=tenant, current_index=2)

    updated = await svc.remove_member(run_id=run["id"], project_id=p1, tenant_key=tenant)
    assert updated["resolved_order"] == [p2, p3]
    assert updated["current_index"] == 1


async def test_remove_member_absent_is_noop(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _svc(db_session, tenant)
    p1, p2, p3 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    run = await _create(svc, tenant, project_ids=[p1, p2, p3])
    updated = await svc.remove_member(run_id=run["id"], project_id="not-a-member", tenant_key=tenant)
    assert updated["project_ids"] == [p1, p2, p3], "removing an absent project is a no-op"


async def test_remove_member_tenant_isolation(db_session: AsyncSession) -> None:
    tenant_a = TenantManager.generate_tenant_key()
    tenant_b = TenantManager.generate_tenant_key()
    svc = _svc(db_session, tenant_a)
    p1, p2, p3 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    run_a = await _create(svc, tenant_a, project_ids=[p1, p2, p3])

    from giljo_mcp.exceptions import ResourceNotFoundError

    svc_b = _svc(db_session, tenant_b)
    with pytest.raises(ResourceNotFoundError):
        await svc_b.remove_member(run_id=run_a["id"], project_id=p2, tenant_key=tenant_b)

    still = await svc.get(run_id=run_a["id"], tenant_key=tenant_a)
    assert still["project_ids"] == [p1, p2, p3]


async def test_remove_member_rejects_empty_project_id(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _svc(db_session, tenant)
    run = await _create(svc, tenant)
    with pytest.raises(ValidationError):
        await svc.remove_member(run_id=run["id"], project_id="   ", tenant_key=tenant)




async def test_reduce_to_one_dissolves_run(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _svc(db_session, tenant)
    lone = await _make_project(db_session, tenant, status=ProjectStatus.INACTIVE)
    other = str(uuid.uuid4())
    run = await _create(svc, tenant, project_ids=[lone, other])

    result = await svc.remove_member(run_id=run["id"], project_id=other, tenant_key=tenant)
    assert result["status"] == "cancelled", "removal leaving 1 dissolves the run"

    active = await svc.list_active(tenant_key=tenant)
    assert run["id"] not in {r["id"] for r in active}


async def test_reduce_to_one_does_not_activate_lone_project(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _svc(db_session, tenant)
    lone = await _make_project(db_session, tenant, status=ProjectStatus.INACTIVE)
    other = str(uuid.uuid4())
    run = await _create(svc, tenant, project_ids=[lone, other])

    result = await svc.remove_member(run_id=run["id"], project_id=other, tenant_key=tenant)
    assert result["status"] == "cancelled"

    row = await db_session.execute(select(Project).where(Project.id == lone))
    project = row.scalar_one()
    assert project.status == ProjectStatus.INACTIVE, "reduce-to-1 must NOT auto-activate the lone project"
    assert project.implementation_launched_at is None




async def test_ultralock_running_refuses_unstage(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _svc(db_session, tenant)
    run = await _create(svc, tenant, status="running")
    await svc.update(run_id=run["id"], tenant_key=tenant, locked=True)
    with pytest.raises(ValidationError):
        await svc.update(run_id=run["id"], tenant_key=tenant, locked=False)


async def test_ultralock_running_refuses_member_edit(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _svc(db_session, tenant)
    p1, p2, p3 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    run = await _create(svc, tenant, project_ids=[p1, p2, p3], status="running")
    with pytest.raises(ValidationError):
        await svc.remove_member(run_id=run["id"], project_id=p2, tenant_key=tenant)


async def test_ultralock_staging_complete_member_refuses_edit(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _svc(db_session, tenant)
    staged_member = await _make_project(db_session, tenant)
    row = await db_session.execute(select(Project).where(Project.id == staged_member))
    proj = row.scalar_one()
    proj.staging_status = "staging_complete"
    await db_session.flush()
    other = str(uuid.uuid4())
    run = await _create(svc, tenant, project_ids=[staged_member, other])

    with pytest.raises(ValidationError):
        await svc.remove_member(run_id=run["id"], project_id=other, tenant_key=tenant)
    with pytest.raises(ValidationError):
        await svc.update(run_id=run["id"], tenant_key=tenant, locked=False)


async def test_editing_tier_allows_unstage_and_remove(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _svc(db_session, tenant)
    p1, p2, p3 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    run = await _create(svc, tenant, project_ids=[p1, p2, p3])
    await svc.update(run_id=run["id"], tenant_key=tenant, locked=True)
    unstaged = await svc.update(run_id=run["id"], tenant_key=tenant, locked=False)
    assert unstaged["locked"] is False
    removed = await svc.remove_member(run_id=run["id"], project_id=p3, tenant_key=tenant)
    assert removed["project_ids"] == [p1, p2]
