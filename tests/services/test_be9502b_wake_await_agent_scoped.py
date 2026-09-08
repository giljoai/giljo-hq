# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9502b -- ``get_my_turn`` / ``get_my_turn`` are agent-scoped, not product-confused.

Ruling 15: two harness sessions on the same tenant, each driving work under a
different product, must not have their wake/turn machinery cross-talk. Both
tools key strictly on ``(tenant_key, agent_id)`` -- see
``_comm_thread_wake_mixin.get_my_turn`` (registers with
``get_wake_registry().register(tk, agent_id)``) and
``_comm_thread_baton_mixin.get_my_turn`` (``next_action_owner == agent_id``) --
there is no product notion anywhere in that path; a comm thread is not owned
by a product at all. This proves it: two agents, each doing comm-thread work
"for" a different product's project, park on ``get_my_turn`` concurrently,
and a directed post to ONE of them must wake only that one -- the other keeps
waiting out its own timeout untouched.

Follows the established MCP-boundary wake fixture
(``test_be9296a_await_my_turn_mcp_boundary.py``): one rolled-back ``db_session``
shared by the tool dispatch and the test's own writes, so a write here is
observable by the parked call without needing genuinely separate connections
(the wake signal itself, not DB commit visibility, is what is being proven).
"""

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
    """(client_factory, tenant_key, service) -- ONE tenant, meant to host two
    agents each nominally "belonging" to a different product's work. The wake
    machinery itself has no product concept, which is exactly the invariant
    under test."""
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
    """Agent A (product-A work) and agent B (product-B work) both park on
    ``get_my_turn`` at the same time. A directed post to A must wake ONLY
    A -- B's call is still in flight when A's resolves, and B's own eventual
    wake must be a timeout, not a signal meant for A."""
    client_factory, tenant_key, service = two_product_wake_client
    thread_a = await _thread_with_worker(service, tenant_key, "product-A work", "agent-a")
    # agent-b also needs a thread to join so it is a real participant on this
    # tenant, but this test never posts to it -- only thread_a's id matters.
    await _thread_with_worker(service, tenant_key, "product-B work", "agent-b")

    async with client_factory() as client_a, client_factory() as client_b:
        call_a = asyncio.create_task(client_a.call_tool("get_my_turn", {"agent_id": "agent-a", "wait_seconds": 10}))
        call_b = asyncio.create_task(client_b.call_tool("get_my_turn", {"agent_id": "agent-b", "wait_seconds": 1}))

        # Let both register as parked waiters before signalling either.
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

    # Agent B was never signalled -- it must time out, not pick up A's wake,
    # and must carry no trace of thread A.
    assert body_b["woken"] is False
    assert body_b["wake_reason"] == "timeout"
    assert body_b["agent_id"] == "agent-b"
    assert thread_a not in [t["thread_id"] for t in body_b.get("threads", [])]


async def test_get_my_turn_for_one_agent_never_surfaces_the_others_directed_thread(two_product_wake_client):
    """The poll-based sibling of the above, without the wait: two agents each
    with their own pending directed post must each see only their own."""
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
