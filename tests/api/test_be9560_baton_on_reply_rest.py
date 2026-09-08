# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""REST endpoint tests for BE-9560 -- baton-on-reply.

Operator-reported 2026-09-02: the "Waiting on you" banner in the dashboard
outlives an operator's reply. Root cause verified by call path: ``comm_threads.py``
``post_to_thread`` forwarded no baton at all, so an operator who replies to a
thread they hold never clears it -- only the manual raised-hand control did.

These are the RED-FIRST repros at the failing layer named in the work order: an
operator REST post to a thread they hold, asserting ``next_action_owner``
afterwards, for both the directed and broadcast case. They pass now that
``CommThreadService.post_to_thread`` gained ``pass_baton_to``/
``clear_baton_on_broadcast_reply`` forwarding from this route (see
``api/endpoints/comm_threads.py::post_to_thread``); before that change the
broadcast case left ``next_action_owner`` unchanged and the directed case never
moved the baton either.

Parallel-safe: uses the ``api_client`` fixture (fresh db_manager session per
test), no module-level mutable state, no test ordering dependencies.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.comm import CommParticipant, CommThread
from tests.api.test_comm_threads_endpoints import _create_thread, _seed_tenant  # reuse the house fixtures


pytestmark = pytest.mark.asyncio


async def _seed_other_agent_holding_baton(db_manager, tenant_key: str, thread_id: str, agent_id: str) -> None:
    """Register ``agent_id`` as a participant and hand it the baton directly at the
    DB layer -- the REST surface has no join-a-participant route (join_thread is
    MCP-side; see the existing BE-9292a-F1 REST test for the same seeding pattern)."""
    async with db_manager.get_session_async() as session:
        with tenant_session_context(session, tenant_key):
            session.add(
                CommParticipant(
                    tenant_key=tenant_key,
                    thread_id=thread_id,
                    participant_id=agent_id,
                    participant_type="agent",
                    display_name=agent_id,
                )
            )
            thread = (await session.execute(select(CommThread).where(CommThread.id == thread_id))).scalar_one()
            thread.next_action_owner = agent_id
            await session.commit()


async def test_operator_broadcast_reply_clears_the_banner(api_client: AsyncClient, db_manager) -> None:
    """RED-FIRST repro (broadcast case): the operator creates (and so holds) the
    thread, replies with no addressee, and the baton must clear -- this is the
    exact "Waiting on you" banner-outlives-the-reply bug."""
    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"])
    thread_id = thread["thread_id"]
    assert thread["next_action_owner"] == seed["user_id"]

    resp = await api_client.post(
        f"/api/v1/threads/{thread_id}/post",
        headers=seed["headers"],
        json={"content": "answered, no addressee"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["baton_cleared"] is True
    assert body["next_action_owner"] is None

    hist = await api_client.get(f"/api/v1/threads/{thread_id}", headers=seed["headers"])
    assert hist.json()["thread"]["next_action_owner"] is None


async def test_operator_directed_reply_hands_off_the_baton(api_client: AsyncClient, db_manager) -> None:
    """RED-FIRST repro (directed case): the operator holds the thread and DMs an
    addressee -- the baton must move to that addressee, unconditionally, the same
    as the MCP auto-pass."""
    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"])
    thread_id = thread["thread_id"]

    resp = await api_client.post(
        f"/api/v1/threads/{thread_id}/post",
        headers=seed["headers"],
        json={"content": "over to you", "to_participant": "agent_new"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["baton_passed"] is True
    assert body["next_action_owner"] == "agent_new"


async def test_operator_broadcast_reply_leaves_another_agents_baton_untouched(
    api_client: AsyncClient, db_manager
) -> None:
    """Regression guard: an operator's unrelated broadcast comment must never
    silently cancel some OTHER agent's still-open turn."""
    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"])
    thread_id = thread["thread_id"]
    await _seed_other_agent_holding_baton(db_manager, seed["tenant_key"], thread_id, "agent_midtask")

    resp = await api_client.post(
        f"/api/v1/threads/{thread_id}/post",
        headers=seed["headers"],
        json={"content": "FYI, not for agent_midtask"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["baton_cleared"] is False
    assert body["next_action_owner"] == "agent_midtask"


async def test_operator_broadcast_reply_clears_shared_all_baton(api_client: AsyncClient, db_manager) -> None:
    """'all'-owner case, stated and covered: an open turn shared with everyone is
    resolved by the operator answering it, same as their own held baton."""
    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"])
    thread_id = thread["thread_id"]

    baton_resp = await api_client.post(
        f"/api/v1/threads/{thread_id}/baton", headers=seed["headers"], json={"to": "all"}
    )
    assert baton_resp.status_code == 200, baton_resp.text

    resp = await api_client.post(
        f"/api/v1/threads/{thread_id}/post",
        headers=seed["headers"],
        json={"content": "I'll take it"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["next_action_owner"] is None


async def test_operator_broadcast_reply_on_a_closed_thread_still_clears(api_client: AsyncClient, db_manager) -> None:
    """Terminal-thread case, stated and covered: no special-casing -- a reply that
    closes the thread still applies the same mirror rule to the baton, matching the
    existing precedent that ``post_to_thread`` never gates the baton on status."""
    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"])
    thread_id = thread["thread_id"]

    resp = await api_client.post(
        f"/api/v1/threads/{thread_id}/post",
        headers=seed["headers"],
        json={"content": "wrapping up", "set_status": "closed"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["baton_cleared"] is True
    assert body["next_action_owner"] is None

    hist = await api_client.get(f"/api/v1/threads/{thread_id}", headers=seed["headers"])
    t = hist.json()["thread"]
    assert t["status"] == "closed"
    assert t["next_action_owner"] is None


async def test_unregistered_agent_string_id(api_client: AsyncClient, db_manager) -> None:
    """A directed reply to a plain new agent id (not a display-name collision, not
    previously registered) is not refused -- the auto-pass ``also_reachable``
    exemption (the post enrols its own addressee) applies to REST exactly like it
    already does at the MCP boundary. Guards against over-tightening the new
    pass_baton_to forwarding into a false-positive refusal on first contact."""
    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"])
    thread_id = thread["thread_id"]

    resp = await api_client.post(
        f"/api/v1/threads/{thread_id}/post",
        headers=seed["headers"],
        json={"content": "first contact", "to_participant": str(uuid.uuid4())},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("success", True) is not False
    assert body["baton_passed"] is True


async def test_ws_broadcasts_a_baton_update_on_a_broadcast_reply(api_client: AsyncClient, db_manager) -> None:
    """Dual-door WS parity: a plain broadcast reply that clears the operator's own
    baton must push a live thread_update(update_type=baton) too, exactly like the
    MCP wrapper already does on baton_passed -- otherwise every OTHER open tab only
    learns the turn cleared on its next reload."""
    from api.app_state import state

    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"])

    mock_ws = AsyncMock()
    original = state.websocket_manager
    state.websocket_manager = mock_ws
    try:
        resp = await api_client.post(
            f"/api/v1/threads/{thread['thread_id']}/post",
            headers=seed["headers"],
            json={"content": "answered, no addressee"},
        )
        assert resp.status_code == 200, resp.text
    finally:
        state.websocket_manager = original

    calls = mock_ws.broadcast_event_to_tenant.call_args_list
    baton_events = [
        (call.args[1] if call.args else call.kwargs["event"])
        for call in calls
        if (call.args[1] if call.args else call.kwargs["event"])["type"] == "thread_update"
    ]
    assert any(e["data"]["update_type"] == "baton" for e in baton_events)
    baton_event = next(e for e in baton_events if e["data"]["update_type"] == "baton")
    assert baton_event["data"]["next_action_owner"] is None
