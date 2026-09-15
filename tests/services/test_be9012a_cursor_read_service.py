# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy import update as sa_update

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.comm import CommParticipant
from giljo_mcp.models.tasks import Message, MessageAcknowledgment
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

_T1 = datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)
_T2 = datetime(2026, 1, 1, 0, 0, 2, tzinfo=UTC)


def _tk(suffix: str) -> str:
    return f"tk_be9012a_{suffix}"


def _service(db_manager, db_session) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed(db_session, tenant: str) -> None:
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)


async def _post(svc, tid, tenant, content, **kwargs) -> str:
    res = await svc.post_to_thread(thread_id=tid, content=content, from_agent="alpha", tenant_key=tenant, **kwargs)
    return res["message_id"]


async def _stamp(db_session, tenant, ids_ts) -> None:
    with tenant_session_context(db_session, tenant):
        for mid, ts in ids_ts:
            await db_session.execute(sa_update(Message).where(Message.id == mid).values(created_at=ts))
        await db_session.flush()


async def _cursor_row(db_session, tenant, tid, participant_id) -> CommParticipant:
    with tenant_session_context(db_session, tenant):
        res = await db_session.execute(
            select(CommParticipant).where(
                CommParticipant.tenant_key == tenant,
                CommParticipant.thread_id == tid,
                CommParticipant.participant_id == participant_id,
            )
        )
    return res.scalar_one()


async def test_cursor_is_per_participant_independent(db_manager, db_session):
    tenant = _tk("indep")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="t", creator_id="alpha", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="beta", tenant_key=tenant)
    await svc.join_thread(thread_id=tid, participant_id="gamma", tenant_key=tenant)
    m1 = await _post(svc, tid, tenant, "one")
    m2 = await _post(svc, tid, tenant, "two")
    await _stamp(db_session, tenant, [(m1, _T1), (m2, _T2)])

    beta_first = await svc.get_thread_history(
        thread_id=tid, as_participant="beta", unread_only=True, mark_read=True, tenant_key=tenant
    )
    assert beta_first["count"] == 2
    beta_second = await svc.get_thread_history(
        thread_id=tid, as_participant="beta", unread_only=True, tenant_key=tenant
    )
    assert beta_second["count"] == 0

    gamma = await svc.get_thread_history(thread_id=tid, as_participant="gamma", unread_only=True, tenant_key=tenant)
    assert gamma["count"] == 2

    beta_row = await _cursor_row(db_session, tenant, tid, "beta")
    gamma_row = await _cursor_row(db_session, tenant, tid, "gamma")
    assert beta_row.last_read_message_id == m2
    assert beta_row.last_read_at is not None
    assert gamma_row.last_read_message_id is None
    assert gamma_row.last_read_at is None


async def test_narrowed_mark_read_does_not_advance_watermark(db_manager, db_session):
    tenant = _tk("guard")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="t", creator_id="alpha", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="beta", tenant_key=tenant)
    m1 = await _post(svc, tid, tenant, "broadcast", requires_action=False)
    m2 = await _post(svc, tid, tenant, "please act", requires_action=True)
    await _stamp(db_session, tenant, [(m1, _T1), (m2, _T2)])

    narrowed = await svc.get_thread_history(
        thread_id=tid,
        as_participant="beta",
        action_required_only=True,
        mark_read=True,
        tenant_key=tenant,
    )
    assert [m["content"] for m in narrowed["messages"]] == ["please act"]

    with tenant_session_context(db_session, tenant):
        acked = (
            (
                await db_session.execute(
                    select(MessageAcknowledgment.message_id).where(
                        MessageAcknowledgment.tenant_key == tenant,
                        MessageAcknowledgment.agent_id == "beta",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert set(acked) == {m2}

    beta_row = await _cursor_row(db_session, tenant, tid, "beta")
    assert beta_row.last_read_at is None
    unread = await svc.get_thread_history(thread_id=tid, as_participant="beta", unread_only=True, tenant_key=tenant)
    assert unread["count"] == 2


async def test_full_drain_advances_cursor_and_re_ack_is_idempotent(db_manager, db_session):
    tenant = _tk("drain")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="t", creator_id="alpha", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="beta", tenant_key=tenant)
    m1 = await _post(svc, tid, tenant, "one")
    m2 = await _post(svc, tid, tenant, "two")
    await _stamp(db_session, tenant, [(m1, _T1), (m2, _T2)])

    async def _ack_count() -> int:
        with tenant_session_context(db_session, tenant):
            res = await db_session.execute(
                select(func.count())
                .select_from(MessageAcknowledgment)
                .where(
                    MessageAcknowledgment.tenant_key == tenant,
                    MessageAcknowledgment.agent_id == "beta",
                )
            )
        return res.scalar_one()

    first = await svc.get_thread_history(
        thread_id=tid, as_participant="beta", unread_only=True, mark_read=True, tenant_key=tenant
    )
    assert first["count"] == 2 and first["marked_read"] == 2
    assert await _ack_count() == 2
    row = await _cursor_row(db_session, tenant, tid, "beta")
    assert row.last_read_message_id == m2

    second = await svc.get_thread_history(
        thread_id=tid, as_participant="beta", unread_only=True, mark_read=True, tenant_key=tenant
    )
    assert second["count"] == 0 and second["marked_read"] == 0
    assert await _ack_count() == 2
