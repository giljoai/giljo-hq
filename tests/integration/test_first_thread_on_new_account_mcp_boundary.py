# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import (
    DEFAULT_TAXONOMY_TYPES,
    RESERVED_CHAT_THREAD_TYPE_ABBR,
    RESERVED_TASK_TYPE_ABBR,
    ensure_default_types_seeded,
    ensure_reserved_type,
)
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


async def _abbrs(session, tenant_key: str) -> list[str]:
    with tenant_session_context(session, tenant_key):
        rows = await session.execute(select(TaxonomyType.abbreviation).where(TaxonomyType.tenant_key == tenant_key))
        return sorted(rows.scalars().all())


_ALL_ABBRS = sorted(t["abbr"] for t in DEFAULT_TAXONOMY_TYPES)


@pytest_asyncio.fixture
async def fresh_tenant(db_manager, db_session):
    tenant_key = TenantManager.generate_tenant_key()
    other_tenant = TenantManager.generate_tenant_key()
    suffix = uuid4().hex[:8]
    for tk in (tenant_key, other_tenant):
        db_session.add(Organization(name=f"Org {tk[-6:]}{suffix}", slug=f"o-{tk[-8:]}", tenant_key=tk, is_active=True))
    await db_session.commit()
    assert await _abbrs(db_session, tenant_key) == [], "RED tenant must start with zero taxonomy rows"
    try:
        yield tenant_key, other_tenant
    finally:
        for tk in (tenant_key, other_tenant):
            async with db_manager.get_session_async() as cleanup:
                with tenant_session_context(cleanup, tk):
                    await cleanup.execute(delete(TaxonomyType).where(TaxonomyType.tenant_key == tk))
                await cleanup.commit()


def _payload(res) -> dict:
    if getattr(res, "structuredContent", None):
        return res.structured_content
    return json.loads(res.content[0].text)


async def _mcp_create_thread(db_manager, db_session, monkeypatch, tenant_key: str):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager
    state.tool_accessor = ToolAccessor(
        db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session
    )
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)
    try:
        async with create_connected_server_and_client_session(mcp_sdk_server.mcp) as s:
            res = await s.call_tool("create_thread", {"subject": "first", "creator_id": "agent-alpha"})
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior
    assert res.is_error is False, "\n".join(getattr(b, "text", "") or "" for b in res.content)
    return _payload(res)


async def test_transport_first_thread_on_tenant_with_no_taxonomy(db_manager, db_session, monkeypatch, fresh_tenant):
    tenant_key, other_tenant = fresh_tenant
    payload = await _mcp_create_thread(db_manager, db_session, monkeypatch, tenant_key)
    assert payload["chat_id"] == "CHT-0001"
    assert await _abbrs(db_session, tenant_key) == _ALL_ABBRS
    assert await _abbrs(db_session, other_tenant) == []


async def test_service_first_thread_on_tenant_with_no_taxonomy(db_manager, db_session, fresh_tenant):
    tenant_key, other_tenant = fresh_tenant
    svc = CommThreadService(db_manager, TenantManager(), session=db_session)
    thread = await svc.create_thread(subject="first", creator_id="agent-alpha", tenant_key=tenant_key)
    assert thread["chat_id"] == "CHT-0001"
    assert await _abbrs(db_session, other_tenant) == []


async def test_thread_first_then_project_types_still_seeded(db_manager, db_session, fresh_tenant):
    tenant_key, _ = fresh_tenant
    svc = CommThreadService(db_manager, TenantManager(), session=db_session)
    await svc.create_thread(subject="first", creator_id="a", tenant_key=tenant_key)
    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)
    assert await _abbrs(db_session, tenant_key) == _ALL_ABBRS


async def test_project_first_then_thread(db_manager, db_session, fresh_tenant):
    tenant_key, _ = fresh_tenant
    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)
    svc = CommThreadService(db_manager, TenantManager(), session=db_session)
    thread = await svc.create_thread(subject="first", creator_id="a", tenant_key=tenant_key)
    assert thread["chat_id"] == "CHT-0001"
    assert await _abbrs(db_session, tenant_key) == _ALL_ABBRS


async def test_existing_tenant_without_cht_heals_on_first_thread(db_manager, db_session, fresh_tenant):
    tenant_key, _ = fresh_tenant
    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)
    with tenant_session_context(db_session, tenant_key):
        await db_session.execute(
            delete(TaxonomyType).where(
                TaxonomyType.tenant_key == tenant_key, TaxonomyType.abbreviation == RESERVED_CHAT_THREAD_TYPE_ABBR
            )
        )
    svc = CommThreadService(db_manager, TenantManager(), session=db_session)
    thread = await svc.create_thread(subject="first", creator_id="a", tenant_key=tenant_key)
    assert thread["chat_id"] == "CHT-0001"
    assert await _abbrs(db_session, tenant_key) == _ALL_ABBRS


async def test_task_first_write_does_not_leave_tenant_without_default_types(db_session, fresh_tenant):
    tenant_key, _ = fresh_tenant
    with tenant_session_context(db_session, tenant_key):
        await ensure_reserved_type(db_session, tenant_key, RESERVED_TASK_TYPE_ABBR)
        await ensure_default_types_seeded(db_session, tenant_key)
    assert await _abbrs(db_session, tenant_key) == _ALL_ABBRS


async def test_two_first_threads_at_once_make_one_cht_row(db_manager, fresh_tenant):
    tenant_key, _ = fresh_tenant

    async def first_thread(tag: str):
        svc = CommThreadService(db_manager, TenantManager())
        return await svc.create_thread(subject=tag, creator_id=tag, tenant_key=tenant_key)

    results = await asyncio.gather(first_thread("a"), first_thread("b"), return_exceptions=True)
    for r in results:
        assert not isinstance(r, Exception) or "taxonomy" not in str(r).lower(), r
    async with db_manager.get_session_async() as s:
        assert await _abbrs(s, tenant_key) == _ALL_ABBRS
        with tenant_session_context(s, tenant_key):
            count = (
                await s.execute(
                    select(func.count())
                    .select_from(TaxonomyType)
                    .where(
                        TaxonomyType.tenant_key == tenant_key,
                        TaxonomyType.abbreviation == RESERVED_CHAT_THREAD_TYPE_ABBR,
                    )
                )
            ).scalar_one()
    assert count == 1
