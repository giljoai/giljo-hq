# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import secrets
from unittest.mock import MagicMock

import bcrypt
import pytest_asyncio
from httpx import ASGITransport
from httpx import AsyncClient as HTTPXAsyncClient


_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_agent_coordination():
    yield


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_context_module():
    yield


@pytest_asyncio.fixture(scope="function")
async def api_client(db_manager):
    from api.app import app
    from api.app_state import state
    from giljo_mcp.auth import AuthManager
    from giljo_mcp.auth.dependencies import get_db_session
    from giljo_mcp.tenant import TenantManager

    async def mock_get_db_session():
        async with db_manager.get_session_async() as session:
            yield session

    app.dependency_overrides[get_db_session] = mock_get_db_session

    state.db_manager = db_manager
    app.state.db_manager = db_manager
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()

    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)
    app.state.tool_accessor = state.tool_accessor

    mock_config = MagicMock()
    mock_config.jwt.secret_key = "test_secret_key"
    mock_config.jwt.algorithm = "HS256"
    mock_config.jwt.expiration_minutes = 30
    mock_config.get = MagicMock(
        side_effect=lambda key, default=None: {
            "security.auth_enabled": True,
            "security.api_keys_required": False,
        }.get(key, default)
    )

    state.config = mock_config
    app.state.config = mock_config

    app.state.auth = AuthManager(mock_config, db=None)
    state.auth = app.state.auth

    transport = ASGITransport(app=app)
    async with HTTPXAsyncClient(
        transport=transport,
        base_url="http://test",
        cookies=None,
        follow_redirects=True,
    ) as client:
        client.cookies.clear()
        yield client
        client.cookies.clear()

    app.dependency_overrides.clear()
    if hasattr(app.state, "auth"):
        del app.state.auth


@pytest_asyncio.fixture(scope="function")
async def auth_headers(db_manager, api_client) -> dict:

    from uuid import uuid4

    from giljo_mcp.auth.jwt_manager import JWTManager
    from giljo_mcp.models import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    async with db_manager.get_session_async() as session:
        unique_suffix = uuid4().hex[:8]
        username = f"test_user_{unique_suffix}"

        tenant_key = TenantManager.generate_tenant_key()

        password_hash = bcrypt.hashpw(b"test_password", bcrypt.gensalt()).decode("utf-8")

        org = Organization(
            name=f"Test Org {unique_suffix}",
            slug=f"test-org-{unique_suffix}",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(org)
        await session.flush()

        user = User(
            username=username,
            email=f"test_{unique_suffix}@example.com",
            password_hash=password_hash,
            tenant_key=tenant_key,
            role="developer",
            org_id=org.id,
        )
        session.add(user)
        await session.commit()

        token = JWTManager.create_access_token(
            user_id=user.id,
            username=user.username,
            role="developer",
            tenant_key=user.tenant_key,
        )

        return {
            "Cookie": f"access_token={token}; csrf_token={_TEST_CSRF_TOKEN}",
            "X-CSRF-Token": _TEST_CSRF_TOKEN,
        }
