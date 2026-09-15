# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import bcrypt
import jwt
import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.auth import MCPSession
from tests.api.test_be9035d_harness_capture_and_stamp import (  # noqa: E402
    _initialize_body,
    _StateCapturingApp,
)
from tests.api.test_mcp_session import _drive_middleware_with_body  # noqa: E402


pytestmark = pytest.mark.asyncio

CANONICAL_MCP_URI = "http://test/mcp"
JWT_SECRET = "test_secret_key"
JWT_ALG = "HS256"


@pytest_asyncio.fixture
async def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    yield JWT_SECRET


def _make_jwt(*, tenant_key: str, sub: str) -> str:
    return jwt.encode(
        {
            "sub": sub,
            "username": "oauth_user",
            "role": "developer",
            "tenant_key": tenant_key,
            "type": "access",
            "aud": CANONICAL_MCP_URI,
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        JWT_SECRET,
        algorithm=JWT_ALG,
    )


async def _seed_oauth_user(db_manager) -> tuple[str, str]:
    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tenant_key = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        org = Organization(
            name=f"OAuth Org {unique}", slug=f"oauth-org-{unique}", tenant_key=tenant_key, is_active=True
        )
        session.add(org)
        await session.flush()
        user = User(
            id=str(uuid4()),
            username=f"oauth_user_{unique}",
            email=f"oauth_{unique}@example.com",
            password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode("utf-8"),
            tenant_key=tenant_key,
            role="developer",
            org_id=org.id,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        return tenant_key, user.id


async def _oauth_initialize(db_manager, *, tenant_key: str, user_id: str, client_name: str = "claude-code"):
    from api.app_state import state
    from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

    token = _make_jwt(tenant_key=tenant_key, sub=user_id)
    prior_db = state.db_manager
    state.db_manager = db_manager
    try:
        inner = _StateCapturingApp()
        mw = MCPAuthMiddleware(app=inner)
        status, headers, _body = await _drive_middleware_with_body(
            mw,
            headers=[
                (b"authorization", f"Bearer {token}".encode()),
                (b"content-type", b"application/json"),
            ],
            body=_initialize_body(client_name),
        )
        return status, headers, inner
    finally:
        state.db_manager = prior_db


async def _session_rows(db_manager, tenant_key: str) -> list[MCPSession]:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        with tenant_session_context(session, tenant_key):
            rows = await session.execute(select(MCPSession).where(MCPSession.tenant_key == tenant_key))
            return list(rows.scalars().all())


async def test_an_oauth_initialize_persists_a_session_row(db_manager, jwt_env):
    tenant_key, user_id = await _seed_oauth_user(db_manager)

    status, _headers, inner = await _oauth_initialize(db_manager, tenant_key=tenant_key, user_id=user_id)

    assert status == 200, f"OAuth initialize was rejected ({status}) — this test is about the row, not auth"
    assert inner.called is True
    rows = await _session_rows(db_manager, tenant_key)
    assert len(rows) == 1, "an OAuth initialize must mint exactly one mcp_sessions row"


async def test_the_oauth_row_carries_no_api_key_and_binds_the_user(db_manager, jwt_env):
    tenant_key, user_id = await _seed_oauth_user(db_manager)

    await _oauth_initialize(db_manager, tenant_key=tenant_key, user_id=user_id)

    rows = await _session_rows(db_manager, tenant_key)
    assert len(rows) == 1
    assert rows[0].api_key_id is None
    assert rows[0].user_id == user_id
    assert rows[0].tenant_key == tenant_key


async def test_the_connected_tool_survives_a_reload(db_manager, jwt_env):
    from giljo_mcp.repositories.auth_repository import AuthRepository

    tenant_key, user_id = await _seed_oauth_user(db_manager)

    await _oauth_initialize(db_manager, tenant_key=tenant_key, user_id=user_id, client_name="claude-code")

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        with tenant_session_context(session, tenant_key):
            harnesses = await AuthRepository().connected_harnesses(session, tenant_key)
    assert "claude-code" in harnesses, f"OAuth connection left no durable harness: {harnesses}"


async def test_a_non_initialize_oauth_request_mints_nothing(db_manager, jwt_env):
    from tests.api.test_mcp_session import _jsonrpc_body

    tenant_key, user_id = await _seed_oauth_user(db_manager)
    token = _make_jwt(tenant_key=tenant_key, sub=user_id)

    from api.app_state import state
    from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

    prior_db = state.db_manager
    state.db_manager = db_manager
    try:
        mw = MCPAuthMiddleware(app=_StateCapturingApp())
        await _drive_middleware_with_body(
            mw,
            headers=[
                (b"authorization", f"Bearer {token}".encode()),
                (b"content-type", b"application/json"),
            ],
            body=_jsonrpc_body("tools/list"),
        )
    finally:
        state.db_manager = prior_db

    assert await _session_rows(db_manager, tenant_key) == []
