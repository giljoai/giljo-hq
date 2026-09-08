# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""FE-9586 — the operator's attention read: what is asking for you, right now.

ONE READ, because the banner family needs ONE loaded state. A family assembled
from two independent fetches has two hydration moments, and "not fetched yet"
becomes indistinguishable from "nothing waiting" for whichever half is late --
the exact shape of the FE-9553 near-miss, where an unhydrated store looked like a
cleared banner and would have closed every popout on mount.

WHY THE DISPLAY NAME IS RESOLVED HERE AND NOT PASSED IN. "Mention" must have ONE
definition. The client's display-name match is deleted in this same change, so if
this service accepted a name from its caller, the caller would become the second
definition -- a REST shim, an MCP tool and a test could each hand it a different
string and each get a different answer to "was I mentioned". It reads the name
off the authenticated user's own row, through the same ``User.display_name``
property the API already serves to the client.

THE BROADCAST RULE IS PINNED HERE.
``getSignal()`` treated a BROADCAST ``requires_action`` post as the operator's
business ("all recipients must act"). The server never has: BE-9207's directed
query excludes broadcasts, citing BE-9197 as a museum-rule decision -- a
broadcast action-request is "whoever picks it up" and obligates nobody in
particular. Those two disagreed, so the client's popout was quietly
contradicting a ruled invariant. This read is the server's answer and the client
is aligned to it: a broadcast keeps its durable bell row and stops claiming a
specific person owes an answer.

Parallel-safe: real DB via the rollback-isolated ``db_session`` fixture, no
module-level mutable state, each test owns its setup, every query tenant-scoped.
"""

from __future__ import annotations

import uuid

import bcrypt
import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _tk(suffix: str) -> str:
    return f"tk_attn_{suffix}_{uuid.uuid4().hex[:8]}"


def _service(db_manager, db_session) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed_operator(db_session, tenant: str, *, first: str = "Patrik", last: str = "") -> str:
    """An org + user whose ``display_name`` resolves to ``first last``.

    A real row, not a stub: the whole point of this surface is that the server
    reads the name off the user rather than being told it, so a test that supplied
    the name would be testing nothing.
    """
    suffix = uuid.uuid4().hex[:8]
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
        org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant, is_active=True)
        db_session.add(org)
        await db_session.flush()
        user = User(
            username=f"op_{suffix}",
            email=f"op_{suffix}@example.com",
            password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode(),
            tenant_key=tenant,
            role="developer",
            org_id=org.id,
            first_name=first,
            last_name=last or None,
        )
        db_session.add(user)
        await db_session.flush()
        return user.id


async def _thread(svc: CommThreadService, tenant: str) -> str:
    created = await svc.create_thread(subject="t", creator_id="agent-orch", tenant_key=tenant)
    return created["thread_id"]


async def test_a_post_naming_the_operator_lands_in_mentions(db_manager, db_session):
    """And the caller passes NO name -- the server resolves it off the user row."""
    tenant = _tk("mention")
    user_id = await _seed_operator(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _thread(svc, tenant)
    await svc.post_to_thread(thread_id=tid, content="Patrik, take a look", from_agent="agent-a", tenant_key=tenant)

    attention = await svc.get_attention_for_user(user_id=user_id, tenant_key=tenant)

    assert [m["thread_id"] for m in attention["mentions"]] == [tid]


async def test_a_directed_action_request_lands_in_directed_action(db_manager, db_session):
    """The BE-9207 projection, surfaced for the operator rather than an agent."""
    tenant = _tk("directed")
    user_id = await _seed_operator(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _thread(svc, tenant)
    await svc.join_thread(thread_id=tid, participant_id=user_id, participant_type="user", tenant_key=tenant)
    await svc.post_to_thread(
        thread_id=tid,
        content="please decide",
        from_agent="agent-a",
        to_participant=user_id,
        requires_action=True,
        tenant_key=tenant,
    )

    attention = await svc.get_attention_for_user(user_id=user_id, tenant_key=tenant)

    assert [d["thread_id"] for d in attention["directed_action"]] == [tid]


async def test_a_broadcast_action_request_obligates_nobody(db_manager, db_session):
    """BE-9197, pinned: a broadcast requires_action post is
    "whoever picks it up". It must appear in NEITHER list, so the client can stop
    raising an actionable popout for it and keep only the durable bell row.

    This is the assertion that fails first if anyone re-widens the recipient test
    the way getSignal() had it."""
    tenant = _tk("broadcast")
    user_id = await _seed_operator(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _thread(svc, tenant)
    await svc.join_thread(thread_id=tid, participant_id=user_id, participant_type="user", tenant_key=tenant)
    await svc.post_to_thread(
        thread_id=tid,
        content="somebody should handle the deploy",
        from_agent="agent-a",
        requires_action=True,
        tenant_key=tenant,
    )

    attention = await svc.get_attention_for_user(user_id=user_id, tenant_key=tenant)

    assert attention["mentions"] == []
    assert attention["directed_action"] == []


async def test_reading_the_thread_clears_both_classes(db_manager, db_session):
    """Acting in the Hub clears it. Both halves resolve on the same
    gesture, which is what makes ONE banner family honest."""
    tenant = _tk("clear")
    user_id = await _seed_operator(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _thread(svc, tenant)
    await svc.join_thread(thread_id=tid, participant_id=user_id, participant_type="user", tenant_key=tenant)
    await svc.post_to_thread(
        thread_id=tid,
        content="Patrik, please decide",
        from_agent="agent-a",
        to_participant=user_id,
        requires_action=True,
        tenant_key=tenant,
    )
    before = await svc.get_attention_for_user(user_id=user_id, tenant_key=tenant)
    assert before["mentions"] and before["directed_action"]

    await svc.mark_thread_read_for_user(thread_id=tid, user_id=user_id, tenant_key=tenant)

    after = await svc.get_attention_for_user(user_id=user_id, tenant_key=tenant)
    assert after["mentions"] == []
    assert after["directed_action"] == []


async def test_a_user_whose_name_appears_nowhere_gets_nothing(db_manager, db_session):
    """The negative control. Without it, a read that returned every thread would
    pass every test above."""
    tenant = _tk("quiet")
    user_id = await _seed_operator(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _thread(svc, tenant)
    await svc.post_to_thread(
        thread_id=tid, content="routine status, nobody named", from_agent="agent-a", tenant_key=tenant
    )

    attention = await svc.get_attention_for_user(user_id=user_id, tenant_key=tenant)

    assert attention["mentions"] == []
    assert attention["directed_action"] == []


async def test_an_unknown_user_gets_nothing_rather_than_everything(db_manager, db_session):
    """No user row means no resolvable name, and an unresolved name must collapse to
    NO mentions -- never to the empty-pattern match that reports every thread. The
    repository layer pins the same rule; this pins that the service cannot route
    around it."""
    tenant = _tk("ghost")
    await _seed_operator(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _thread(svc, tenant)
    await svc.post_to_thread(thread_id=tid, content="Patrik, take a look", from_agent="agent-a", tenant_key=tenant)

    attention = await svc.get_attention_for_user(user_id=str(uuid.uuid4()), tenant_key=tenant)

    assert attention["mentions"] == []


async def test_mentions_name_every_post_grouped_by_thread(db_manager, db_session):
    """One entry per thread for the banner, every naming post listed for the bell and
    the deep-link. Two mentions on one thread are two facts on one row."""
    tenant = _tk("grouped")
    user_id = await _seed_operator(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _thread(svc, tenant)
    first = await svc.post_to_thread(
        thread_id=tid, content="Patrik, one thing", from_agent="agent-a", tenant_key=tenant
    )
    second = await svc.post_to_thread(
        thread_id=tid, content="Patrik, another thing", from_agent="agent-a", tenant_key=tenant
    )

    attention = await svc.get_attention_for_user(user_id=user_id, tenant_key=tenant)

    assert len(attention["mentions"]) == 1
    entry = attention["mentions"][0]
    assert entry["thread_id"] == tid
    assert set(entry["message_ids"]) == {first["message_id"], second["message_id"]}
