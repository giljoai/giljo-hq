# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import json

from giljo_mcp.services.agent_wake_registry import get_wake_registry
from giljo_mcp.services.comm_thread_service import CommThreadService

from tests.integration.test_be9296a_await_my_turn_mcp_boundary import wake_mcp_client  # noqa: F401


PARK_SECONDS = 1
WAKE_DEADLINE_SECONDS = 2.0


def _payload(result) -> dict:
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            return json.loads(text)
    raise AssertionError("tool returned no content")


async def _thread(service: CommThreadService, tenant_key: str, *, joiners: tuple[str, ...] = ()) -> str:
    created = await service.create_thread(subject="be9388", creator_id="em", tenant_key=tenant_key)
    thread_id = created["thread_id"]
    for agent in joiners:
        await service.join_thread(thread_id=thread_id, participant_id=agent, tenant_key=tenant_key)
    return thread_id


async def _await_turn(client_factory, agent_id: str, *, timeout: int = PARK_SECONDS) -> dict:
    async with client_factory() as client:
        result = await client.call_tool("get_my_turn", {"agent_id": agent_id, "wait_seconds": timeout})
    assert result.is_error is False
    return _payload(result)




async def test_a_resolved_thread_holding_the_all_baton_does_not_block_the_park(wake_mcp_client):  # noqa: F811
    client_factory, tenant_key, service = wake_mcp_client
    thread_id = await _thread(service, tenant_key, joiners=("worker-1",))
    await service.pass_baton(thread_id=thread_id, to="all", tenant_key=tenant_key)
    await service.post_to_thread(
        thread_id=thread_id, content="done", from_agent="em", set_status="resolved", tenant_key=tenant_key
    )

    body = await _await_turn(client_factory, "worker-1")

    assert body["wake_reason"] == "timeout", "a resolved thread must not hold anybody's turn"
    assert body["woken"] is False
    assert thread_id not in [t["thread_id"] for t in body["threads"]]


async def test_a_resolved_thread_holding_a_named_baton_does_not_block_the_park(wake_mcp_client):  # noqa: F811
    client_factory, tenant_key, service = wake_mcp_client
    thread_id = await _thread(service, tenant_key, joiners=("worker-1",))
    await service.pass_baton(thread_id=thread_id, to="worker-1", tenant_key=tenant_key)
    await service.post_to_thread(
        thread_id=thread_id, content="done", from_agent="em", set_status="closed", tenant_key=tenant_key
    )

    body = await _await_turn(client_factory, "worker-1")

    assert body["wake_reason"] == "timeout"
    assert thread_id not in [t["thread_id"] for t in body["threads"]]


async def test_b_an_all_baton_does_not_reach_an_agent_who_never_joined(wake_mcp_client):  # noqa: F811
    client_factory, tenant_key, service = wake_mcp_client
    thread_id = await _thread(service, tenant_key, joiners=("worker-1",))
    await service.pass_baton(thread_id=thread_id, to="all", tenant_key=tenant_key)

    body = await _await_turn(client_factory, "stranger-1")

    assert body["wake_reason"] == "timeout", "'all' must mean all participants, not every agent in the tenant"
    assert body["count"] == 0
    assert body["threads"] == []


async def test_c_a_standing_all_baton_does_not_pre_empt_a_participants_park(wake_mcp_client):  # noqa: F811
    client_factory, tenant_key, service = wake_mcp_client
    thread_id = await _thread(service, tenant_key, joiners=("worker-1",))
    await service.pass_baton(thread_id=thread_id, to="all", tenant_key=tenant_key)

    body = await _await_turn(client_factory, "worker-1")

    assert body["wake_reason"] == "timeout", "a standing 'all' baton must not disable the park"
    assert body["woken"] is False
    assert thread_id in [t["thread_id"] for t in body["threads"]]




async def test_a_named_baton_still_wakes_instantly(wake_mcp_client):  # noqa: F811
    client_factory, tenant_key, service = wake_mcp_client
    thread_id = await _thread(service, tenant_key, joiners=("worker-1",))
    await service.pass_baton(thread_id=thread_id, to="worker-1", tenant_key=tenant_key)

    body = await asyncio.wait_for(_await_turn(client_factory, "worker-1", timeout=30), WAKE_DEADLINE_SECONDS)

    assert body["wake_reason"] == "already_pending"
    assert body["woken"] is True
    assert body["waited_seconds"] == 0
    assert thread_id in [t["thread_id"] for t in body["threads"]]


async def test_a_directed_action_still_wakes_instantly(wake_mcp_client):  # noqa: F811
    client_factory, tenant_key, service = wake_mcp_client
    thread_id = await _thread(service, tenant_key, joiners=("worker-1", "worker-2"))
    await service.post_to_thread(
        thread_id=thread_id,
        content="please review",
        from_agent="em",
        to_participant="worker-1",
        requires_action=True,
        tenant_key=tenant_key,
    )
    await service.pass_baton(thread_id=thread_id, to="worker-2", tenant_key=tenant_key)

    body = await asyncio.wait_for(_await_turn(client_factory, "worker-1", timeout=30), WAKE_DEADLINE_SECONDS)

    assert body["wake_reason"] == "already_pending"
    assert [d["thread_id"] for d in body["directed_action"]] == [thread_id]


async def test_a_real_all_handoff_still_wakes_a_parked_participant_instantly(wake_mcp_client):  # noqa: F811
    client_factory, tenant_key, service = wake_mcp_client
    thread_id = await _thread(service, tenant_key, joiners=("worker-1",))

    async with client_factory() as client:
        read_done = asyncio.Event()
        original_get_my_turn = service.get_my_turn

        async def _instrumented(**kwargs):
            result = await original_get_my_turn(**kwargs)
            read_done.set()
            return result

        service.get_my_turn = _instrumented  # type: ignore[method-assign]
        call = asyncio.create_task(client.call_tool("get_my_turn", {"agent_id": "worker-1", "wait_seconds": 10}))
        await asyncio.wait_for(read_done.wait(), timeout=WAKE_DEADLINE_SECONDS)
        assert get_wake_registry().waiter_count(tenant_key) >= 1, "waiter read but never parked"

        await service.pass_baton(thread_id=thread_id, to="all", tenant_key=tenant_key)
        result = await asyncio.wait_for(call, timeout=WAKE_DEADLINE_SECONDS)

    body = _payload(result)
    assert body["woken"] is True
    assert body["wake_reason"] == "signalled", "a fresh 'all' hand-off must still reach a parked participant"
    assert thread_id in [t["thread_id"] for t in body["threads"]]


async def test_the_three_observed_threads_replayed_together(wake_mcp_client):  # noqa: F811
    client_factory, tenant_key, service = wake_mcp_client

    resolved_a = await _thread(service, tenant_key, joiners=("worker-1",))
    still_open = await _thread(service, tenant_key, joiners=("retired-lane-1", "retired-lane-2"))
    resolved_b = await _thread(service, tenant_key, joiners=("worker-1",))

    for thread_id in (resolved_a, still_open, resolved_b):
        await service.pass_baton(thread_id=thread_id, to="all", tenant_key=tenant_key)
    for thread_id in (resolved_a, resolved_b):
        await service.post_to_thread(
            thread_id=thread_id, content="wrapping up", from_agent="em", set_status="resolved", tenant_key=tenant_key
        )

    body = await _await_turn(client_factory, "fresh-agent-with-no-work")

    assert body["wake_reason"] == "timeout"
    assert body["woken"] is False
    assert body["count"] == 0, "three abandoned 'all' batons must not hold a fresh agent's turn"


async def test_the_idle_payload_is_empty_rather_than_urgent_looking(wake_mcp_client):  # noqa: F811
    client_factory, tenant_key, service = wake_mcp_client
    await _thread(service, tenant_key, joiners=("worker-1",))

    body = await _await_turn(client_factory, "worker-1")

    assert body["woken"] is False
    assert body["wake_reason"] == "timeout"
    assert body["count"] == 0
    assert body["directed_action"] == []
