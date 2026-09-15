# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import inspect
import uuid

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.auth import User
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


def _tk(suffix: str) -> str:
    return f"tk_fe9546_{suffix}_{uuid.uuid4().hex[:8]}"


def _service(db_manager, db_session) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed(db_session, tenant: str) -> None:
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)


async def _seed_with_operator(db_session, tenant: str) -> str:
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
        operator = User(
            id=str(uuid.uuid4()),
            tenant_key=tenant,
            username=f"op_{uuid.uuid4().hex[:8]}",
            email=f"op_{uuid.uuid4().hex[:8]}@example.test",
            password_hash="x",
            full_name="Sam Rivera",
            is_active=True,
        )
        db_session.add(operator)
        await db_session.flush()
    return operator.id


async def _thread(svc: CommThreadService, tenant: str) -> str:
    created = await svc.create_thread(subject="approvals", creator_id="orchestrator", tenant_key=tenant)
    thread_id = created["thread_id"]
    await svc.join_thread(thread_id=thread_id, participant_id="orchestrator", display_name="EM", tenant_key=tenant)
    await svc.join_thread(thread_id=thread_id, participant_id="CI2", display_name="CI2", tenant_key=tenant)
    return thread_id




async def test_post_to_thread_returns_the_directed_recipient(db_manager, db_session):
    tenant = _tk("directed")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread(svc, tenant)

    result = await svc.post_to_thread(
        thread_id=thread_id,
        content="pick this up",
        from_agent="orchestrator",
        to_participant="CI2",
        requires_action=True,
        tenant_key=tenant,
    )

    assert result["to_participant"] == "CI2"


async def test_post_to_thread_resolves_the_user_alias_before_returning_it(db_manager, db_session):
    tenant = _tk("alias")
    real_user_id = await _seed_with_operator(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread(svc, tenant)

    result = await svc.post_to_thread(
        thread_id=thread_id,
        content="need your sign-off",
        from_agent="orchestrator",
        to_participant="user",
        requires_action=True,
        tenant_key=tenant,
    )

    assert result["to_participant"] == real_user_id
    assert result["to_participant"] != "user"


async def test_a_broadcast_returns_no_recipient(db_manager, db_session):
    tenant = _tk("broadcast")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread(svc, tenant)

    result = await svc.post_to_thread(
        thread_id=thread_id,
        content="status update for everyone",
        from_agent="orchestrator",
        requires_action=False,
        tenant_key=tenant,
    )

    assert result.get("to_participant") is None




async def test_thread_message_event_carries_to_participant_additively():
    from api.endpoints._comm_ws import broadcast_thread_message

    sent: list[dict] = []

    class _Manager:
        async def broadcast_event_to_tenant(self, tenant_key, event):
            sent.append(event)

    await broadcast_thread_message(
        _Manager(),
        "tk_x",
        thread_id="t1",
        message_id="m1",
        from_agent_id="orchestrator",
        from_display_name="EM",
        content="pick this up",
        message_type="direct",
        priority="normal",
        requires_action=True,
        project_id=None,
        to_participant="CI2",
    )
    assert sent[0]["data"]["to_participant"] == "CI2"

    sent.clear()
    await broadcast_thread_message(
        _Manager(),
        "tk_x",
        thread_id="t1",
        message_id="m2",
        from_agent_id="orchestrator",
        from_display_name="EM",
        content="status for everyone",
        message_type="broadcast",
        priority="normal",
        requires_action=False,
        project_id=None,
    )
    assert sent[0]["data"]["to_participant"] is None


def test_to_participant_is_optional_and_defaults_to_none():
    from api.endpoints._comm_ws import broadcast_thread_message

    assert inspect.signature(broadcast_thread_message).parameters["to_participant"].default is None
