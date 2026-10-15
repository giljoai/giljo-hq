# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from tests.api.test_comm_threads_endpoints import _create_thread, _seed_tenant


pytestmark = pytest.mark.asyncio


async def test_operator_post_reopens_a_resolved_thread_and_broadcasts_the_status(
    api_client: AsyncClient, db_manager
) -> None:
    from api.app_state import state

    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"])
    tid = thread["thread_id"]
    patched = await api_client.patch(f"/api/v1/threads/{tid}", headers=seed["headers"], json={"status": "resolved"})
    assert patched.status_code == 200, patched.text
    assert patched.json()["status"] == "resolved"

    mock_ws = AsyncMock()
    original = state.websocket_manager
    state.websocket_manager = mock_ws
    try:
        resp = await api_client.post(
            f"/api/v1/threads/{tid}/post", headers=seed["headers"], json={"content": "actually, one more question"}
        )
        assert resp.status_code == 200, resp.text
    finally:
        state.websocket_manager = original

    hist = await api_client.get(f"/api/v1/threads/{tid}", headers=seed["headers"])
    assert hist.json()["thread"]["status"] == "active"

    events = [(c.args[1] if c.args else c.kwargs["event"]) for c in mock_ws.broadcast_event_to_tenant.call_args_list]
    status_events = [e for e in events if e["type"] == "thread_update" and e["data"].get("update_type") == "status"]
    assert status_events, "the reopen must be broadcast like any other status change"
    assert status_events[0]["data"]["status"] == "active"


async def test_operator_post_to_a_closed_thread_stays_closed(api_client: AsyncClient, db_manager) -> None:
    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"])
    tid = thread["thread_id"]
    await api_client.patch(f"/api/v1/threads/{tid}", headers=seed["headers"], json={"status": "closed"})

    resp = await api_client.post(f"/api/v1/threads/{tid}/post", headers=seed["headers"], json={"content": "hello?"})
    assert resp.status_code == 200, resp.text

    hist = await api_client.get(f"/api/v1/threads/{tid}", headers=seed["headers"])
    assert hist.json()["thread"]["status"] == "closed"
