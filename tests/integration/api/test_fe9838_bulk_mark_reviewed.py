# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from giljo_mcp.models import Product, Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.tenant import TenantManager
from tests.helpers.test_db_helper import purge_tenant_rows
from tests.integration.api.test_fe9708_board_keeps_unreviewed_completed import _app


pytestmark = pytest.mark.asyncio

URL = "/api/v1/projects/reviewed/bulk"


async def _seed(db_manager, tenant_key: str, statuses: list[str]) -> list[str]:
    ids: list[str] = []
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        product = Product(
            id=str(uuid.uuid4()),
            name=f"FE-9838 {uuid.uuid4().hex[:6]}",
            description="bulk review",
            tenant_key=tenant_key,
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(product)
        await session.flush()
        for n, status in enumerate(statuses, start=1):
            project = Project(
                id=str(uuid.uuid4()),
                name=f"FE-9838 {n}",
                description="d",
                mission="m",
                status=status,
                tenant_key=tenant_key,
                product_id=product.id,
                series_number=n,
                execution_mode="claude_code_cli",
                created_at=datetime.now(UTC),
                completed_at=datetime.now(UTC) if status == "completed" else None,
            )
            session.add(project)
            ids.append(project.id)
        await session.commit()
    return ids


async def _reviewed_at(db_manager, tenant_key: str, project_id: str):
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        row = await session.execute(select(Project.reviewed_at).where(Project.id == project_id))
        return row.scalar_one()


@pytest_asyncio.fixture
async def tenant(db_manager):
    tenant_key = TenantManager.generate_tenant_key()
    yield tenant_key
    await purge_tenant_rows(db_manager, tenant_key)


async def test_marks_every_finished_project(db_manager, tenant):
    ids = await _seed(db_manager, tenant, ["completed", "completed", "terminated"])
    async with AsyncClient(transport=ASGITransport(app=_app(db_manager, tenant)), base_url="http://t") as client:
        resp = await client.post(URL, json={"project_ids": ids})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"marked": 3, "skipped": []}
    for pid in ids:
        assert await _reviewed_at(db_manager, tenant, pid) is not None


async def test_unfinished_project_is_skipped_and_the_rest_marked(db_manager, tenant):
    done, running = (await _seed(db_manager, tenant, ["completed", "active"]))[0:2]
    async with AsyncClient(transport=ASGITransport(app=_app(db_manager, tenant)), base_url="http://t") as client:
        resp = await client.post(URL, json={"project_ids": [done, running]})
    assert resp.json() == {"marked": 1, "skipped": [{"id": running, "reason": "not_finished"}]}
    assert await _reviewed_at(db_manager, tenant, done) is not None
    assert await _reviewed_at(db_manager, tenant, running) is None


async def test_another_tenants_project_is_skipped_never_marked(db_manager, tenant):
    mine = (await _seed(db_manager, tenant, ["completed"]))[0]
    other = TenantManager.generate_tenant_key()
    try:
        theirs = (await _seed(db_manager, other, ["completed"]))[0]
        async with AsyncClient(transport=ASGITransport(app=_app(db_manager, tenant)), base_url="http://t") as client:
            resp = await client.post(URL, json={"project_ids": [mine, theirs]})
        assert resp.json() == {"marked": 1, "skipped": [{"id": theirs, "reason": "not_found"}]}
        assert await _reviewed_at(db_manager, other, theirs) is None
    finally:
        await purge_tenant_rows(db_manager, other)


async def test_chain_member_is_skipped(db_manager, tenant):
    solo, member = await _seed(db_manager, tenant, ["completed", "completed"])
    async with db_manager.get_session_async(tenant_key=tenant) as session:
        session.add(
            SequenceRun(
                id=str(uuid.uuid4()),
                tenant_key=tenant,
                project_ids=[member],
                resolved_order=[member],
                execution_mode="subagent",
                status="running",
                project_statuses={},
            )
        )
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=_app(db_manager, tenant)), base_url="http://t") as client:
        resp = await client.post(URL, json={"project_ids": [solo, member]})
    assert resp.json() == {"marked": 1, "skipped": [{"id": member, "reason": "chain"}]}
    assert await _reviewed_at(db_manager, tenant, member) is None


async def test_repeating_keeps_the_first_stamp(db_manager, tenant):
    pid = (await _seed(db_manager, tenant, ["completed"]))[0]
    async with AsyncClient(transport=ASGITransport(app=_app(db_manager, tenant)), base_url="http://t") as client:
        await client.post(URL, json={"project_ids": [pid]})
        first = await _reviewed_at(db_manager, tenant, pid)
        again = await client.post(URL, json={"project_ids": [pid]})
    assert again.json()["marked"] == 1
    assert await _reviewed_at(db_manager, tenant, pid) == first


async def test_cap_empty_and_non_uuid_are_422(db_manager, tenant):
    async with AsyncClient(transport=ASGITransport(app=_app(db_manager, tenant)), base_url="http://t") as client:
        too_many = await client.post(URL, json={"project_ids": [str(uuid.uuid4()) for _ in range(501)]})
        empty = await client.post(URL, json={"project_ids": []})
        junk = await client.post(URL, json={"project_ids": ["not-a-uuid"]})
        at_cap = await client.post(URL, json={"project_ids": [str(uuid.uuid4()) for _ in range(500)]})
    assert too_many.status_code == 422
    assert empty.status_code == 422
    assert junk.status_code == 422
    assert at_cap.status_code == 200
    assert at_cap.json()["marked"] == 0
