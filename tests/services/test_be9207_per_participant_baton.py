# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.repositories.comm_thread_repository import CommThreadRepository
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _comm(db_session) -> CommThreadService:
    return CommThreadService(db_manager=None, tenant_manager=TenantManager(), session=db_session)


async def _seed_cht(db_session, tenant_key: str) -> None:
    from giljo_mcp.database import tenant_session_context

    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)


async def _directed_thread(comm, tenant, *, to_participant):
    thread = await comm.create_thread(subject="coord", creator_id="EM", tenant_key=tenant)
    tid = thread["thread_id"]
    await comm.join_thread(thread_id=tid, participant_id=to_participant, tenant_key=tenant)
    await comm.post_to_thread(
        thread_id=tid,
        content="please handle",
        from_agent="EM",
        to_participant=to_participant,
        requires_action=True,
        tenant_key=tenant,
    )
    return tid


async def test_pending_directed_query_returns_thread_for_addressee_only(db_session):
    tenant = TenantManager.generate_tenant_key()
    await _seed_cht(db_session, tenant)
    comm = _comm(db_session)
    repo = CommThreadRepository()

    tid = await _directed_thread(comm, tenant, to_participant="lane-A")
    await comm.join_thread(thread_id=tid, participant_id="lane-B", tenant_key=tenant)

    from giljo_mcp.database import tenant_session_context

    with tenant_session_context(db_session, tenant):
        for_a = await repo.get_threads_with_pending_directed_action(db_session, tenant, "lane-A")
        for_b = await repo.get_threads_with_pending_directed_action(db_session, tenant, "lane-B")
    assert [t.id for t in for_a] == [tid]
    assert for_b == []


async def test_ack_resolves_pending_directive(db_session):
    tenant = TenantManager.generate_tenant_key()
    await _seed_cht(db_session, tenant)
    comm = _comm(db_session)

    tid = await _directed_thread(comm, tenant, to_participant="lane-A")
    assert tid in {t["thread_id"] for t in (await comm.get_my_turn(agent_id="lane-A", tenant_key=tenant))["threads"]}

    await comm.get_thread_history(thread_id=tid, as_participant="lane-A", mark_read=True, tenant_key=tenant)

    turn = await comm.get_my_turn(agent_id="lane-A", tenant_key=tenant)
    assert turn["directed_action"] == []
    assert tid not in {t["thread_id"] for t in turn["threads"]}


async def test_pending_directive_is_tenant_isolated(db_session):
    t1 = TenantManager.generate_tenant_key()
    t2 = TenantManager.generate_tenant_key()
    await _seed_cht(db_session, t1)
    await _seed_cht(db_session, t2)
    comm = _comm(db_session)

    tid1 = await _directed_thread(comm, t1, to_participant="lane-A")
    tid2 = await _directed_thread(comm, t2, to_participant="lane-A")

    t1_turn = await comm.get_my_turn(agent_id="lane-A", tenant_key=t1)
    t2_turn = await comm.get_my_turn(agent_id="lane-A", tenant_key=t2)
    assert _directed_ids(t1_turn) == {tid1}
    assert _directed_ids(t2_turn) == {tid2}


async def test_informational_directed_post_is_not_pending(db_session):
    tenant = TenantManager.generate_tenant_key()
    await _seed_cht(db_session, tenant)
    comm = _comm(db_session)

    thread = await comm.create_thread(subject="fyi", creator_id="EM", tenant_key=tenant)
    tid = thread["thread_id"]
    await comm.join_thread(thread_id=tid, participant_id="lane-A", tenant_key=tenant)
    await comm.post_to_thread(
        thread_id=tid,
        content="just so you know",
        from_agent="EM",
        to_participant="lane-A",
        requires_action=False,
        tenant_key=tenant,
    )

    turn = await comm.get_my_turn(agent_id="lane-A", tenant_key=tenant)
    assert tid not in _directed_ids(turn)


def _directed_ids(turn) -> set[str]:
    return {d["thread_id"] for d in turn["directed_action"]}
