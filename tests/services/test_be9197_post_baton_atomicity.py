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
    return f"tk_be9197_{suffix}"


def _service(db_manager, db_session) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed(db_session, tenant: str) -> None:
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)


async def test_post_with_baton_moves_owner_in_result_and_db(db_manager, db_session):
    tenant = _tk("move")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="hand-off", creator_id="alpha", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="beta", tenant_key=tenant)

    result = await svc.post_to_thread(
        thread_id=tid, content="over to you", from_agent="alpha", pass_baton_to="beta", tenant_key=tenant
    )
    assert result["baton_passed"] is True
    assert result["next_action_owner"] == "beta"
    with tenant_session_context(db_session, tenant):
        row = (await db_session.execute(select(CommThread).where(CommThread.id == tid))).scalar_one()
        assert row.next_action_owner == "beta"


async def test_none_and_omitted_leave_owner_untouched(db_manager, db_session):
    tenant = _tk("none")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="keep it", creator_id="alpha", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="beta", tenant_key=tenant)

    suppressed = await svc.post_to_thread(
        thread_id=tid,
        content="directed action, baton kept",
        from_agent="alpha",
        to_participant="beta",
        requires_action=True,
        pass_baton_to="none",
        tenant_key=tenant,
    )
    assert suppressed["baton_passed"] is False
    assert suppressed["next_action_owner"] == "alpha"

    omitted = await svc.post_to_thread(
        thread_id=tid,
        content="directed action, no param",
        from_agent="alpha",
        to_participant="beta",
        requires_action=True,
        tenant_key=tenant,
    )
    assert omitted["baton_passed"] is False
    assert omitted["next_action_owner"] == "alpha"


async def test_failed_post_rolls_baton_back(db_manager, monkeypatch):
    tenant = _tk("rollback")
    async with db_manager.get_session_async(tenant_key=tenant) as seed_session:
        with tenant_session_context(seed_session, tenant):
            await ensure_default_types_seeded(seed_session, tenant)
            await seed_session.commit()

    svc = CommThreadService(db_manager, TenantManager())
    try:
        thread = await svc.create_thread(subject="atomic", creator_id="alpha", tenant_key=tenant)
        tid = thread["thread_id"]
        await svc.join_thread(thread_id=tid, participant_id="beta", tenant_key=tenant)

        async def _explode(self, *args, **kwargs):
            raise RuntimeError("injected persist failure (BE-9197 atomicity test)")

        monkeypatch.setattr(CommThreadRepository, "persist_thread_message", _explode)

        with pytest.raises(RuntimeError, match="injected persist failure"):
            await svc.post_to_thread(
                thread_id=tid, content="never lands", from_agent="alpha", pass_baton_to="beta", tenant_key=tenant
            )
        monkeypatch.undo()

        async with db_manager.get_session_async(tenant_key=tenant) as check:
            with tenant_session_context(check, tenant):
                row = (await check.execute(select(CommThread).where(CommThread.id == tid))).scalar_one()
                assert row.next_action_owner == "alpha"
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
