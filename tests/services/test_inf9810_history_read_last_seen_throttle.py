# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.comm import CommParticipant
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

AGENT = "agent-reader"


def _tk(suffix: str) -> str:
    return f"tk_inf9810_{suffix}_{uuid.uuid4().hex[:8]}"


async def _setup(db_manager, db_session, suffix: str):
    tenant = _tk(suffix)
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
    svc = CommThreadService(db_manager, TenantManager(), session=db_session)
    thread_id = (await svc.create_thread(subject="read", creator_id="agent-orch", tenant_key=tenant))["thread_id"]
    await svc.join_thread(thread_id=thread_id, participant_id=AGENT, tenant_key=tenant)
    return svc, tenant, thread_id


async def _seen(db_session, tenant: str, thread_id: str) -> datetime | None:
    with tenant_session_context(db_session, tenant):
        return (
            await db_session.execute(
                select(CommParticipant.last_seen_at)
                .where(
                    CommParticipant.tenant_key == tenant,
                    CommParticipant.thread_id == thread_id,
                    CommParticipant.participant_id == AGENT,
                )
                .execution_options(populate_existing=True)
            )
        ).scalar_one()


async def _set_seen(db_session, tenant: str, thread_id: str, value: datetime | None) -> None:
    with tenant_session_context(db_session, tenant):
        await db_session.execute(
            update(CommParticipant)
            .where(
                CommParticipant.tenant_key == tenant,
                CommParticipant.thread_id == thread_id,
                CommParticipant.participant_id == AGENT,
            )
            .values(last_seen_at=value)
        )


async def _read(svc, tenant: str, tid: str, **kwargs):
    return await svc.get_thread_history(thread_id=tid, as_participant=AGENT, tenant_key=tenant, **kwargs)


async def test_second_read_a_second_later_changes_nothing(db_manager, db_session):
    svc, tenant, tid = await _setup(db_manager, db_session, "twice")

    await _read(svc, tenant, tid)
    after_first = await _seen(db_session, tenant, tid)
    await asyncio.sleep(1)
    await _read(svc, tenant, tid)

    assert await _seen(db_session, tenant, tid) == after_first


async def test_read_inside_the_interval_leaves_an_older_stamp_alone(db_manager, db_session):
    svc, tenant, tid = await _setup(db_manager, db_session, "inside")
    stamp = datetime.now(UTC) - timedelta(seconds=30)
    await _set_seen(db_session, tenant, tid, stamp)

    await _read(svc, tenant, tid)

    assert await _seen(db_session, tenant, tid) == stamp


async def test_mark_read_inside_the_interval_is_throttled_too(db_manager, db_session):
    svc, tenant, tid = await _setup(db_manager, db_session, "markread")
    stamp = datetime.now(UTC) - timedelta(seconds=30)
    await _set_seen(db_session, tenant, tid, stamp)

    await _read(svc, tenant, tid, unread_only=True, mark_read=True)

    assert await _seen(db_session, tenant, tid) == stamp


async def test_read_after_the_interval_stamps_again(db_manager, db_session):
    svc, tenant, tid = await _setup(db_manager, db_session, "after")
    await _set_seen(db_session, tenant, tid, datetime.now(UTC) - timedelta(seconds=61))

    await _read(svc, tenant, tid)

    assert await _seen(db_session, tenant, tid) > datetime.now(UTC) - timedelta(seconds=10)


async def test_never_seen_participant_is_stamped_by_the_first_read(db_manager, db_session):
    svc, tenant, tid = await _setup(db_manager, db_session, "null")
    await _set_seen(db_session, tenant, tid, None)

    await _read(svc, tenant, tid)

    assert await _seen(db_session, tenant, tid) is not None


async def test_post_right_after_a_read_still_stamps_immediately(db_manager, db_session):
    svc, tenant, tid = await _setup(db_manager, db_session, "post")
    stamp = datetime.now(UTC) - timedelta(seconds=30)
    await _set_seen(db_session, tenant, tid, stamp)

    await _read(svc, tenant, tid)
    assert await _seen(db_session, tenant, tid) == stamp

    await svc.post_to_thread(thread_id=tid, content="hello", from_agent=AGENT, tenant_key=tenant)

    assert await _seen(db_session, tenant, tid) > datetime.now(UTC) - timedelta(seconds=10)
