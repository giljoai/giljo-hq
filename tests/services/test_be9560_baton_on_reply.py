# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from sqlalchemy import delete, func, select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.comm import CommParticipant, CommThread
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.models.tasks import Message
from giljo_mcp.repositories.comm_thread_repository import CommThreadRepository
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _tk(suffix: str) -> str:
    return f"tk_be9560_{suffix}"


def _service(db_manager, db_session) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed(db_session, tenant: str) -> None:
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)


async def test_broadcast_reply_clears_operators_own_baton(db_manager, db_session):
    tenant = _tk("clear_own")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(
        subject="operator holds it", creator_id="op-1", creator_type="user", tenant_key=tenant
    )
    tid = thread["thread_id"]
    assert thread["next_action_owner"] == "op-1"

    result = await svc.post_to_thread(
        thread_id=tid,
        content="answered, no addressee",
        as_user=True,
        user_id="op-1",
        clear_baton_on_broadcast_reply=True,
        tenant_key=tenant,
    )
    assert result["baton_cleared"] is True
    assert result["baton_passed"] is False
    assert result["next_action_owner"] is None
    with tenant_session_context(db_session, tenant):
        row = (await db_session.execute(select(CommThread).where(CommThread.id == tid))).scalar_one()
        assert row.next_action_owner is None


async def test_broadcast_reply_clears_all_baton(db_manager, db_session):
    tenant = _tk("clear_all")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="open turn", creator_id="alpha", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.pass_baton(thread_id=tid, to="all", from_agent="alpha", tenant_key=tenant)

    result = await svc.post_to_thread(
        thread_id=tid,
        content="operator picks it up",
        as_user=True,
        user_id="op-1",
        clear_baton_on_broadcast_reply=True,
        tenant_key=tenant,
    )
    assert result["baton_cleared"] is True
    assert result["next_action_owner"] is None


async def test_broadcast_reply_leaves_another_agents_baton_untouched(db_manager, db_session):
    tenant = _tk("no_steal")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="agent mid-task", creator_id="alpha", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="beta", tenant_key=tenant)
    await svc.pass_baton(thread_id=tid, to="beta", from_agent="alpha", tenant_key=tenant)

    result = await svc.post_to_thread(
        thread_id=tid,
        content="FYI, not for beta",
        as_user=True,
        user_id="op-1",
        clear_baton_on_broadcast_reply=True,
        tenant_key=tenant,
    )
    assert result["baton_cleared"] is False
    assert result["next_action_owner"] == "beta"
    with tenant_session_context(db_session, tenant):
        row = (await db_session.execute(select(CommThread).where(CommThread.id == tid))).scalar_one()
        assert row.next_action_owner == "beta"


async def test_directed_reply_hands_baton_to_addressee(db_manager, db_session):
    tenant = _tk("directed")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="dm reply", creator_id="alpha", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="beta", tenant_key=tenant)
    await svc.join_thread(thread_id=tid, participant_id="gamma", tenant_key=tenant)
    await svc.pass_baton(thread_id=tid, to="beta", from_agent="alpha", tenant_key=tenant)

    result = await svc.post_to_thread(
        thread_id=tid,
        content="over to gamma",
        as_user=True,
        user_id="op-1",
        to_participant="gamma",
        pass_baton_to="gamma",
        clear_baton_on_broadcast_reply=True,
        tenant_key=tenant,
    )
    assert result["baton_passed"] is True
    assert result["baton_cleared"] is False
    assert result["next_action_owner"] == "gamma"


async def test_terminal_thread_still_applies_the_mirror_rule(db_manager, db_session):
    tenant = _tk("terminal")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="wrapping up", creator_id="op-1", creator_type="user", tenant_key=tenant)
    tid = thread["thread_id"]

    result = await svc.post_to_thread(
        thread_id=tid,
        content="closing this out",
        as_user=True,
        user_id="op-1",
        set_status="closed",
        clear_baton_on_broadcast_reply=True,
        tenant_key=tenant,
    )
    assert result["baton_cleared"] is True
    assert result["next_action_owner"] is None
    with tenant_session_context(db_session, tenant):
        row = (await db_session.execute(select(CommThread).where(CommThread.id == tid))).scalar_one()
        assert row.status == "closed"
        assert row.next_action_owner is None


async def test_no_owner_and_no_poster_identity_never_reports_a_clear(db_manager, db_session):
    tenant = _tk("no_owner_no_poster")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="nobody holds it", tenant_key=tenant)
    tid = thread["thread_id"]
    assert thread["next_action_owner"] is None

    result = await svc.post_to_thread(
        thread_id=tid,
        content="anonymous broadcast",
        from_agent="alpha",
        clear_baton_on_broadcast_reply=True,
        tenant_key=tenant,
    )
    assert result["baton_cleared"] is False
    assert result["next_action_owner"] is None


async def test_flag_omitted_broadcast_stays_untouched(db_manager, db_session):
    tenant = _tk("omitted")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="no opt-in", creator_id="op-1", creator_type="user", tenant_key=tenant)
    tid = thread["thread_id"]

    result = await svc.post_to_thread(
        thread_id=tid,
        content="plain broadcast",
        as_user=True,
        user_id="op-1",
        tenant_key=tenant,
    )
    assert result["baton_cleared"] is False
    assert result["next_action_owner"] == "op-1"


async def test_failed_broadcast_clear_rolls_back(db_manager, monkeypatch):
    tenant = _tk("clear_rollback")
    async with db_manager.get_session_async(tenant_key=tenant) as seed_session:
        with tenant_session_context(seed_session, tenant):
            await ensure_default_types_seeded(seed_session, tenant)
            await seed_session.commit()

    svc = CommThreadService(db_manager, TenantManager())
    try:
        thread = await svc.create_thread(
            subject="atomic clear", creator_id="op-1", creator_type="user", tenant_key=tenant
        )
        tid = thread["thread_id"]

        async def _explode(self, *args, **kwargs):
            raise RuntimeError("injected persist failure (BE-9560 clear atomicity test)")

        monkeypatch.setattr(CommThreadRepository, "persist_thread_message", _explode)

        with pytest.raises(RuntimeError, match="injected persist failure"):
            await svc.post_to_thread(
                thread_id=tid,
                content="never lands",
                as_user=True,
                user_id="op-1",
                clear_baton_on_broadcast_reply=True,
                tenant_key=tenant,
            )
        monkeypatch.undo()

        async with db_manager.get_session_async(tenant_key=tenant) as check:
            with tenant_session_context(check, tenant):
                row = (await check.execute(select(CommThread).where(CommThread.id == tid))).scalar_one()
                assert row.next_action_owner == "op-1"
                msg_count = (
                    await check.execute(select(func.count(Message.id)).where(Message.thread_id == tid))
                ).scalar_one()
                assert msg_count == 0
    finally:
        monkeypatch.undo()
        async with db_manager.get_session_async(tenant_key=tenant) as cleanup:
            with tenant_session_context(cleanup, tenant):
                await cleanup.execute(delete(Message).where(Message.tenant_key == tenant))
                await cleanup.execute(delete(CommParticipant).where(CommParticipant.tenant_key == tenant))
                await cleanup.execute(delete(CommThread).where(CommThread.tenant_key == tenant))
                await cleanup.execute(delete(TaxonomyType).where(TaxonomyType.tenant_key == tenant))
                await cleanup.commit()
