# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.comm import CommParticipant, CommThread
from tests.api.test_comm_threads_endpoints import _create_thread, _seed_tenant


pytestmark = pytest.mark.asyncio


async def _seed_other_agent_holding_baton(db_manager, tenant_key: str, thread_id: str, agent_id: str) -> None:
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
