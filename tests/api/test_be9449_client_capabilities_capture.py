# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from uuid import uuid4

import bcrypt
import pytest
from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from tests.api.test_mcp_session import (  # noqa: E402
    _drive_middleware_with_body,
    _jsonrpc_body,
    _seed_api_key,
)


_CANONICAL_AUD = "http://test/mcp"

_DECLARED_CAPABILITIES = {
    "elicitation": {},
    "roots": {"listChanged": True},
    "sampling": {},
    "experimental": {"vendorPrivate": {"nested": [1, 2, 3]}},
    "anUndeclaredTopLevelKey": "must survive verbatim",
}

_CLIENT_INFO = {"name": "test-harness", "version": "9.9.9"}


class _CapturingProbe:

    async def __call__(self, scope, receive, send) -> None:
        await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b'{"jsonrpc":"2.0","id":1,"result":{}}'})


@pytest.fixture
def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    return "test_secret_key"


async def _read_session_data(db_manager, tenant_key: str, session_id: str) -> dict:
    from giljo_mcp.models import MCPSession

    async with db_manager.get_session_async() as db:
        with tenant_session_context(db, tenant_key):
            row = (await db.execute(select(MCPSession).where(MCPSession.session_id == session_id))).scalar_one()
            return row.session_data


def _initialize_params(capabilities: object = _DECLARED_CAPABILITIES) -> dict:
    return {
        "protocolVersion": "2025-06-18",
        "capabilities": capabilities,
        "clientInfo": dict(_CLIENT_INFO),
    }


async def _initialize_over_api_key(db_manager, raw_key: str, params: dict) -> str:
    from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

    status, headers, _body = await _drive_middleware_with_body(
        MCPAuthMiddleware(app=_CapturingProbe()),
        headers=[(b"x-api-key", raw_key.encode()), (b"content-type", b"application/json")],
        body=_jsonrpc_body("initialize", params=params),
    )
    assert status == 200, f"initialize returned {status}"
    session_id = headers.get("mcp-session-id")
    assert session_id, "initialize must issue Mcp-Session-Id"
    return session_id


async def _seed_jwt_user(db_manager) -> tuple[str, str, str]:
    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]

    async with db_manager.get_session_async(tenant_key=tk) as session:
        org = Organization(
            name=f"BE9449 Org {unique}",
            slug=f"be9449-org-{unique}",
            tenant_key=tk,
            is_active=True,
        )
        session.add(org)
        await session.flush()

        user = User(
            id=str(uuid4()),
            username=f"be9449_user_{unique}",
            email=f"be9449_{unique}@example.com",
            password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode("utf-8"),
            tenant_key=tk,
            role="developer",
            org_id=org.id,
            is_active=True,
        )
        session.add(user)
        await session.commit()

    return user.id, user.username, tk


def _mint_jwt(*, user_id: str, username: str, tenant_key: str) -> str:
    from giljo_mcp.auth.jwt_manager import JWTManager

    return JWTManager.create_access_token(
        user_id=user_id,
        username=username,
        role="developer",
        tenant_key=tenant_key,
        audience=_CANONICAL_AUD,
        scope="mcp:read mcp:write",
    )


async def _initialize_over_jwt(db_manager, token: str, params: dict) -> str:
    from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

    status, headers, _body = await _drive_middleware_with_body(
        MCPAuthMiddleware(app=_CapturingProbe()),
        headers=[
            (b"authorization", f"Bearer {token}".encode()),
            (b"host", b"test"),
            (b"content-type", b"application/json"),
        ],
        body=_jsonrpc_body("initialize", params=params),
    )
    assert status == 200, f"JWT initialize returned {status}"
    session_id = headers.get("mcp-session-id")
    assert session_id, "JWT initialize must issue Mcp-Session-Id"
    return session_id




class TestCapturedAtTheApiKeyMint:

    @pytest.mark.asyncio
    async def test_declared_capabilities_land_verbatim(self, db_manager, jwt_env):
        from api.app_state import state

        raw_key, tenant_key = await _seed_api_key(db_manager)

        prior_db = state.db_manager
        state.db_manager = db_manager
        try:
            session_id = await _initialize_over_api_key(db_manager, raw_key, _initialize_params())
            session_data = await _read_session_data(db_manager, tenant_key, session_id)

            assert session_data.get("client_capabilities") == _DECLARED_CAPABILITIES, (
                "BE-9449: the capabilities the client declared at initialize were not captured "
                "verbatim into session_data['client_capabilities']. Initialize is the only moment "
                "this is ever knowable -- a 2025-era tools/call carries neither clientInfo nor "
                "capabilities, and the live fleet is 2025-era."
            )
        finally:
            state.db_manager = prior_db

    @pytest.mark.asyncio
    async def test_undeclared_nested_key_survives_the_round_trip(self, db_manager, jwt_env):
        from api.app_state import state

        raw_key, tenant_key = await _seed_api_key(db_manager)

        prior_db = state.db_manager
        state.db_manager = db_manager
        try:
            session_id = await _initialize_over_api_key(db_manager, raw_key, _initialize_params())
            captured = (await _read_session_data(db_manager, tenant_key, session_id)).get("client_capabilities") or {}

            assert captured.get("anUndeclaredTopLevelKey") == "must survive verbatim", (
                "BE-9449: an undeclared top-level capability key did not survive to session_data. "
                "A filtered capture would hide exactly what this field exists to observe."
            )
            assert captured.get("experimental", {}).get("vendorPrivate", {}).get("nested") == [1, 2, 3], (
                "BE-9449: a nested undeclared structure did not survive to session_data verbatim."
            )
        finally:
            state.db_manager = prior_db

    @pytest.mark.asyncio
    async def test_elicitation_is_readable_from_the_captured_row(self, db_manager, jwt_env):
        from api.app_state import state

        raw_key, tenant_key = await _seed_api_key(db_manager)

        prior_db = state.db_manager
        state.db_manager = db_manager
        try:
            session_id = await _initialize_over_api_key(db_manager, raw_key, _initialize_params())
            session_data = await _read_session_data(db_manager, tenant_key, session_id)

            assert "elicitation" in (session_data.get("client_capabilities") or {}), (
                "BE-9449 / BE-9440: a client that declared elicitation support at initialize must be "
                "readable as such from the persisted session row."
            )
        finally:
            state.db_manager = prior_db


class TestCapturedAtTheJwtMint:

    @pytest.mark.asyncio
    async def test_declared_capabilities_land_verbatim_over_jwt(self, db_manager, jwt_env):
        from api.app_state import state

        user_id, username, tenant_key = await _seed_jwt_user(db_manager)
        token = _mint_jwt(user_id=user_id, username=username, tenant_key=tenant_key)

        prior_db = state.db_manager
        state.db_manager = db_manager
        try:
            session_id = await _initialize_over_jwt(db_manager, token, _initialize_params())
            session_data = await _read_session_data(db_manager, tenant_key, session_id)

            assert session_data.get("client_capabilities") == _DECLARED_CAPABILITIES, (
                "BE-9449: the JWT mint path did not capture the declared capabilities. The API-key "
                "path passing is not sufficient evidence -- these are two independent mint sites."
            )
        finally:
            state.db_manager = prior_db




class TestUnchangedBehaviour:
    @pytest.mark.asyncio
    async def test_existing_capture_keys_still_land(self, db_manager, jwt_env):
        from api.app_state import state

        raw_key, tenant_key = await _seed_api_key(db_manager)

        prior_db = state.db_manager
        state.db_manager = db_manager
        try:
            session_id = await _initialize_over_api_key(db_manager, raw_key, _initialize_params())
            session_data = await _read_session_data(db_manager, tenant_key, session_id)

            assert session_data.get("client_info") == _CLIENT_INFO
            assert session_data.get("resolved_harness") == "generic"
            assert session_data.get("resolved_preset") is None
            assert session_data.get("protocol_version") == "2025-06-18"
        finally:
            state.db_manager = prior_db

    @pytest.mark.asyncio
    async def test_existing_empty_capabilities_key_is_untouched(self, db_manager, jwt_env):
        from api.app_state import state

        raw_key, tenant_key = await _seed_api_key(db_manager)

        prior_db = state.db_manager
        state.db_manager = db_manager
        try:
            session_id = await _initialize_over_api_key(db_manager, raw_key, _initialize_params())
            session_data = await _read_session_data(db_manager, tenant_key, session_id)

            assert session_data.get("capabilities") == {}, (
                "BE-9449 explicitly does NOT fill the pre-existing 'capabilities' key. If this is "
                "now populated, the client's declared capabilities have been merged into Giljo's "
                "own derived capability vector -- two different meanings in one JSONB field."
            )
        finally:
            state.db_manager = prior_db

    @pytest.mark.asyncio
    async def test_initialize_without_any_capabilities_still_creates_a_session(self, db_manager, jwt_env):
        from api.app_state import state

        raw_key, tenant_key = await _seed_api_key(db_manager)
        params = {"protocolVersion": "2025-06-18", "clientInfo": dict(_CLIENT_INFO)}

        prior_db = state.db_manager
        state.db_manager = db_manager
        try:
            session_id = await _initialize_over_api_key(db_manager, raw_key, params)
            session_data = await _read_session_data(db_manager, tenant_key, session_id)

            assert session_data.get("client_info") == _CLIENT_INFO
            assert not session_data.get("client_capabilities"), (
                "an initialize declaring no capabilities must not invent one"
            )
        finally:
            state.db_manager = prior_db

    @pytest.mark.asyncio
    async def test_malformed_capabilities_field_does_not_raise(self, db_manager, jwt_env):
        from api.app_state import state

        raw_key, tenant_key = await _seed_api_key(db_manager)

        prior_db = state.db_manager
        state.db_manager = db_manager
        try:
            session_id = await _initialize_over_api_key(
                db_manager, raw_key, _initialize_params(capabilities="not-an-object")
            )
            session_data = await _read_session_data(db_manager, tenant_key, session_id)

            assert session_data.get("client_info") == _CLIENT_INFO, (
                "a malformed capabilities field must not cost the session its clientInfo capture"
            )
            assert not session_data.get("client_capabilities"), (
                "a malformed capabilities field must yield nothing, not a garbage capture"
            )
        finally:
            state.db_manager = prior_db

    @pytest.mark.asyncio
    async def test_undecodable_body_is_still_answered_not_crashed(self, db_manager, jwt_env):
        from api.app_state import state
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

        raw_key, _tenant_key = await _seed_api_key(db_manager)

        prior_db = state.db_manager
        state.db_manager = db_manager
        try:
            status, _headers, _body = await _drive_middleware_with_body(
                MCPAuthMiddleware(app=_CapturingProbe()),
                headers=[(b"x-api-key", raw_key.encode()), (b"content-type", b"application/json")],
                body=b"\xff\xfe not json at all {{{",
            )
            assert status < 500, f"an undecodable body must never 500 out of the transport, got {status}"
        finally:
            state.db_manager = prior_db




class TestPeekHelperContract:

    def test_returns_the_declared_object_verbatim(self):
        from api.endpoints.mcp_transport import _peek_jsonrpc_capabilities

        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": _initialize_params()}).encode(
            "utf-8"
        )
        assert _peek_jsonrpc_capabilities(body) == _DECLARED_CAPABILITIES

    @pytest.mark.parametrize(
        ("body", "why"),
        [
            (b"", "empty body"),
            (b"{not json", "unparseable body"),
            (b"\xff\xfe\x00", "undecodable bytes"),
            (b'["a", "list"]', "payload is not an object"),
            (b'{"params": "not-an-object"}', "params is not an object"),
            (b'{"params": {}}', "no capabilities field"),
            (b'{"params": {"capabilities": "not-an-object"}}', "capabilities is not an object"),
            (b'{"params": {"capabilities": null}}', "capabilities is null"),
        ],
    )
    def test_tolerates_every_malformed_shape_without_raising(self, body, why):
        from api.endpoints.mcp_transport import _peek_jsonrpc_capabilities

        assert _peek_jsonrpc_capabilities(body) is None, f"expected None for {why}"


class TestClientInfoPatchVehicle:

    def test_patch_carries_client_capabilities(self):
        from api.endpoints.mcp_session import _client_info_patch

        patch = _client_info_patch(
            dict(_CLIENT_INFO),
            protocol_version="2025-06-18",
            capabilities=_DECLARED_CAPABILITIES,
        )
        assert patch["client_capabilities"] == _DECLARED_CAPABILITIES

    def test_patch_defaults_the_new_key_to_none(self):
        from api.endpoints.mcp_session import _client_info_patch

        patch = _client_info_patch(dict(_CLIENT_INFO))
        assert patch["client_capabilities"] is None

    def test_the_three_existing_keys_are_unchanged_by_the_addition(self):
        from api.endpoints.mcp_session import _client_info_patch

        patch = _client_info_patch(dict(_CLIENT_INFO), capabilities=_DECLARED_CAPABILITIES)
        assert patch["client_info"] == _CLIENT_INFO
        assert patch["resolved_harness"] == "generic"
        assert patch["resolved_preset"] is None
        assert patch["protocol_version"] is None
