# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from giljo_mcp.thin_prompt_generator import build_continuation_prompt
from tests.helpers.taxonomy_seeds import next_series_number


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
        await session.execute(text("DELETE FROM projects WHERE name LIKE 'chain-member-%'"))
        await session.commit()


def _svc(session: AsyncSession) -> SequenceRunService:
    return SequenceRunService(db_manager=None, tenant_manager=None, session=session)


async def _seed_live_project(session: AsyncSession, tenant: str) -> str:
    pid = str(uuid.uuid4())
    _product_id = str(uuid.uuid4())
    session.add(
        Product(
            id=_product_id,
            tenant_key=tenant,
            name=f"Owning Product {_product_id[:8]}",
            description="seeded",
            is_active=False,
        )
    )
    session.add(
        Project(
            id=pid,
            product_id=_product_id,
            tenant_key=tenant,
            name=f"chain-member-{pid[:8]}",
            description="live chain member",
            mission="member mission",
            series_number=next_series_number(),
        )
    )
    await session.flush()
    return pid


async def _create(svc: SequenceRunService, tenant: str, *, status: str = "pending") -> dict:
    pa = await _seed_live_project(svc._session, tenant)
    pb = await _seed_live_project(svc._session, tenant)
    return await svc.create(
        project_ids=[pa, pb],
        resolved_order=[pa, pb],
        execution_mode=_MODE,
        status=status,
        project_statuses={pa: "pending", pb: "pending"},
        tenant_key=tenant,
    )




async def test_list_active_tenant_isolation(db_session: AsyncSession) -> None:
    tenant_a = TenantManager.generate_tenant_key()
    tenant_b = TenantManager.generate_tenant_key()
    svc = _svc(db_session)

    a1 = await _create(svc, tenant_a)
    a2 = await _create(svc, tenant_a, status="running")
    await _create(svc, tenant_b)

    runs_a = await svc.list_active(tenant_key=tenant_a)
    ids_a = {r["id"] for r in runs_a}
    assert ids_a == {a1["id"], a2["id"]}, "tenant A must see only its own active runs"

    runs_b = await svc.list_active(tenant_key=tenant_b)
    assert all(r["tenant_key"] == tenant_b for r in runs_b)
    assert a1["id"] not in {r["id"] for r in runs_b}, "TENANT LEAK: B saw A's run"


async def test_list_active_status_filter(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _svc(db_session)

    pending = await _create(svc, tenant, status="pending")
    done = await _create(svc, tenant, status="pending")
    await svc.update(run_id=done["id"], tenant_key=tenant, status="completed")

    active = await svc.list_active(tenant_key=tenant)
    active_ids = {r["id"] for r in active}
    assert pending["id"] in active_ids
    assert done["id"] not in active_ids, "completed run must be excluded from the active default"

    completed = await svc.list_active(tenant_key=tenant, statuses=("completed",))
    assert {r["id"] for r in completed} == {done["id"]}


async def test_list_active_rejects_invalid_status(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _svc(db_session)
    with pytest.raises(ValidationError):
        await svc.list_active(tenant_key=tenant, statuses=("not_a_status",))




def test_continuation_prompt_carries_chain_brief() -> None:
    run_id = str(uuid.uuid4())
    order = ["proj-head", "proj-2", "proj-3"]
    prompt = build_continuation_prompt(
        project_id="proj-head",
        agent_id="agent-1",
        job_id="job-1",
        run_id=run_id,
        current_index=1,
        resolved_order=order,
        overarching_mission="Ship the whole widget pipeline end to end.",
    )
    assert "CHAIN CONTINUATION" in prompt
    assert run_id in prompt
    assert "proj-head -> proj-2 -> proj-3" in prompt
    assert "Ship the whole widget pipeline end to end." in prompt
    assert "Resume at index: 1" in prompt
    assert "launch_implementation per project" in prompt


def test_continuation_prompt_solo_unchanged_without_run() -> None:
    solo = build_continuation_prompt(
        project_id="proj-1",
        agent_id="agent-1",
        job_id="job-1",
    )
    assert "CHAIN CONTINUATION" not in solo
    assert "CONTINUATION SESSION" in solo
