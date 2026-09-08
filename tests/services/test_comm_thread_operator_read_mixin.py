# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""FE-9586 — the operator's read watermark, which did not exist.

THE DEFECT THIS PINS. ``comm_participants.last_read_at`` is the cursor every
"is there anything new" answer keys on, and until now only AGENTS advanced it
(``get_thread_history(as_participant=..., mark_read=True)`` over MCP). The
dashboard never did: ``commHubStore.markThreadRead()`` zeroes an in-memory
counter and persists nothing, and ``GET /api/v1/threads/{id}`` passes neither
``as_participant`` nor ``mark_read``. So the operator had no watermark at all,
and the card ``unread`` flag (BE-9289b) was stuck TRUE forever once anything was
posted -- not coarse, not conservative, simply wrong.

That is also why a mention could not be state-backed. "The operator read it" was
a fact the server had never been told, so no projection could ask about it. This
is the mechanism half of FE-9586; the banner family that reads these facts is the
other half and lands separately.

WHY A SERVICE TEST AND NOT ONLY AN API TEST: the write must go through the SAME
path agents already use, so the operator's watermark and an agent's are the same
object rather than two spellings that can drift. Pinning it here is pinning that
choice; ``tests/api`` covers the REST shim over it.

Parallel-safe: real DB via the rollback-isolated ``db_session`` fixture, no
module-level mutable state, each test owns its setup, every query tenant-scoped.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.tasks import Message
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _tk(suffix: str) -> str:
    return f"tk_fe9586_{suffix}_{uuid.uuid4().hex[:8]}"


def _service(db_manager, db_session) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed(db_session, tenant: str) -> None:
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)


async def _card(svc: CommThreadService, *, thread_id: str, viewer: str, tenant: str) -> dict:
    """The viewer's own card facts for one thread -- the surface the defect showed on."""
    listed = await svc.list_threads(viewer_id=viewer, tenant_key=tenant)
    return next(t for t in listed["threads"] if t["thread_id"] == thread_id)


async def _thread_with_one_post(svc: CommThreadService, tenant: str, *, content: str = "hi") -> str:
    thread = await svc.create_thread(subject="t", creator_id="agent-orch", tenant_key=tenant)
    await svc.post_to_thread(thread_id=thread["thread_id"], content=content, from_agent="agent-a", tenant_key=tenant)
    return thread["thread_id"]


async def test_the_operator_has_no_watermark_until_something_writes_one(db_manager, db_session):
    """The motivation, pinned so it cannot silently change: reading a thread through
    the ordinary history read does NOT clear the card. This is the behaviour that made
    ``unread`` stuck-on -- it stays true here BY DESIGN, because the read is not the
    signal. Only an explicit mark is."""
    tenant = _tk("stuck")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _thread_with_one_post(svc, tenant)

    await svc.get_thread_history(thread_id=tid, tenant_key=tenant)

    assert (await _card(svc, thread_id=tid, viewer="operator-1", tenant=tenant))["unread"] is True


async def test_marking_read_as_the_operator_clears_the_card_unread_flag(db_manager, db_session):
    """The fix. One call, and the operator's own card stops claiming there is something
    new -- through the same cursor an agent's mark_read advances."""
    tenant = _tk("clear")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _thread_with_one_post(svc, tenant)
    assert (await _card(svc, thread_id=tid, viewer="operator-1", tenant=tenant))["unread"] is True

    await svc.mark_thread_read_for_user(thread_id=tid, user_id="operator-1", display_name="Patrik", tenant_key=tenant)

    assert (await _card(svc, thread_id=tid, viewer="operator-1", tenant=tenant))["unread"] is False


async def test_marking_read_registers_the_operator_in_the_participant_directory(db_manager, db_session):
    """By design: reading-with-a-watermark IS participation, and the directory is
    left UNFILTERED -- "the operator has looked at this thread" is true information.
    A watermark with no participant row is not possible anyway: the cursor LIVES on
    that row."""
    tenant = _tk("directory")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _thread_with_one_post(svc, tenant)

    await svc.mark_thread_read_for_user(thread_id=tid, user_id="operator-1", display_name="Patrik", tenant_key=tenant)

    listed = await svc.list_participants(thread_id=tid, tenant_key=tenant)
    mine = next(p for p in listed["participants"] if p["participant_id"] == "operator-1")
    assert mine["participant_type"] == "user"


async def test_marking_read_is_per_viewer(db_manager, db_session):
    """One operator's read must never clear another viewer's card. The cursor is per
    participant row, and this is the assertion that fails first if a write ever
    loses its correlation."""
    tenant = _tk("perviewer")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _thread_with_one_post(svc, tenant)

    await svc.mark_thread_read_for_user(thread_id=tid, user_id="operator-1", display_name="Patrik", tenant_key=tenant)

    assert (await _card(svc, thread_id=tid, viewer="operator-1", tenant=tenant))["unread"] is False
    assert (await _card(svc, thread_id=tid, viewer="operator-2", tenant=tenant))["unread"] is True


async def test_marking_read_twice_is_idempotent(db_manager, db_session):
    """Write-on-open fires on every open, so the second call must be a no-op rather
    than a duplicate participant row or an error."""
    tenant = _tk("idempotent")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _thread_with_one_post(svc, tenant)

    await svc.mark_thread_read_for_user(thread_id=tid, user_id="operator-1", display_name="Patrik", tenant_key=tenant)
    await svc.mark_thread_read_for_user(thread_id=tid, user_id="operator-1", display_name="Patrik", tenant_key=tenant)

    listed = await svc.list_participants(thread_id=tid, tenant_key=tenant)
    assert len([p for p in listed["participants"] if p["participant_id"] == "operator-1"]) == 1
    assert (await _card(svc, thread_id=tid, viewer="operator-1", tenant=tenant))["unread"] is False


async def _backdate(db_session, tenant: str, message_id: str, *, seconds: int) -> None:
    """Push one post into the past.

    Posts made inside one transaction share a ``created_at`` -- ``server_default=func.now()``
    and Postgres ``now()`` is the TRANSACTION timestamp -- which production never does,
    since each post commits on its own. Without this the watermark and the next post tie,
    and ``unread``'s strict ``created_at > last_read`` reads the newer post as already
    read. Same artifact and same remedy as tests/repositories/test_comm_thread_list_enrichment_mixin.py.

    Noted rather than papered over: a post sharing an instant with the watermark IS
    treated as read by BE-9289b's strict comparison. That is pre-existing, it is
    unreachable in production for this reason, and changing it is not this project's
    business (museum rule -- no reproduced incident).
    """
    with tenant_session_context(db_session, tenant):
        await db_session.execute(
            update(Message)
            .where(Message.id == message_id, Message.tenant_key == tenant)
            .values(created_at=datetime.now(UTC) - timedelta(seconds=seconds))
        )
        await db_session.flush()


async def test_a_post_after_the_read_is_unread_again(db_manager, db_session):
    """It is a CURSOR, not a seen-it flag. A banner family projecting off this would be
    permanently silent if a read latched -- so this is the test that proves the fix
    cannot over-clear."""
    tenant = _tk("cursor")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread = await svc.create_thread(subject="t", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]
    first = await svc.post_to_thread(thread_id=tid, content="hi", from_agent="agent-a", tenant_key=tenant)
    # The read must land AFTER the first post and BEFORE the second in real time.
    await _backdate(db_session, tenant, first["message_id"], seconds=60)

    await svc.mark_thread_read_for_user(thread_id=tid, user_id="operator-1", display_name="Patrik", tenant_key=tenant)
    assert (await _card(svc, thread_id=tid, viewer="operator-1", tenant=tenant))["unread"] is False

    await svc.post_to_thread(thread_id=tid, content="something new", from_agent="agent-b", tenant_key=tenant)

    assert (await _card(svc, thread_id=tid, viewer="operator-1", tenant=tenant))["unread"] is True


async def test_marking_read_does_not_leak_across_tenants(db_manager, db_session):
    """Same user id, two tenants: a read in one must not clear the other."""
    tenant_a = _tk("iso_a")
    tenant_b = _tk("iso_b")
    await _seed(db_session, tenant_a)
    await _seed(db_session, tenant_b)
    svc = _service(db_manager, db_session)
    tid_a = await _thread_with_one_post(svc, tenant_a)
    tid_b = await _thread_with_one_post(svc, tenant_b)

    await svc.mark_thread_read_for_user(
        thread_id=tid_a, user_id="operator-1", display_name="Patrik", tenant_key=tenant_a
    )

    assert (await _card(svc, thread_id=tid_a, viewer="operator-1", tenant=tenant_a))["unread"] is False
    assert (await _card(svc, thread_id=tid_b, viewer="operator-1", tenant=tenant_b))["unread"] is True
