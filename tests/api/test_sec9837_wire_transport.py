# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import base64
import json
import secrets
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text

from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from tests.api.test_oauth_refresh import (
    _bcrypt_hash,
    _generate_pkce_pair,
    _install_confidential_resolver,
    _seed_user_and_code,
)


pytestmark = pytest.mark.asyncio

MCP_URL = "http://test/mcp"
_REDIRECT = "http://localhost:3000/callback"
_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


@asynccontextmanager
async def mcp_wire(db_manager):
    from mcp.server.streamable_http_manager import StreamableHTTPASGIApp

    from api.app_state import state
    from api.endpoints.mcp_sdk_server import _STREAMABLE_HTTP_KWARGS, MCPAuthMiddleware, mcp

    prior = state.db_manager
    state.db_manager = db_manager
    mcp.streamable_http_app(**_STREAMABLE_HTTP_KWARGS)
    try:
        async with mcp.session_manager.run():
            transport = httpx.ASGITransport(app=MCPAuthMiddleware(StreamableHTTPASGIApp(mcp.session_manager)))
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                yield client
    finally:
        state.db_manager = prior


async def _connect(api_client, db_manager) -> dict:
    verifier, challenge = _generate_pkce_pair()
    code_value = secrets.token_urlsafe(64)
    client_id = str(uuid4())
    secret = secrets.token_urlsafe(48)
    tenant_key = await _seed_user_and_code(db_manager, challenge=challenge, code_value=code_value, client_id=client_id)
    restore = _install_confidential_resolver((client_id, _bcrypt_hash(secret), [_REDIRECT]))
    try:
        response = await api_client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code_value,
                "client_id": client_id,
                "code_verifier": verifier,
                "redirect_uri": _REDIRECT,
                "client_secret": secret,
                "resource": MCP_URL,
            },
        )
    finally:
        restore()
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    return {"token": token, "claims": claims, "tenant_key": tenant_key, "client_id": client_id}


async def _login_row(db_manager, tenant_key: str):
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        result = await session.execute(text("SELECT * FROM oauth_logins WHERE tenant_key = :t"), {"t": tenant_key})
        return result.mappings().all()


def _rpc(method: str, params: dict | None = None, rid: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}


async def _post(client, token: str, payload: dict, extra: dict | None = None) -> httpx.Response:
    headers = {**_HEADERS, "Authorization": f"Bearer {token}", "User-Agent": "WireAgent/7.1", **(extra or {})}
    return await client.post("/mcp", json=payload, headers=headers)


async def test_an_oauth_call_over_the_real_transport_is_recorded_and_logout_ends_it(api_client, db_manager):
    app = await _connect(api_client, db_manager)
    tenant_key, token = app["tenant_key"], app["token"]
    assert app["claims"].get("fid"), "the access token must carry its refresh family (fid)"

    async with mcp_wire(db_manager) as wire:
        init = await _post(
            wire,
            token,
            _rpc(
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "wire-test-client", "version": "4.5.6"},
                },
            ),
        )
        assert init.status_code == 200, init.text

        (login,) = await _login_row(db_manager, tenant_key)
        assert login["client_name"] == "DCR Confidential Test Client"
        assert login["client_id"] == app["client_id"]
        assert login["last_ip"] == "127.0.0.1"
        assert login["last_user_agent"] == "WireAgent/7.1"
        assert login["last_mcp_client_name"] == "wire-test-client"
        assert login["last_mcp_client_version"] == "4.5.6"
        assert login["last_used_at"] is not None

        listed = await _post(wire, token, _rpc("tools/list", rid=2))
        assert listed.status_code == 200, listed.text

        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            product = Product(id=str(uuid4()), name="Wire Product", tenant_key=tenant_key, is_active=True)
            session.add(product)
            await session.flush()
            project = Project(
                id=str(uuid4()),
                tenant_key=tenant_key,
                product_id=product.id,
                name="Wire Project",
                description="x",
                mission="x",
                status="active",
                series_number=4242,
            )
            session.add(project)
            product_id, project_id = product.id, project.id
        await _post(
            wire,
            token,
            _rpc("tools/call", {"name": "get_workflow_status", "arguments": {"project_id": project_id}}, rid=3),
        )
        (login,) = await _login_row(db_manager, tenant_key)
        assert login["last_product_id"] == product_id

        await _post(
            wire,
            token,
            _rpc("tools/call", {"name": "get_workflow_status", "arguments": {"project_id": str(uuid4())}}, rid=4),
        )
        (login,) = await _login_row(db_manager, tenant_key)
        assert login["last_product_id"] == product_id

        from giljo_mcp.database import tenant_session_context
        from giljo_mcp.services import oauth_login_service

        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            with tenant_session_context(session, tenant_key):
                (shown,) = await oauth_login_service.list_connected_apps(
                    session, tenant_key=tenant_key, user_id=login["user_id"]
                )
        assert shown.last_product_name == "Wire Product"
        assert shown.mcp_client_version == "4.5.6"

        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            with tenant_session_context(session, tenant_key):
                await oauth_login_service.log_out_app(
                    session, tenant_key=tenant_key, user_id=login["user_id"], login_id=login["id"]
                )
        refused = await _post(wire, token, _rpc("tools/list", rid=5))
        assert refused.status_code == 401, refused.text
