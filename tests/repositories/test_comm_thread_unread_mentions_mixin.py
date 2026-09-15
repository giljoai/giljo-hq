# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid

import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.repositories.comm_thread_repository import CommThreadRepository
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

OPERATOR = "operator-1"
OPERATOR_NAME = "Patrik"


def _tk(suffix: str) -> str:
    return f"tk_mentions_{suffix}_{uuid.uuid4().hex[:8]}"


def _service(db_manager, db_session) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed(db_session, tenant: str) -> None:
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)


async def _mentions(
    db_session,
    tenant: str,
    *,
    viewer_id: str = OPERATOR,
    display_name: str | None = OPERATOR_NAME,
) -> list[tuple[str, str]]:
    repo = CommThreadRepository()
    with tenant_session_context(db_session, tenant):
        rows = await repo.get_unread_mentions(db_session, tenant, viewer_id=viewer_id, display_name=display_name)
    return [(thread.id, message_id) for thread, message_id in rows]


async def _mentioned_threads(
    db_session,
    tenant: str,
    *,
    viewer_id: str = OPERATOR,
    display_name: str | None = OPERATOR_NAME,
) -> list[str]:
    seen: list[str] = []
    for thread_id, _message_id in await _mentions(db_session, tenant, viewer_id=viewer_id, display_name=display_name):
        if thread_id not in seen:
            seen.append(thread_id)
    return seen


async def _thread_saying(svc: CommThreadService, tenant: str, content: str, *, author: str = "agent-a") -> str:
    thread = await svc.create_thread(subject="t", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.post_to_thread(thread_id=tid, content=content, from_agent=author, tenant_key=tenant)
    return tid


async def _say(svc: CommThreadService, tenant: str, tid: str, content: str, *, author: str = "agent-a") -> str:
    posted = await svc.post_to_thread(thread_id=tid, content=content, from_agent=author, tenant_key=tenant)
    return posted["message_id"]


async def test_a_post_naming_the_viewer_is_an_unread_mention(db_manager, db_session):
    tenant = _tk("named")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    tid = await _thread_saying(svc, tenant, f"{OPERATOR_NAME}, can you look at this?")

    assert await _mentioned_threads(db_session, tenant) == [tid]


async def test_a_post_naming_nobody_is_not_a_mention(db_manager, db_session):
    tenant = _tk("unnamed")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    await _thread_saying(svc, tenant, "status update, nothing for anyone in particular")

    assert await _mentioned_threads(db_session, tenant) == []


async def test_the_match_is_case_insensitive(db_manager, db_session):
    tenant = _tk("case")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    tid = await _thread_saying(svc, tenant, f"cc {OPERATOR_NAME.lower()} please review")

    assert await _mentioned_threads(db_session, tenant) == [tid]


async def test_your_own_post_never_mentions_you(db_manager, db_session):
    tenant = _tk("own")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    await _thread_saying(svc, tenant, f"{OPERATOR_NAME} writing my own name", author=OPERATOR)

    assert await _mentioned_threads(db_session, tenant) == []


async def test_reading_the_thread_clears_the_mention(db_manager, db_session):
    tenant = _tk("read")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _thread_saying(svc, tenant, f"{OPERATOR_NAME} please look")
    assert await _mentioned_threads(db_session, tenant) == [tid]

    await svc.mark_thread_read_for_user(thread_id=tid, user_id=OPERATOR, display_name=OPERATOR_NAME, tenant_key=tenant)

    assert await _mentioned_threads(db_session, tenant) == []


async def test_a_terminal_thread_is_never_an_unread_mention(db_manager, db_session):
    tenant = _tk("terminal")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _thread_saying(svc, tenant, f"{OPERATOR_NAME} please look")

    await svc.post_to_thread(
        thread_id=tid, content="closing", from_agent="agent-a", set_status="closed", tenant_key=tenant
    )

    assert await _mentioned_threads(db_session, tenant) == []


async def test_a_mention_past_the_excerpt_boundary_is_still_found(db_manager, db_session):
    tenant = _tk("excerpt")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    long_body = ("x" * 9000) + f" and finally, {OPERATOR_NAME}, over to you"
    tid = await _thread_saying(svc, tenant, long_body)

    assert await _mentioned_threads(db_session, tenant) == [tid]


async def test_a_viewer_with_no_display_name_matches_nothing(db_manager, db_session):
    tenant = _tk("noname")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    await _thread_saying(svc, tenant, f"{OPERATOR_NAME} please look")

    assert await _mentioned_threads(db_session, tenant, display_name="") == []
    assert await _mentioned_threads(db_session, tenant, display_name=None) == []


async def test_a_name_containing_like_wildcards_is_matched_literally(db_manager, db_session):
    tenant = _tk("wildcard")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    await _thread_saying(svc, tenant, "ping AxB about the deploy")

    found = await _mentioned_threads(db_session, tenant, display_name="A_B")

    assert found == []


async def test_mentions_do_not_leak_across_tenants(db_manager, db_session):
    tenant_a = _tk("iso_a")
    tenant_b = _tk("iso_b")
    await _seed(db_session, tenant_a)
    await _seed(db_session, tenant_b)
    svc = _service(db_manager, db_session)
    tid_a = await _thread_saying(svc, tenant_a, f"{OPERATOR_NAME} in tenant A")

    assert await _mentioned_threads(db_session, tenant_a) == [tid_a]
    assert await _mentioned_threads(db_session, tenant_b) == []


async def test_it_names_the_post_not_only_the_thread(db_manager, db_session):
    tenant = _tk("anchor")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _thread_saying(svc, tenant, f"{OPERATOR_NAME} first ask")

    pairs = await _mentions(db_session, tenant)

    assert len(pairs) == 1
    thread_id, message_id = pairs[0]
    assert thread_id == tid
    assert message_id != tid


async def test_two_mentions_on_one_thread_are_two_facts(db_manager, db_session):
    tenant = _tk("two")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _thread_saying(svc, tenant, f"{OPERATOR_NAME} first ask")
    second = await _say(svc, tenant, tid, f"and again {OPERATOR_NAME}, the other thing")

    pairs = await _mentions(db_session, tenant)

    assert len(pairs) == 2
    assert {m for _t, m in pairs} >= {second}
    assert await _mentioned_threads(db_session, tenant) == [tid]
