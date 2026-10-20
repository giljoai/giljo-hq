# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from api.exception_handlers import register_exception_handlers
from api.middleware.auth import AuthMiddleware
from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.auth_manager import AuthManager
from giljo_mcp.database import DatabaseManager
from giljo_mcp.tenant import TenantManager
from tests.helpers.test_db_helper import PostgreSQLTestHelper


pytestmark = pytest.mark.asyncio

SERVER_BUSY_BODY = {"error_code": "SERVER_BUSY", "message": "The server is busy. Try again in a moment."}


@pytest.fixture
async def held_pool():
    manager = DatabaseManager(
        PostgreSQLTestHelper.get_test_db_url(), is_async=True, pool_size=1, max_overflow=0, pool_timeout=1
    )
    async with manager.get_session_async() as holder:
        await holder.execute(text("SELECT 1"))
        assert manager.async_engine.pool.checkedout() == 1
        yield manager
    await manager.close_async()


async def test_jwt_check_pool_timeout_is_server_busy_with_retry_after(held_pool):
    auth = AuthManager(MagicMock(), db=None)
    app = FastAPI()
    register_exception_handlers(app)
    app.state.db_manager = held_pool
    app.add_middleware(AuthMiddleware, auth_manager=lambda: auth)
    reached: list[str] = []

    @app.get("/api/v1/projects/")
    async def list_projects():
        reached.append("route")
        return {"projects": ["must never be served"]}

    token = JWTManager.create_access_token(
        user_id=uuid.uuid4(), username="inf9810", role="admin", tenant_key=TenantManager.generate_tenant_key()
    )
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/projects/", headers={"authorization": f"Bearer {token}"})

    assert response.status_code == 503, response.text
    assert response.json() == SERVER_BUSY_BODY
    assert response.headers.get("retry-after") == "5"
    assert reached == []
