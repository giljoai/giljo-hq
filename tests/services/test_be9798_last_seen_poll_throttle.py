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

AGENT = "agent-poller"


def _tk(suffix: str) -> str:
    return f"tk_be9798_{suffix}_{uuid.uuid4().hex[:8]}"


async def _setup(db_manager, db_session, suffix: str):
    tenant = _tk(suffix)
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
    svc = CommThreadService(db_manager, TenantManager(), session=db_session)
    thread_id = (await svc.create_thread(subject="poll", creator_id="agent-orch", tenant_key=tenant))["thread_id"]
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


async def test_second_poll_a_second_later_changes_nothing(db_manager, db_session):
    svc, tenant, tid = await _setup(db_manager, db_session, "twice")

    await svc.get_my_turn(agent_id=AGENT, tenant_key=tenant)
    after_first = await _seen(db_session, tenant, tid)
    await asyncio.sleep(1)
    await svc.get_my_turn(agent_id=AGENT, tenant_key=tenant)

    assert await _seen(db_session, tenant, tid) == after_first


async def test_poll_inside_the_interval_leaves_an_older_stamp_alone(db_manager, db_session):
    svc, tenant, tid = await _setup(db_manager, db_session, "inside")
    stamp = datetime.now(UTC) - timedelta(seconds=30)
    await _set_seen(db_session, tenant, tid, stamp)

    await svc.get_my_turn(agent_id=AGENT, tenant_key=tenant)

    assert await _seen(db_session, tenant, tid) == stamp


async def test_poll_after_the_interval_stamps_again(db_manager, db_session):
    svc, tenant, tid = await _setup(db_manager, db_session, "after")
    stale = datetime.now(UTC) - timedelta(seconds=61)
    await _set_seen(db_session, tenant, tid, stale)

    await svc.get_my_turn(agent_id=AGENT, tenant_key=tenant)

    assert await _seen(db_session, tenant, tid) > datetime.now(UTC) - timedelta(seconds=10)


async def test_never_seen_participant_is_stamped_by_the_first_poll(db_manager, db_session):
    svc, tenant, tid = await _setup(db_manager, db_session, "null")
    await _set_seen(db_session, tenant, tid, None)

    await svc.get_my_turn(agent_id=AGENT, tenant_key=tenant)

    assert await _seen(db_session, tenant, tid) is not None


async def test_post_right_after_a_poll_still_stamps_immediately(db_manager, db_session):
    svc, tenant, tid = await _setup(db_manager, db_session, "post")
    stamp = datetime.now(UTC) - timedelta(seconds=30)
    await _set_seen(db_session, tenant, tid, stamp)

    await svc.get_my_turn(agent_id=AGENT, tenant_key=tenant)
    assert await _seen(db_session, tenant, tid) == stamp

    await svc.post_to_thread(thread_id=tid, content="hello", from_agent=AGENT, tenant_key=tenant)

    assert await _seen(db_session, tenant, tid) > datetime.now(UTC) - timedelta(seconds=10)
