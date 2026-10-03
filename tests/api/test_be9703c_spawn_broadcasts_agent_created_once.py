# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.dependencies.websocket import get_websocket_dependency
from api.endpoints.agent_jobs import lifecycle
from api.endpoints.agent_jobs.dependencies import get_orchestration_service
from giljo_mcp.auth.dependencies import get_current_active_user


@pytest.mark.asyncio
async def test_the_spawn_endpoint_does_not_broadcast_a_second_agent_created():
    service = MagicMock()
    service.spawn_job = AsyncMock(
        return_value=SimpleNamespace(
            job_id="j1", agent_id="a1", execution_id="e1", agent_prompt="p", mission_stored=True, thin_client=True
        )
    )
    ws_dep = MagicMock()
    ws_dep.broadcast_to_tenant = AsyncMock()

    app = FastAPI()
    app.include_router(lifecycle.router, prefix="/api/agent-jobs")
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(
        username="admin", role="admin", tenant_key="tk"
    )
    app.dependency_overrides[get_orchestration_service] = lambda: service
    app.dependency_overrides[get_websocket_dependency] = lambda: ws_dep

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/agent-jobs/spawn",
            json={"agent_display_name": "impl", "mission": "m", "project_id": "p1"},
        )
    assert response.status_code == 201, response.text
    ws_dep.broadcast_to_tenant.assert_not_awaited()
