# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid

import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.tasks import MessageCompletion, MessageRecipient
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _tk(suffix: str) -> str:
    return f"tk_fe9012c_{suffix}"


def _service(db_manager, db_session) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed(db_session, tenant: str) -> None:
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)


def _msg(history: dict, message_id: str) -> dict:
    return next(m for m in history["messages"] if m["message_id"] == message_id)


async def test_recipient_state_pending_then_acked(db_manager, db_session):
    tenant = _tk("pending")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="t", creator_id="alpha", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="beta", tenant_key=tenant)
    posted = await svc.post_to_thread(
        thread_id=tid,
        content="please act",
        from_agent="alpha",
        to_participant="beta",
        requires_action=True,
        tenant_key=tenant,
    )
    mid = posted["message_id"]

    before = await svc.get_thread_history(thread_id=tid, include_recipient_state=True, tenant_key=tenant)
    m = _msg(before, mid)
    assert m["recipients"] == ["beta"]
    assert m["acked_by"] == []
    assert m["completed_by"] == []
    assert m["pending_for"] == ["beta"]

    await svc.get_thread_history(thread_id=tid, as_participant="beta", mark_read=True, tenant_key=tenant)

    after = await svc.get_thread_history(thread_id=tid, include_recipient_state=True, tenant_key=tenant)
    m = _msg(after, mid)
    assert m["acked_by"] == ["beta"]
    assert m["pending_for"] == []


async def test_completion_counts_as_acted(db_manager, db_session):
    tenant = _tk("complete")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="t", creator_id="alpha", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="beta", tenant_key=tenant)
    posted = await svc.post_to_thread(
        thread_id=tid,
        content="do work",
        from_agent="alpha",
        to_participant="beta",
        requires_action=True,
        tenant_key=tenant,
    )
    mid = posted["message_id"]

    with tenant_session_context(db_session, tenant):
        db_session.add(MessageCompletion(id=str(uuid.uuid4()), message_id=mid, agent_id="beta", tenant_key=tenant))
        await db_session.flush()

    hist = await svc.get_thread_history(thread_id=tid, include_recipient_state=True, tenant_key=tenant)
    m = _msg(hist, mid)
    assert m["completed_by"] == ["beta"]
    assert m["pending_for"] == []


async def test_default_read_omits_recipient_state(db_manager, db_session):
    tenant = _tk("default")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="t", creator_id="alpha", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="beta", tenant_key=tenant)
    await svc.post_to_thread(thread_id=tid, content="hi", from_agent="alpha", to_participant="beta", tenant_key=tenant)

    hist = await svc.get_thread_history(thread_id=tid, tenant_key=tenant)
    m = hist["messages"][0]
    for k in ("recipients", "acked_by", "completed_by", "pending_for"):
        assert k not in m


async def test_recipient_state_tenant_scoped(db_manager, db_session):
    tenant = _tk("iso")
    other = _tk("iso_other")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="t", creator_id="alpha", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="beta", tenant_key=tenant)
    posted = await svc.post_to_thread(
        thread_id=tid, content="scoped", from_agent="alpha", to_participant="beta", tenant_key=tenant
    )
    mid = posted["message_id"]

    with tenant_session_context(db_session, other):
        db_session.add(MessageRecipient(id=str(uuid.uuid4()), message_id=mid, agent_id="ghost", tenant_key=other))
        await db_session.flush()

    hist = await svc.get_thread_history(thread_id=tid, include_recipient_state=True, tenant_key=tenant)
    m = _msg(hist, mid)
    assert m["recipients"] == ["beta"]
    assert "ghost" not in m["recipients"]
