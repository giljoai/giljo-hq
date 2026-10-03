# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.services.orchestrator_prompt_ws_broadcast import (
    EVENT_TYPE,
    broadcast_orchestrator_prompt_generated,
)


pytestmark = pytest.mark.asyncio


class _SpyManager:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def broadcast_to_tenant(self, tenant_key: str, event_type: str, data: dict) -> None:
        self.calls.append({"tenant_key": tenant_key, "event_type": event_type, "data": data})


def _dead_socket_manager(tenant_key: str):
    from unittest.mock import AsyncMock as _AsyncMock
    from unittest.mock import MagicMock as _MagicMock

    from fastapi import WebSocketDisconnect

    from api.websocket import WebSocketManager

    manager = WebSocketManager()
    socket = _MagicMock()
    socket.send_text = _AsyncMock(side_effect=WebSocketDisconnect(code=1006))
    manager.active_connections["dead-client"] = socket
    manager.tenant_connections[tenant_key] = {"dead-client"}
    return manager


async def test_emits_the_canonical_event_type_scoped_to_the_tenant():
    spy = _SpyManager()
    await broadcast_orchestrator_prompt_generated(spy, tenant_key="tenant-a", project_id="p1", orchestrator_id="o1")

    assert len(spy.calls) == 1
    assert spy.calls[0]["event_type"] == EVENT_TYPE == "orchestrator:prompt_generated"
    assert spy.calls[0]["tenant_key"] == "tenant-a"


async def test_always_present_keys_are_always_present():
    spy = _SpyManager()
    await broadcast_orchestrator_prompt_generated(spy, tenant_key="t", project_id="p1", orchestrator_id="o1")

    data = spy.calls[0]["data"]
    assert data["project_id"] == "p1"
    assert data["orchestrator_id"] == "o1"
    assert data["thin_client"] is True


async def test_none_optional_keys_are_omitted_not_sent_as_null():
    spy = _SpyManager()
    await broadcast_orchestrator_prompt_generated(
        spy,
        tenant_key="t",
        project_id="p1",
        orchestrator_id="o1",
        agent_id=None,
        execution_id=None,
        estimated_tokens=None,
        tool=None,
        timestamp=None,
        product_id=None,
    )

    data = spy.calls[0]["data"]
    for omitted in ("agent_id", "execution_id", "estimated_tokens", "tool", "timestamp", "product_id"):
        assert omitted not in data, f"{omitted!r} was None and must be omitted, not sent as null: {data!r}"


async def test_supplied_optional_keys_are_included():
    spy = _SpyManager()
    await broadcast_orchestrator_prompt_generated(
        spy,
        tenant_key="t",
        project_id="p1",
        orchestrator_id="o1",
        agent_id="a1",
        execution_id="e1",
        estimated_tokens=931,
        tool="claude-code",
        timestamp="2026-08-02T00:00:00+00:00",
        product_id="prod-1",
    )

    assert spy.calls[0]["data"] == {
        "project_id": "p1",
        "orchestrator_id": "o1",
        "thin_client": True,
        "agent_id": "a1",
        "execution_id": "e1",
        "estimated_tokens": 931,
        "tool": "claude-code",
        "timestamp": "2026-08-02T00:00:00+00:00",
        "product_id": "prod-1",
    }


async def test_estimated_tokens_zero_is_still_sent():
    spy = _SpyManager()
    await broadcast_orchestrator_prompt_generated(
        spy, tenant_key="t", project_id="p1", orchestrator_id="o1", estimated_tokens=0
    )

    assert spy.calls[0]["data"]["estimated_tokens"] == 0


async def test_no_manager_is_a_silent_no_op():
    await broadcast_orchestrator_prompt_generated(None, tenant_key="t", project_id="p1", orchestrator_id="o1")


async def test_a_delivery_failure_never_fails_the_staging():
    manager = _dead_socket_manager("t")

    await broadcast_orchestrator_prompt_generated(manager, tenant_key="t", project_id="p1", orchestrator_id="o1")

    assert "dead-client" not in manager.active_connections, "the dead client was attempted and evicted"
