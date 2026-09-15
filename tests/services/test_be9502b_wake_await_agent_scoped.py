# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import json

import pytest_asyncio

from api.endpoints.mcp_sdk_server import mcp
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.tool_accessor import ToolAccessor
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


WAKE_DEADLINE_SECONDS = 3.0


def _payload(result) -> dict:
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            return json.loads(text)
    raise AssertionError("tool returned no content")


@pytest_asyncio.fixture
async def two_product_wake_client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.database import tenant_session_context

    state = app_state.state
    prior_accessor, prior_tm, prior_dbm = state.tool_accessor, state.tenant_manager, state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)
    service = CommThreadService(db_manager, state.tenant_manager, session=db_session)
    accessor._comm_thread_service = service
    state.tool_accessor = accessor

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)
    monkeypatch.setattr(_base, "should_run", lambda *args, **kwargs: False)

    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)

    def _client():
        return create_connected_server_and_client_session(mcp)

    try:
        yield _client, tenant_key, service
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior_accessor, prior_tm, prior_dbm


async def _thread_with_worker(service: CommThreadService, tenant_key: str, subject: str, worker_id: str) -> str:
    created = await service.create_thread(subject=subject, creator_id="em", tenant_key=tenant_key)
    thread_id = created["thread_id"]
    await service.join_thread(
        thread_id=thread_id, participant_id=worker_id, display_name=worker_id, tenant_key=tenant_key
    )
    return thread_id


async def test_a_directed_wake_for_one_agent_never_wakes_the_others_parked_call(two_product_wake_client):
    client_factory, tenant_key, service = two_product_wake_client
    thread_a = await _thread_with_worker(service, tenant_key, "product-A work", "agent-a")
    await _thread_with_worker(service, tenant_key, "product-B work", "agent-b")

    async with client_factory() as client_a, client_factory() as client_b:
        call_a = asyncio.create_task(client_a.call_tool("get_my_turn", {"agent_id": "agent-a", "wait_seconds": 10}))
        call_b = asyncio.create_task(client_b.call_tool("get_my_turn", {"agent_id": "agent-b", "wait_seconds": 1}))

        await asyncio.sleep(0.05)

        await service.post_to_thread(
            thread_id=thread_a,
            content="your turn",
            from_agent="em",
            to_participant="agent-a",
            requires_action=True,
            tenant_key=tenant_key,
        )

        result_a = await asyncio.wait_for(call_a, timeout=WAKE_DEADLINE_SECONDS)
        result_b = await asyncio.wait_for(call_b, timeout=WAKE_DEADLINE_SECONDS)

    body_a = _payload(result_a)
    body_b = _payload(result_b)

    assert body_a["woken"] is True
    assert body_a["wake_reason"] == "signalled"
    assert body_a["agent_id"] == "agent-a"
    assert [t["thread_id"] for t in body_a["directed_action"]] == [thread_a]

    assert body_b["woken"] is False
    assert body_b["wake_reason"] == "timeout"
    assert body_b["agent_id"] == "agent-b"
    assert thread_a not in [t["thread_id"] for t in body_b.get("threads", [])]


async def test_get_my_turn_for_one_agent_never_surfaces_the_others_directed_thread(two_product_wake_client):
    client_factory, tenant_key, service = two_product_wake_client
    thread_a = await _thread_with_worker(service, tenant_key, "product-A work", "agent-a")
    thread_b = await _thread_with_worker(service, tenant_key, "product-B work", "agent-b")

    await service.post_to_thread(
        thread_id=thread_a,
        content="A's turn",
        from_agent="em",
        to_participant="agent-a",
        requires_action=True,
        tenant_key=tenant_key,
    )
    await service.post_to_thread(
        thread_id=thread_b,
        content="B's turn",
        from_agent="em",
        to_participant="agent-b",
        requires_action=True,
        tenant_key=tenant_key,
    )

    async with client_factory() as client:
        result_a = await client.call_tool("get_my_turn", {"agent_id": "agent-a"})
        result_b = await client.call_tool("get_my_turn", {"agent_id": "agent-b"})

    body_a = _payload(result_a)
    body_b = _payload(result_b)

    threads_a = {t["thread_id"] for t in body_a["threads"]}
    threads_b = {t["thread_id"] for t in body_b["threads"]}
    assert thread_a in threads_a
    assert thread_b not in threads_a
    assert thread_b in threads_b
    assert thread_a not in threads_b
