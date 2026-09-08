# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""FE-9586 — unread mentions, as a SERVER fact.

WHY THIS MOVED SERVER-SIDE. "Was I mentioned" was decided on the client, in
``useHubNotifications.getSignal()``, by a case-insensitive substring match of the
user's display name against ``payload.content``. That is one definition of
"mention" living in the one place that cannot reliably see the text: a post over
~5.8 KB rides the cross-worker broker as a bounded EXCERPT (pg_notify caps a
NOTIFY payload at 7999 bytes), and the composable's own docblock admits it falls
back to that excerpt when the hydrating read fails. So a mention written past the
cut-off could be missed entirely, and the reader would never learn they were
named. ``test_a_mention_past_the_excerpt_boundary_is_still_found`` is that case:
the client structurally cannot pass it, and the server cannot fail it, because
the server reads the ``content`` column whole.

Building this as a projection instead of a client derivation is also what lets a
mention BANNER exist at all -- a banner follows state, and until now no state
said "you have been named and have not looked".

SCOPE, and it deliberately differs from its BE-9207 sibling. The directed-action
query requires a ``message_recipients`` row, because directedness is DELIVERY. A
mention is NAMING, and the Hub's WS fan-out is tenant-wide
(``broadcast_event_to_tenant``), so today the operator is signalled for any
thread in the tenant where their name appears, participant or not. Requiring
participation here would SILENCE mentions they currently get, so this is
tenant-scoped. Accepted divergence, recorded rather than left to look accidental.

RESOLUTION is the read watermark, not an acknowledgment: a mention is answered
when the operator has read the thread. That fact only started existing with the
operator read signal (see tests/services/test_comm_thread_operator_read_mixin.py)
-- which is why this half could not be built first.

COVERAGE NOTE. The per-message tenant predicate is retained for consistency with
sibling queries; it is not independently exercised here because the surrounding
scoping already constrains the result set. Do not remove it.

Parallel-safe: real DB via the rollback-isolated ``db_session`` fixture, no
module-level mutable state, each test owns its setup, every query tenant-scoped.
"""

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
    """The projection under test, as ``(thread_id, message_id)`` pairs."""
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
    """Just the threads, de-duplicated in first-seen order -- what the banner shows."""
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
    """One more post on an existing thread; returns its message id."""
    posted = await svc.post_to_thread(thread_id=tid, content=content, from_agent=author, tenant_key=tenant)
    return posted["message_id"]


async def test_a_post_naming_the_viewer_is_an_unread_mention(db_manager, db_session):
    tenant = _tk("named")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    tid = await _thread_saying(svc, tenant, f"{OPERATOR_NAME}, can you look at this?")

    assert await _mentioned_threads(db_session, tenant) == [tid]


async def test_a_post_naming_nobody_is_not_a_mention(db_manager, db_session):
    """The negative control. Without it a query that returned every thread would
    pass the test above."""
    tenant = _tk("unnamed")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    await _thread_saying(svc, tenant, "status update, nothing for anyone in particular")

    assert await _mentioned_threads(db_session, tenant) == []


async def test_the_match_is_case_insensitive(db_manager, db_session):
    """Carried over verbatim from the client rule this replaces -- agents type names
    however they like, and a case-sensitive server would silently signal less than
    the client did."""
    tenant = _tk("case")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    tid = await _thread_saying(svc, tenant, f"cc {OPERATOR_NAME.lower()} please review")

    assert await _mentioned_threads(db_session, tenant) == [tid]


async def test_your_own_post_never_mentions_you(db_manager, db_session):
    """Own posts are never signalled -- also carried over from getSignal(). Writing
    your own name is not being named."""
    tenant = _tk("own")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    await _thread_saying(svc, tenant, f"{OPERATOR_NAME} writing my own name", author=OPERATOR)

    assert await _mentioned_threads(db_session, tenant) == []


async def test_reading_the_thread_clears_the_mention(db_manager, db_session):
    """Resolution is the read watermark: acting in the Hub clears it. This
    is the assertion that makes a popout a projection rather than an event -- without
    it there is nothing for the reconcile to observe."""
    tenant = _tk("read")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _thread_saying(svc, tenant, f"{OPERATOR_NAME} please look")
    assert await _mentioned_threads(db_session, tenant) == [tid]

    await svc.mark_thread_read_for_user(thread_id=tid, user_id=OPERATOR, display_name=OPERATOR_NAME, tenant_key=tenant)

    assert await _mentioned_threads(db_session, tenant) == []


async def test_a_terminal_thread_is_never_an_unread_mention(db_manager, db_session):
    """Same gate as the baton and the directed directive: "done" and "needs you"
    cannot both be true (FE-9365i, BE-9207)."""
    tenant = _tk("terminal")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _thread_saying(svc, tenant, f"{OPERATOR_NAME} please look")

    await svc.post_to_thread(
        thread_id=tid, content="closing", from_agent="agent-a", set_status="closed", tenant_key=tenant
    )

    assert await _mentioned_threads(db_session, tenant) == []


async def test_a_mention_past_the_excerpt_boundary_is_still_found(db_manager, db_session):
    """THE TEST THE CLIENT CANNOT PASS.

    pg_notify caps a NOTIFY payload at 7999 bytes, so a long post reaches the client
    as a bounded excerpt (BE-9414). The client matched the operator's name against
    that payload, falling back to the excerpt whenever the hydrating read failed --
    so a mention written past the cut-off was invisible to the very reader it named.
    The server reads the whole ``content`` column, so the position of the name in the
    body cannot matter. This is the single strongest reason the definition belongs
    here and not there."""
    tenant = _tk("excerpt")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    long_body = ("x" * 9000) + f" and finally, {OPERATOR_NAME}, over to you"
    tid = await _thread_saying(svc, tenant, long_body)

    assert await _mentioned_threads(db_session, tenant) == [tid]


async def test_a_viewer_with_no_display_name_matches_nothing(db_manager, db_session):
    """The %% catastrophe, pinned. A naive ILIKE '%' || name || '%' with an empty
    name matches EVERY post, so a user who has not set a display name would see every
    thread in the tenant reported as mentioning them. Empty means no mentions, never
    all of them."""
    tenant = _tk("noname")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    await _thread_saying(svc, tenant, f"{OPERATOR_NAME} please look")

    assert await _mentioned_threads(db_session, tenant, display_name="") == []
    assert await _mentioned_threads(db_session, tenant, display_name=None) == []


async def test_a_name_containing_like_wildcards_is_matched_literally(db_manager, db_session):
    """A display name holding '%' or '_' must not become a pattern. '_' is LIKE's
    single-character wildcard, so an unescaped name like 'A_B' would also match
    'AxB' -- mentioning somebody who was never named."""
    tenant = _tk("wildcard")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    await _thread_saying(svc, tenant, "ping AxB about the deploy")

    found = await _mentioned_threads(db_session, tenant, display_name="A_B")

    assert found == []


async def test_mentions_do_not_leak_across_tenants(db_manager, db_session):
    """Same viewer id and name in two tenants: one tenant's mention must never appear
    in the other's projection."""
    tenant_a = _tk("iso_a")
    tenant_b = _tk("iso_b")
    await _seed(db_session, tenant_a)
    await _seed(db_session, tenant_b)
    svc = _service(db_manager, db_session)
    tid_a = await _thread_saying(svc, tenant_a, f"{OPERATOR_NAME} in tenant A")

    assert await _mentioned_threads(db_session, tenant_a) == [tid_a]
    assert await _mentioned_threads(db_session, tenant_b) == []


async def test_it_names_the_post_not_only_the_thread(db_manager, db_session):
    """The bell row keys on the post and the popout deep-links to it, so a
    thread-only projection would make the client guess which arriving event the
    verdict meant."""
    tenant = _tk("anchor")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _thread_saying(svc, tenant, f"{OPERATOR_NAME} first ask")

    pairs = await _mentions(db_session, tenant)

    assert len(pairs) == 1
    thread_id, message_id = pairs[0]
    assert thread_id == tid
    # Not the thread id wearing the anchor's name -- the FE-9418 failure mode.
    assert message_id != tid


async def test_two_mentions_on_one_thread_are_two_facts(db_manager, db_session):
    """A second mention is a second thing somebody asked you (the BELL_ROWS
    keyOnPost precedent). Collapsing them to one row per thread would lose one, so
    the projection returns both posts while the banner still shows one thread."""
    tenant = _tk("two")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _thread_saying(svc, tenant, f"{OPERATOR_NAME} first ask")
    second = await _say(svc, tenant, tid, f"and again {OPERATOR_NAME}, the other thing")

    pairs = await _mentions(db_session, tenant)

    assert len(pairs) == 2
    assert {m for _t, m in pairs} >= {second}
    assert await _mentioned_threads(db_session, tenant) == [tid]
