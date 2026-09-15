# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

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


async def _thread(comm, tenant, *, joiners=()):
    created = await comm.create_thread(subject="baton", creator_id="EM", tenant_key=tenant)
    tid = created["thread_id"]
    for agent in joiners:
        await comm.join_thread(thread_id=tid, participant_id=agent, tenant_key=tenant)
    return tid


def _ids(turn) -> set[str]:
    return {t["thread_id"] for t in turn["threads"]}




async def test_a_terminal_thread_drops_off_both_baton_arms(db_session):
    tenant = TenantManager.generate_tenant_key()
    await _seed_cht(db_session, tenant)
    comm = _comm(db_session)

    named = await _thread(comm, tenant, joiners=("lane-A",))
    broadcast = await _thread(comm, tenant, joiners=("lane-A",))
    await comm.pass_baton(thread_id=named, to="lane-A", tenant_key=tenant)
    await comm.pass_baton(thread_id=broadcast, to="all", tenant_key=tenant)

    assert {named, broadcast} <= _ids(await comm.get_my_turn(agent_id="lane-A", tenant_key=tenant))

    for tid in (named, broadcast):
        await comm.post_to_thread(
            thread_id=tid, content="done", from_agent="EM", set_status="resolved", tenant_key=tenant
        )

    after = await comm.get_my_turn(agent_id="lane-A", tenant_key=tenant)
    assert _ids(after).isdisjoint({named, broadcast})
    assert after["count"] == 0




async def test_b_all_baton_reaches_participants_and_not_strangers(db_session):
    tenant = TenantManager.generate_tenant_key()
    await _seed_cht(db_session, tenant)
    comm = _comm(db_session)

    tid = await _thread(comm, tenant, joiners=("lane-A",))
    await comm.pass_baton(thread_id=tid, to="all", tenant_key=tenant)

    assert tid in _ids(await comm.get_my_turn(agent_id="lane-A", tenant_key=tenant))
    assert tid not in _ids(await comm.get_my_turn(agent_id="lane-Z", tenant_key=tenant))


async def test_b_does_not_narrow_the_named_arm(db_session):
    tenant = TenantManager.generate_tenant_key()
    await _seed_cht(db_session, tenant)
    comm = _comm(db_session)

    tid = await _thread(comm, tenant)
    from giljo_mcp.database import tenant_session_context

    with tenant_session_context(db_session, tenant):
        await comm._repo.set_next_action_owner(db_session, tenant, tid, "never-joined")

    assert tid in _ids(await comm.get_my_turn(agent_id="never-joined", tenant_key=tenant))


async def test_b_is_tenant_scoped(db_session):
    t1, t2 = TenantManager.generate_tenant_key(), TenantManager.generate_tenant_key()
    await _seed_cht(db_session, t1)
    await _seed_cht(db_session, t2)
    comm = _comm(db_session)

    tid = await _thread(comm, t1, joiners=("lane-A",))
    await comm.pass_baton(thread_id=tid, to="all", tenant_key=t1)

    assert tid in _ids(await comm.get_my_turn(agent_id="lane-A", tenant_key=t1))
    assert (await comm.get_my_turn(agent_id="lane-A", tenant_key=t2))["count"] == 0


