# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import select

from giljo_mcp import harness_resolver
from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.auth import MCPSession
from tests.api.test_be9035d_harness_capture_and_stamp import _initialize_body, _StateCapturingApp  # noqa: E402
from tests.api.test_be9586c_oauth_session_row import (  # noqa: E402
    CANONICAL_MCP_URI,
    JWT_ALG,
    JWT_SECRET,
    _seed_oauth_user,
    jwt_env,  # noqa: F401  (fixture re-export)
)
from tests.api.test_be9586d_discover_mints_session_row import _discover_body  # noqa: E402
from tests.api.test_mcp_session import _drive_middleware_with_body  # noqa: E402


pytestmark = pytest.mark.asyncio

REGISTERED_URL = "https://connector.example.com/oauth/client-metadata.json"
UNREGISTERED_URL = "https://other.example.com/oauth/client-metadata.json"


def _token(*, tenant_key: str, user_id: str, cid: str | None) -> str:
    claims = {
        "sub": user_id,
        "username": "oauth_user",
        "role": "developer",
        "tenant_key": tenant_key,
        "type": "access",
        "aud": CANONICAL_MCP_URI,
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    if cid is not None:
        claims["cid"] = cid
    return jwt.encode(claims, JWT_SECRET, algorithm=JWT_ALG)


async def _drive(db_manager, *, tenant_key: str, user_id: str, cid: str | None, body: bytes):
    from api.app_state import state
    from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

    prior = state.db_manager
    state.db_manager = db_manager
    try:
        status, _headers, _body = await _drive_middleware_with_body(
            MCPAuthMiddleware(app=_StateCapturingApp()),
            headers=[
                (b"authorization", f"Bearer {_token(tenant_key=tenant_key, user_id=user_id, cid=cid)}".encode()),
                (b"content-type", b"application/json"),
                (b"mcp-protocol-version", b"2026-07-28" if b"server/discover" in body else b"2025-06-18"),
            ],
            body=body,
        )
        return status
    finally:
        state.db_manager = prior


async def _session_data(db_manager, tenant_key: str) -> dict:
    async with db_manager.get_session_async(tenant_key=tenant_key) as s:
        with tenant_session_context(s, tenant_key):
            rows = (await s.execute(select(MCPSession).where(MCPSession.tenant_key == tenant_key))).scalars().all()
    assert len(rows) == 1
    return rows[0].session_data


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setitem(harness_resolver.CIMD_CLIENT_HARNESSES, REGISTERED_URL, harness_resolver.HARNESS_CODEX)


async def test_a_registered_cimd_client_id_names_the_harness(db_manager, jwt_env, registry):  # noqa: F811
    tenant_key, user_id = await _seed_oauth_user(db_manager)

    status = await _drive(
        db_manager, tenant_key=tenant_key, user_id=user_id, cid=REGISTERED_URL, body=_initialize_body("mystery-app")
    )

    assert status == 200
    data = await _session_data(db_manager, tenant_key)
    assert data["resolved_harness"] == harness_resolver.HARNESS_CODEX
    assert data["oauth_client_id"] == REGISTERED_URL


async def test_the_client_id_outranks_a_clientinfo_that_claims_another_harness(db_manager, jwt_env, registry):  # noqa: F811
    tenant_key, user_id = await _seed_oauth_user(db_manager)

    await _drive(
        db_manager, tenant_key=tenant_key, user_id=user_id, cid=REGISTERED_URL, body=_initialize_body("claude-code")
    )

    assert (await _session_data(db_manager, tenant_key))["resolved_harness"] == harness_resolver.HARNESS_CODEX


async def test_an_unregistered_cimd_client_id_falls_back_to_clientinfo(db_manager, jwt_env, registry):  # noqa: F811
    tenant_key, user_id = await _seed_oauth_user(db_manager)

    await _drive(
        db_manager, tenant_key=tenant_key, user_id=user_id, cid=UNREGISTERED_URL, body=_initialize_body("claude-code")
    )

    data = await _session_data(db_manager, tenant_key)
    assert data["resolved_harness"] == harness_resolver.HARNESS_CLAUDE_CODE
    assert data["oauth_client_id"] == UNREGISTERED_URL


async def test_a_token_without_a_client_id_is_unchanged(db_manager, jwt_env, registry):  # noqa: F811
    tenant_key, user_id = await _seed_oauth_user(db_manager)

    await _drive(db_manager, tenant_key=tenant_key, user_id=user_id, cid=None, body=_initialize_body("opencode"))

    data = await _session_data(db_manager, tenant_key)
    assert data["resolved_harness"] == harness_resolver.HARNESS_OPENCODE
    assert data.get("oauth_client_id") is None


async def test_a_discover_frame_carries_the_client_id_too(db_manager, jwt_env, registry):  # noqa: F811
    tenant_key, user_id = await _seed_oauth_user(db_manager)

    await _drive(
        db_manager, tenant_key=tenant_key, user_id=user_id, cid=REGISTERED_URL, body=_discover_body("mystery-app")
    )

    data = await _session_data(db_manager, tenant_key)
    assert data["resolved_harness"] == harness_resolver.HARNESS_CODEX


async def test_the_connect_page_reads_the_same_harness(db_manager, jwt_env, registry):  # noqa: F811
    from giljo_mcp.repositories.auth_repository import AuthRepository

    tenant_key, user_id = await _seed_oauth_user(db_manager)
    await _drive(
        db_manager, tenant_key=tenant_key, user_id=user_id, cid=REGISTERED_URL, body=_initialize_body("mystery-app")
    )

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        with tenant_session_context(session, tenant_key):
            harnesses = await AuthRepository().connected_harnesses(session, tenant_key)
    assert list(harnesses) == [harness_resolver.HARNESS_CODEX]


@pytest.mark.parametrize(
    ("url", "harness"),
    [
        ("https://claude.ai/oauth/claude-code-client-metadata", harness_resolver.HARNESS_CLAUDE_CODE),
        ("https://claude.ai/oauth/mcp-oauth-client-metadata", harness_resolver.GENERIC_HARNESS),
        ("https://chatgpt.com/oauth/client.json", harness_resolver.GENERIC_HARNESS),
        ("https://chatgpt.com/oauth/codex/client.json", harness_resolver.HARNESS_CODEX),
        ("https://vscode.dev/oauth/client-metadata.json", harness_resolver.GENERIC_HARNESS),
        ("https://insiders.vscode.dev/oauth/client-metadata.json", harness_resolver.GENERIC_HARNESS),
        ("https://opencode.ai/oauth/opencode/client.json", harness_resolver.HARNESS_OPENCODE),
        ("https://cursor.com/oauth/mcp-client.json", harness_resolver.GENERIC_HARNESS),
        ("https://chatgpt.com/oauth/abc123-DEF_9/client.json", harness_resolver.GENERIC_HARNESS),
        ("https://chatgpt.com/oauth/codex/abc123-DEF_9/client.json", harness_resolver.HARNESS_CODEX),
    ],
)
async def test_the_shipped_registry_rows(url, harness):
    assert harness_resolver.harness_from_oauth_client_id(url) == harness


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "https://claude.ai/oauth/claude-code-client-metadata/",
        "https://CLAUDE.ai/oauth/claude-code-client-metadata",
        "http://claude.ai/oauth/claude-code-client-metadata",
        "https://evil.example.com/https://claude.ai/oauth/claude-code-client-metadata",
        "https://chatgpt.com/oauth/a/b/client.json",
        "https://chatgpt.com/oauth//client.json",
        "https://chatgpt.com.evil.test/oauth/abc/client.json",
        "https://chatgpt.com/oauth/abc/client.json?x=1",
        "https://chatgpt.com/oauth/codex/a/b/client.json",
    ],
)
async def test_lookalike_urls_resolve_to_nothing(url):
    assert harness_resolver.harness_from_oauth_client_id(url) is None
