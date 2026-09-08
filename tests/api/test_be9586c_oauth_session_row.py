# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9586c — an OAuth-authenticated MCP connection must leave a durable session row.

THE DEFECT: an OAuth-authenticated MCP connection over ``--transport http``
plus a browser sign-in authenticates and runs tools successfully under the right
tenant, yet leaves no ``mcp_sessions`` row -- while API-key connections do.

The cause is a missing call, not a missing capability. ``create_session`` is
invoked inside the API-key branch only (mcp_auth_middleware, under
``if not tenant_key and api_key_value:``); the JWT branch authenticates through
``validate_principal``, resolves tenant + user, and falls through to the inner app
without ever minting a row. The storage layer has always been ready for it:
``mcp_sessions.api_key_id`` is nullable with the comment "nullable for OAuth JWT
sessions that have no API key", ``create_session`` already declares
``api_key_id: str | None = None``, and the session-resurrect path already branches
on ``api_key_id IS NULL AND user_id = ...``. Somebody built the whole shape and the
call site was never added.

WHAT ACTUALLY BREAKS, which is narrower than "the wizard dot never flips". The
live WS ``setup:tool_connected`` event fires fine for OAuth -- it is announced
outside both auth branches, gated only on ``initialize`` (BE-9498 already fixed
the memo that used to silence OAuth clients). It is the DURABLE half that is
blind: ``auth_repository.connected_harnesses`` derives entirely from
``mcp_sessions`` rows, so the dot flips live and is gone on the next page load.
"Never flips" and "flips then forgets" have different repros, and a fix validated
against the wrong one can look like it works -- hence the reload assertion below
rather than a bare row count.

Failing-layer discipline (CLAUDE.md): these drive a real JSON-RPC ``initialize``
through ``MCPAuthMiddleware`` -- the transport boundary where the branch skips --
and then read the durable surface the operator actually sees.

Edition Scope: Both. OAuth is available in both editions; nothing here is
SaaS-only and no SaaS-only table is referenced.
"""

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
    """An aud-bound access JWT — the shape the browser sign-in mints."""
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
    """A real, ACTIVE user, because validate_principal re-checks both against the DB.

    Returns ``(tenant_key, user_id)``. An OAuth tenant deliberately gets NO api key:
    that absence is the whole point — the row this test wants must be minted without
    one.
    """
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
    """Drive one OAuth-authenticated JSON-RPC initialize through the middleware."""
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
    """THE DEFECT. An OAuth connection currently authenticates and leaves nothing."""
    tenant_key, user_id = await _seed_oauth_user(db_manager)

    status, _headers, inner = await _oauth_initialize(db_manager, tenant_key=tenant_key, user_id=user_id)

    assert status == 200, f"OAuth initialize was rejected ({status}) — this test is about the row, not auth"
    assert inner.called is True
    rows = await _session_rows(db_manager, tenant_key)
    assert len(rows) == 1, "an OAuth initialize must mint exactly one mcp_sessions row"


async def test_the_oauth_row_carries_no_api_key_and_binds_the_user(db_manager, jwt_env):
    """The row must be OAuth-SHAPED, not a borrowed API-key row.

    ``api_key_id`` is NULL because there is no API key — that is what the column's
    nullability was for — and ``user_id`` is what binds it to a principal. The
    resurrect path already branches on exactly this pair, so a row minted any other
    way would be invisible to it.
    """
    tenant_key, user_id = await _seed_oauth_user(db_manager)

    await _oauth_initialize(db_manager, tenant_key=tenant_key, user_id=user_id)

    rows = await _session_rows(db_manager, tenant_key)
    assert len(rows) == 1
    assert rows[0].api_key_id is None
    assert rows[0].user_id == user_id
    assert rows[0].tenant_key == tenant_key


async def test_the_connected_tool_survives_a_reload(db_manager, jwt_env):
    """The operator's actual symptom, at the surface he sees.

    connected_harnesses is derived from mcp_sessions alone, so this is what makes
    the setup wizard's dot and the Connect page's per-tool status outlive the live
    WS event. Asserted through the repository rather than by counting rows: a row
    that exists but whose clientInfo never reached session_data would pass a count
    and still leave the dot blank.
    """
    from giljo_mcp.repositories.auth_repository import AuthRepository

    tenant_key, user_id = await _seed_oauth_user(db_manager)

    await _oauth_initialize(db_manager, tenant_key=tenant_key, user_id=user_id, client_name="claude-code")

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        with tenant_session_context(session, tenant_key):
            harnesses = await AuthRepository().connected_harnesses(session, tenant_key)
    assert "claude-code" in harnesses, f"OAuth connection left no durable harness: {harnesses}"


async def test_a_non_initialize_oauth_request_mints_nothing(db_manager, jwt_env):
    """The negative control, and it guards the BE-9066 invariant.

    One row per CONNECTION, not per request. Without this, a fix that minted on every
    authenticated call would pass all three tests above while re-creating the
    unbounded-growth defect BE-9066 removed.
    """
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
