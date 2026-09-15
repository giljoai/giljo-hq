# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.auth import User
from giljo_mcp.models.comm import CommParticipant
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.models.tasks import Message
from giljo_mcp.services.comm_baton_targets import TARGET_IS_A_DISPLAY_NAME
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _payload(res) -> dict:
    if getattr(res, "structuredContent", None):
        return res.structured_content
    block = res.content[0]
    text = getattr(block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {block!r}")
    return json.loads(text)


def _error_text(res) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in res.content)


@pytest_asyncio.fixture
async def comm_mcp_client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    suffix = uuid4().hex[:8]

    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    user = User(id=str(uuid4()), tenant_key=tenant_key, username=f"patrik_{suffix}")
    db_session.add(user)
    await db_session.flush()
    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)
    await db_session.commit()

    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session)
    state.tool_accessor = accessor

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_key, db_session
    finally:
        async with db_manager.get_session_async() as cleanup:
            await cleanup.execute(delete(TaxonomyType).where(TaxonomyType.tenant_key == tenant_key))
            await cleanup.commit()
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


async def _call(new_client, tool: str, args: dict):
    async with new_client() as s:
        return await s.call_tool(tool, args)


async def _thread_with_em(new_client) -> str:
    res = await _call(new_client, "create_thread", {"subject": "registry", "creator_id": "em"})
    assert res.is_error is False, _error_text(res)
    return _payload(res)["thread_id"]


async def _baton_owner(new_client, thread_id: str) -> str | None:
    res = await _call(new_client, "get_thread_history", {"thread_id": thread_id})
    assert res.is_error is False, _error_text(res)
    return _payload(res)["thread"]["next_action_owner"]




async def test_directed_action_recipient_can_drain_without_ever_posting(comm_mcp_client):
    new_client, _tk, _sess = comm_mcp_client
    tid = await _thread_with_em(new_client)

    posted = await _call(
        new_client,
        "post_to_thread",
        {
            "thread_id": tid,
            "content": "lane-x: your gate needs a decision",
            "from_agent": "em",
            "to_participant": "lane-x",
            "requires_action": True,
        },
    )
    assert posted.is_error is False, _error_text(posted)
    assert _payload(posted)["recipients"] == ["lane-x"]

    drained = await _call(
        new_client,
        "get_thread_history",
        {"thread_id": tid, "as_participant": "lane-x", "unread_only": True, "mark_read": True},
    )
    assert drained.is_error is False, _error_text(drained)
    body = _payload(drained)
    assert body.get("success") is not False, f"reader was refused its own directed post: {body}"
    assert body["marked_read"] >= 1
    assert any("your gate needs a decision" in m["content"] for m in body["messages"])


async def test_directed_recipient_is_enrolled_in_the_directory(comm_mcp_client):
    new_client, tenant_key, db_session = comm_mcp_client
    tid = await _thread_with_em(new_client)

    posted = await _call(
        new_client,
        "post_to_thread",
        {"thread_id": tid, "content": "for you only", "from_agent": "em", "to_participant": "lane-y"},
    )
    assert posted.is_error is False, _error_text(posted)

    with tenant_session_context(db_session, tenant_key):
        row = (
            await db_session.execute(
                select(CommParticipant).where(
                    CommParticipant.tenant_key == tenant_key,
                    CommParticipant.thread_id == tid,
                    CommParticipant.participant_id == "lane-y",
                )
            )
        ).scalar_one_or_none()
    assert row is not None, "a directed post must enrol its addressee"
    assert row.participant_type == "agent"


async def test_reader_with_nothing_delivered_is_still_refused(comm_mcp_client):
    new_client, _tk, _sess = comm_mcp_client
    tid = await _thread_with_em(new_client)
    posted = await _call(new_client, "post_to_thread", {"thread_id": tid, "content": "town square", "from_agent": "em"})
    assert posted.is_error is False, _error_text(posted)

    res = await _call(
        new_client, "get_thread_history", {"thread_id": tid, "as_participant": "ghost", "mark_read": True}
    )
    assert res.is_error is False, _error_text(res)
    body = _payload(res)
    assert body["success"] is False
    assert body["error"] == "NOT_A_PARTICIPANT"




async def test_undeliverable_baton_target_is_rejected_not_silently_accepted(comm_mcp_client):
    new_client, tenant_key, db_session = comm_mcp_client
    tid = await _thread_with_em(new_client)
    joined = await _call(new_client, "join_thread", {"thread_id": tid, "agent_id": "lane-a"})
    assert joined.is_error is False, _error_text(joined)

    res = await _call(
        new_client,
        "post_to_thread",
        {
            "thread_id": tid,
            "content": "DONE - baton back to you",
            "from_agent": "lane-a",
            "pass_baton_to": "Ledger Zero Conductor",
        },
    )
    assert res.is_error is False, _error_text(res)
    body = _payload(res)
    assert body["success"] is False
    assert body["error"] == "BATON_TARGET_NOT_A_PARTICIPANT"
    assert body["requested"] == "Ledger Zero Conductor"
    assert "em" in body["valid_participants"]
    assert "lane-a" in body["valid_participants"]

    assert await _baton_owner(new_client, tid) == "em"
    with tenant_session_context(db_session, tenant_key):
        count = (await db_session.execute(select(func.count(Message.id)).where(Message.thread_id == tid))).scalar_one()
    assert count == 0, "a rejected post must persist no message"


async def test_pass_baton_tool_refuses_the_same_undeliverable_target(comm_mcp_client):
    new_client, _tk, _sess = comm_mcp_client
    tid = await _thread_with_em(new_client)

    res = await _call(new_client, "set_next_actor", {"thread_id": tid, "to": "ghost-conductor"})
    assert res.is_error is False, _error_text(res)
    body = _payload(res)
    assert body["success"] is False
    assert body["error"] == "BATON_TARGET_NOT_A_PARTICIPANT"
    assert body["valid_participants"] == ["em"]
    assert body["next_action_owner"] == "em"
    assert await _baton_owner(new_client, tid) == "em"


async def test_reserved_baton_targets_and_registered_participants_still_work(comm_mcp_client):
    new_client, _tk, _sess = comm_mcp_client
    tid = await _thread_with_em(new_client)
    joined = await _call(new_client, "join_thread", {"thread_id": tid, "agent_id": "lane-a"})
    assert joined.is_error is False, _error_text(joined)

    to_participant = await _call(
        new_client,
        "post_to_thread",
        {"thread_id": tid, "content": "over to you", "from_agent": "em", "pass_baton_to": "lane-a"},
    )
    assert to_participant.is_error is False, _error_text(to_participant)
    assert _payload(to_participant)["baton_passed"] is True
    assert await _baton_owner(new_client, tid) == "lane-a"

    to_all = await _call(
        new_client,
        "post_to_thread",
        {"thread_id": tid, "content": "ACCEPTED", "from_agent": "lane-a", "pass_baton_to": "all"},
    )
    assert to_all.is_error is False, _error_text(to_all)
    assert await _baton_owner(new_client, tid) == "all"

    to_none = await _call(
        new_client,
        "post_to_thread",
        {"thread_id": tid, "content": "fyi", "from_agent": "lane-a", "pass_baton_to": "none"},
    )
    assert to_none.is_error is False, _error_text(to_none)
    assert _payload(to_none)["baton_passed"] is False
    assert await _baton_owner(new_client, tid) == "all"


async def test_directed_auto_pass_to_first_contact_recipient_still_works(comm_mcp_client):
    new_client, _tk, _sess = comm_mcp_client
    tid = await _thread_with_em(new_client)

    res = await _call(
        new_client,
        "post_to_thread",
        {
            "thread_id": tid,
            "content": "lane-z: take it",
            "from_agent": "em",
            "to_participant": "lane-z",
            "requires_action": True,
        },
    )
    assert res.is_error is False, _error_text(res)
    body = _payload(res)
    assert body.get("success") is not False, f"first-contact directed hand-off was refused: {body}"
    assert body["baton_passed"] is True
    assert await _baton_owner(new_client, tid) == "lane-z"

    turn = await _call(new_client, "get_my_turn", {"agent_id": "lane-z"})
    assert turn.is_error is False, _error_text(turn)
    assert tid in {t["thread_id"] for t in _payload(turn)["threads"]}


async def test_first_post_by_an_unjoined_author_can_still_hand_off_to_itself(comm_mcp_client):
    new_client, _tk, _sess = comm_mcp_client
    tid = await _thread_with_em(new_client)

    res = await _call(
        new_client,
        "post_to_thread",
        {"thread_id": tid, "content": "picking this up", "from_agent": "lane-new", "pass_baton_to": "lane-new"},
    )
    assert res.is_error is False, _error_text(res)
    assert _payload(res).get("success") is not False
    assert await _baton_owner(new_client, tid) == "lane-new"



_CONDUCTOR_UUID = "36eac157-bf1e-466e-9e51-91485f46ee62"
_CONDUCTOR_LABEL = "Ledger Zero Conductor"


async def _thread_with_labelled_conductor(new_client) -> str:
    tid = await _thread_with_em(new_client)
    joined = await _call(
        new_client,
        "join_thread",
        {"thread_id": tid, "agent_id": _CONDUCTOR_UUID, "display_name": _CONDUCTOR_LABEL},
    )
    assert joined.is_error is False, _error_text(joined)
    return tid


async def test_auto_pass_to_a_display_label_cannot_strand_the_conductor(comm_mcp_client):
    new_client, _tk, _sess = comm_mcp_client
    tid = await _thread_with_labelled_conductor(new_client)

    res = await _call(
        new_client,
        "post_to_thread",
        {
            "thread_id": tid,
            "content": "DONE - lane complete, baton back to you",
            "from_agent": "sub-orch",
            "to_participant": _CONDUCTOR_LABEL,
            "requires_action": True,
        },
    )
    assert res.is_error is False, _error_text(res)
    body = _payload(res)

    owner = await _baton_owner(new_client, tid)
    assert owner != _CONDUCTOR_LABEL, "the baton was handed to a display label — the conductor is stranded"
    turn = await _call(new_client, "get_my_turn", {"agent_id": _CONDUCTOR_UUID})
    assert turn.is_error is False, _error_text(turn)
    reachable = tid in {t["thread_id"] for t in _payload(turn)["threads"]}
    assert reachable or owner == "em", "baton neither reachable by the conductor nor left where it was"

    assert body["success"] is False
    assert body["error"] == TARGET_IS_A_DISPLAY_NAME
    assert body["registered_id"] == _CONDUCTOR_UUID
    assert _CONDUCTOR_UUID in body["hint"]


async def test_a_directed_post_to_a_label_mints_no_phantom_participant(comm_mcp_client):
    new_client, tenant_key, db_session = comm_mcp_client
    tid = await _thread_with_labelled_conductor(new_client)

    await _call(
        new_client,
        "post_to_thread",
        {
            "thread_id": tid,
            "content": "status for you",
            "from_agent": "sub-orch",
            "to_participant": _CONDUCTOR_LABEL,
            "requires_action": True,
        },
    )

    with tenant_session_context(db_session, tenant_key):
        phantom = (
            await db_session.execute(
                select(CommParticipant).where(
                    CommParticipant.tenant_key == tenant_key,
                    CommParticipant.thread_id == tid,
                    CommParticipant.participant_id == _CONDUCTOR_LABEL,
                )
            )
        ).scalar_one_or_none()
    assert phantom is None, "a display label was minted as a participant beside the id it shadows"


async def test_a_minted_label_cannot_launder_a_later_explicit_hand_off(comm_mcp_client):
    new_client, _tk, _sess = comm_mcp_client
    tid = await _thread_with_labelled_conductor(new_client)

    await _call(
        new_client,
        "post_to_thread",
        {
            "thread_id": tid,
            "content": "first contact",
            "from_agent": "sub-orch",
            "to_participant": _CONDUCTOR_LABEL,
            "requires_action": True,
        },
    )

    res = await _call(
        new_client,
        "post_to_thread",
        {
            "thread_id": tid,
            "content": "explicitly yours",
            "from_agent": "sub-orch",
            "pass_baton_to": _CONDUCTOR_LABEL,
        },
    )
    assert res.is_error is False, _error_text(res)
    body = _payload(res)
    assert body["success"] is False, "a minted label laundered a later explicit hand-off past the validator"
    assert body["error"] == TARGET_IS_A_DISPLAY_NAME
    assert await _baton_owner(new_client, tid) != _CONDUCTOR_LABEL


async def test_a_label_that_shadows_nobody_is_still_a_legitimate_addressee(comm_mcp_client):
    new_client, _tk, _sess = comm_mcp_client
    tid = await _thread_with_labelled_conductor(new_client)

    res = await _call(
        new_client,
        "post_to_thread",
        {
            "thread_id": tid,
            "content": "lane-z: take it",
            "from_agent": "em",
            "to_participant": "lane-z-never-seen",
            "requires_action": True,
        },
    )
    assert res.is_error is False, _error_text(res)
    assert _payload(res).get("success") is not False, "a plain first-contact addressee was refused"
    assert await _baton_owner(new_client, tid) == "lane-z-never-seen"




async def _the_operator(db_session, tenant_key: str) -> str:
    rows = await db_session.execute(select(User.id).where(User.tenant_key == tenant_key))
    ids = list(rows.scalars().all())
    assert len(ids) == 1, "fixture invariant: one operator per tenant"
    return ids[0]


async def test_an_agent_can_hand_the_baton_to_the_operator_by_the_name_user(comm_mcp_client):
    new_client, tenant_key, db_session = comm_mcp_client
    tid = await _thread_with_em(new_client)

    res = await _call(
        new_client,
        "post_to_thread",
        {
            "thread_id": tid,
            "content": "Need your call on the pricing copy before I ship.",
            "from_agent": "em",
            "to_participant": "user",
            "requires_action": True,
        },
    )
    assert res.is_error is False, _error_text(res)
    assert _payload(res).get("success") is not False, "the operator alias was refused"

    operator_id = await _the_operator(db_session, tenant_key)
    assert await _baton_owner(new_client, tid) == operator_id


async def test_pass_baton_accepts_the_operator_alias_too(comm_mcp_client):
    new_client, tenant_key, db_session = comm_mcp_client
    tid = await _thread_with_em(new_client)

    res = await _call(new_client, "set_next_actor", {"thread_id": tid, "to": "user"})
    assert res.is_error is False, _error_text(res)

    operator_id = await _the_operator(db_session, tenant_key)
    assert await _baton_owner(new_client, tid) == operator_id


async def test_the_operator_alias_enrols_the_operator_as_a_user_not_an_agent(comm_mcp_client):
    new_client, tenant_key, db_session = comm_mcp_client
    tid = await _thread_with_em(new_client)

    res = await _call(
        new_client,
        "post_to_thread",
        {"thread_id": tid, "content": "your call", "from_agent": "em", "to_participant": "user"},
    )
    assert res.is_error is False, _error_text(res)

    operator_id = await _the_operator(db_session, tenant_key)
    rows = await db_session.execute(
        select(CommParticipant.participant_type).where(
            CommParticipant.tenant_key == tenant_key,
            CommParticipant.thread_id == tid,
            CommParticipant.participant_id == operator_id,
        )
    )
    assert rows.scalar_one() == "user"
