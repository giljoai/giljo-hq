# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_chain_context_sequence_broadcast_does_not_hide_a_bug():
    from giljo_mcp.services.sequence_chain_context import SequenceChainContextResolver

    ws = MagicMock()
    ws.broadcast_event_to_tenant = AsyncMock(side_effect=ValueError("event.data must be a dictionary"))
    resolver = SequenceChainContextResolver(db_manager=None, tenant_manager=None, websocket_manager=ws)
    with pytest.raises(ValueError):
        await resolver._broadcast_sequence_updated("run-1", "tk")


@pytest.mark.asyncio
async def test_memory_event_emit_does_not_hide_a_bug():
    from giljo_mcp.tools._memory_helpers import emit_websocket_event

    ws = MagicMock()
    ws.broadcast_to_tenant = AsyncMock(side_effect=TypeError("unexpected keyword"))
    with (
        patch("giljo_mcp.app_registry.service_registry.get_websocket_manager", return_value=ws),
        pytest.raises(TypeError),
    ):
        await emit_websocket_event("product:memory:updated", "tk", "p1", {})
