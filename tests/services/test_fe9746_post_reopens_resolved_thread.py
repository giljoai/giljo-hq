# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.comm import CommThread
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


async def _setup(db_manager, db_session, suffix: str, status: str):
    tenant = f"tk_fe9746_{suffix}"
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
    svc = CommThreadService(db_manager, TenantManager(), session=db_session)
    thread = await svc.create_thread(subject="reopen me", creator_id="alpha", tenant_key=tenant)
    tid = thread["thread_id"]
    if status != "open":
        await svc.update_thread(thread_id=tid, status=status, tenant_key=tenant)
    return svc, tenant, tid


async def _status(db_session, tenant: str, tid: str) -> str:
    with tenant_session_context(db_session, tenant):
        row = (await db_session.execute(select(CommThread).where(CommThread.id == tid))).scalar_one()
        await db_session.refresh(row)
        return row.status


async def test_post_to_resolved_thread_reopens_it(db_manager, db_session):
    svc, tenant, tid = await _setup(db_manager, db_session, "reopen", "resolved")
    assert await _status(db_session, tenant, tid) == "resolved"

    result = await svc.post_to_thread(thread_id=tid, content="one more thing", from_agent="alpha", tenant_key=tenant)

    assert result["thread_reopened"] is True
    assert await _status(db_session, tenant, tid) == "active"


async def test_post_to_closed_thread_leaves_it_closed(db_manager, db_session):
    svc, tenant, tid = await _setup(db_manager, db_session, "closed", "closed")

    result = await svc.post_to_thread(thread_id=tid, content="too late", from_agent="alpha", tenant_key=tenant)

    assert result["thread_reopened"] is False
    assert await _status(db_session, tenant, tid) == "closed"


async def test_explicit_set_status_wins_on_a_resolved_thread(db_manager, db_session):
    svc, tenant, tid = await _setup(db_manager, db_session, "explicit", "resolved")

    result = await svc.post_to_thread(
        thread_id=tid, content="final word", from_agent="alpha", set_status="resolved", tenant_key=tenant
    )
    assert result["thread_reopened"] is False
    assert await _status(db_session, tenant, tid) == "resolved"

    result = await svc.post_to_thread(
        thread_id=tid, content="closing it", from_agent="alpha", set_status="closed", tenant_key=tenant
    )
    assert result["thread_reopened"] is False
    assert await _status(db_session, tenant, tid) == "closed"


async def test_post_to_open_thread_does_not_touch_status(db_manager, db_session):
    svc, tenant, tid = await _setup(db_manager, db_session, "open", "open")

    result = await svc.post_to_thread(thread_id=tid, content="hello", from_agent="alpha", tenant_key=tenant)

    assert result["thread_reopened"] is False
    assert await _status(db_session, tenant, tid) == "open"
