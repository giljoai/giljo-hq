# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Service-layer tests for BE-9560 -- baton-on-reply.

Operator-reported 2026-09-02: replying in the dashboard never clears your turn, so
the "Waiting on you" banner can outlive the reply. Root cause: the REST
``post_to_thread`` route forwarded no baton at all, while the MCP boundary
auto-passes on a directed action-request -- so an agent's reply always resolves the
turn and an operator's REST reply never did.

Operator ruling 2026-09-02 (option (a) -- "make answering mean answering"):
on a REST reply, a directed reply (``to_participant`` resolves) hands the baton to
that addressee (screened exactly like the MCP auto-pass); a broadcast reply clears
the baton instead of leaving it to the manual raised-hand control.

``CommThreadService.post_to_thread`` gains ``clear_baton_on_broadcast_reply``: a
second, REST-only opt-in, additive to the BE-9197 ``pass_baton_to`` contract and
never set by the MCP wrapper (see
``tests/integration/test_be9197_post_with_baton_mcp_boundary.py::
test_broadcast_without_param_unchanged``, which pins the MCP door's broadcast
behaviour with the flag never passed -- it stays green, unmodified, proving no
drift).

Corrected record: the planning text also hypothesised that BE-9292a addressee
screening becomes reachable from REST "for the first time" via this fix. Verified
FALSE by call path: ``post_target_rejection`` already screens ``to_participant``
for a shadowed display name UNCONDITIONALLY (before its own
``if not pass_baton_to: return None`` guard), so
``tests/api/test_comm_threads_endpoints.py::
test_post_to_a_display_label_is_refused_cleanly_not_a_500`` already exercised that
refusal via REST before this project, and still does, unmodified by this diff.
What newly reaches REST is only the actual baton WRITE (``next_action_owner``
moving/clearing) -- the ``also_reachable=(author_id, to_participant)`` exemption in
``baton_target_rejection`` means a target identical to ``to_participant`` (the
auto-pass shape this fix mirrors) can never trip ``BATON_TARGET_NOT_A_PARTICIPANT``
either, so no *new* rejection class becomes reachable, only the write.
"""

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
    """RED-FIRST layer: the operator (user_id) holds the baton; a broadcast REST-shaped
    reply must clear it -- this is the exact banner-outlives-the-reply repro."""
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
    """A shared 'all' baton is also cleared -- the operator answering IS one of the
    'anyone' the open turn was waiting on."""
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
    """Guard against the obvious regression: the operator merely commenting on a
    thread must NEVER silently cancel some OTHER agent's still-open turn."""
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
    """A directed REST-shaped reply (to_participant resolves) hands the baton to that
    addressee -- unconditionally, exactly like the MCP auto-pass, regardless of who
    held it before."""
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
        clear_baton_on_broadcast_reply=True,  # both flags present, as REST always sends them
        tenant_key=tenant,
    )
    assert result["baton_passed"] is True
    assert result["baton_cleared"] is False
    assert result["next_action_owner"] == "gamma"


async def test_terminal_thread_still_applies_the_mirror_rule(db_manager, db_session):
    """No special-casing for a terminal thread -- matches the existing precedent that
    ``post_to_thread`` never gates the baton write on thread status (``set_status`` and
    the BE-9197 hand-off already run unconditionally together)."""
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
    """Refutation guard: an omitted poster identity (user_id=None) must never
    coincide with an already-unheld baton (next_action_owner=None) and be read as
    "the poster holds it" -- ``None in (None, "all")`` is a real Python trap the
    helper must not fall into."""
    tenant = _tk("no_owner_no_poster")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="nobody holds it", tenant_key=tenant)  # no creator_id -> owner stays None
    tid = thread["thread_id"]
    assert thread["next_action_owner"] is None

    result = await svc.post_to_thread(
        thread_id=tid,
        content="anonymous broadcast",
        from_agent="alpha",  # NOT as_user -- user_id stays None, the exact trap case
        clear_baton_on_broadcast_reply=True,
        tenant_key=tenant,
    )
    assert result["baton_cleared"] is False
    assert result["next_action_owner"] is None


async def test_flag_omitted_broadcast_stays_untouched(db_manager, db_session):
    """The MCP-parity default: without the opt-in, a broadcast leaves the baton alone
    even when the poster is the current owner -- identical to pre-BE-9560 behavior."""
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
    """Same BE-9197 atomicity guarantee extended to the clear: the clear is written
    BEFORE the persist, in the same transaction, so a persist failure rolls it back
    too. Runs the real db_manager session path (the service owns the transaction),
    not the savepoint-isolated test session."""
    tenant = _tk("clear_rollback")
    async with db_manager.get_session_async(tenant_key=tenant) as seed_session:
        with tenant_session_context(seed_session, tenant):
            await ensure_default_types_seeded(seed_session, tenant)
            await seed_session.commit()

    svc = CommThreadService(db_manager, TenantManager())  # no injected session
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
                # Rolled back WITH the failed post -- still held by op-1, not cleared.
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
