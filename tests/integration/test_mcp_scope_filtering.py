# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Boundary regression tests for API-0021b — scope-aware MCP tool gating.

Per the CLAUDE.md mandatory rule (BE-5042 lesson), tests live at the layer the
constraint lives. Scope gating is enforced at the FastMCP transport boundary
(tools/list filter + tools/call dispatch gate) and at the MCPAuthMiddleware
ASGI layer where the scope claim is decoded into request state. Tests:

- S1: MCPAuthMiddleware stamps `auth_method="jwt"` + `scopes=[...]` for an
  aud-bound JWT carrying a `scope` claim.
- S2: MCPAuthMiddleware stamps `auth_method="jwt"` + default scopes
  ["mcp:read", "mcp:write"] for a JWT with NO scope claim (legacy/cookie
  path).
- S3: MCPAuthMiddleware stamps `auth_method="api_key"` for the API-key path.
- S4: tools/list with token scope = {mcp:read} advertises ONLY mcp:read tools.
- S5: tools/list with token scope = {mcp:read, mcp:write} advertises read+write
  but NOT mcp:agent tools.
- S6: tools/list with API-key auth (bypass) advertises ALL tools incl. agent.
- S7: tools/call against an mcp:write tool with mcp:read-only token returns
  ToolError (defense-in-depth, not just hiding).
- S8: tools/call against an mcp:agent tool with mcp:read+mcp:write token
  returns ToolError.
- S9: tools/call with API-key auth (bypass) succeeds for agent-scope tools.
- S10: OAuth `/authorize` now ACCEPTS `mcp:agent` (BE-6168) but still rejects
  any non-grantable token.
- S11: OAuthService.exchange_code_for_token forwards `auth_code.scope` into
  the issued JWT's `scope` claim.
- S12: TOOL_SCOPES registry-completeness — every registered FastMCP tool has
  an entry, and every entry resolves to a registered tool.
- S13 (BE-6168): an OAuth token granted `mcp:agent` reaches API-key parity —
  sees AND can dispatch the agent-lifecycle tools.
- S14 (BE-6167): `get_staging_instructions` is `mcp:agent` — a read/write-only
  token cannot drive its BE-5122 self-close (project -> COMPLETED) write.
- S15 (BE-6168 guard): every state-mutating orchestration tool maps to
  `mcp:agent` (a mis-map to read/write fails OPEN).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import bcrypt
import jwt
import pytest
import pytest_asyncio

from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


CANONICAL_MCP_URI = "http://test/mcp"
JWT_SECRET = "test_secret_key"
JWT_ALG = "HS256"


# ---------------------------------------------------------------------------
# Helpers (mirror the API-0021a transport-driver pattern)
# ---------------------------------------------------------------------------


def _make_jwt(
    *,
    aud: str | None,
    tenant_key: str,
    scope: str | None = None,
    sub: str | None = None,
) -> str:
    sub_value = sub or str(uuid4())
    payload: dict = {
        "sub": sub_value,
        "username": "scope_test_user",
        "role": "developer",
        "tenant_key": tenant_key,
        "type": "access",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    if aud is not None:
        payload["aud"] = aud
    if scope is not None:
        payload["scope"] = scope
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


class _CapturingInnerApp:
    """ASGI app that records the scope state set by MCPAuthMiddleware."""

    def __init__(self) -> None:
        self.called: bool = False
        self.scope_state: dict | None = None

    async def __call__(self, scope, receive, send) -> None:
        self.called = True
        self.scope_state = dict(scope.get("state", {}))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"OK"})


async def _drive_middleware(middleware, headers: list[tuple[bytes, bytes]]) -> tuple[int, dict, bytes]:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "method": "POST",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
        "scheme": "http",
        "root_path": "",
    }

    captured_status: dict = {"code": 0}
    captured_headers: dict[str, str] = {}
    captured_body = bytearray()

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message) -> None:
        if message["type"] == "http.response.start":
            captured_status["code"] = message["status"]
            for k, v in message.get("headers", []):
                key = k.decode("latin-1") if isinstance(k, bytes) else k
                val = v.decode("latin-1") if isinstance(v, bytes) else v
                captured_headers[key.lower()] = val
        elif message["type"] == "http.response.body":
            captured_body.extend(message.get("body", b""))

    await middleware(scope, receive, send)
    return captured_status["code"], captured_headers, bytes(captured_body)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    yield JWT_SECRET


@pytest_asyncio.fixture
async def mcp_canonical_uri_env(monkeypatch):
    monkeypatch.setenv("GILJO_MCP_CANONICAL_URI", CANONICAL_MCP_URI)
    yield CANONICAL_MCP_URI


@pytest_asyncio.fixture
async def scope_mcp_client(db_manager, monkeypatch):
    """In-memory MCP client that lets each test pin a scope set / auth method.

    Returns (new_client, scope_holder). scope_holder.scopes is the value
    `_scopes_from_request` will return for every request — None for API-key
    bypass, a set for JWT, empty set for empty-scope.
    """
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from giljo_mcp.tenant import TenantManager
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)
    state.tool_accessor = accessor

    class _ScopeHolder:
        scopes: set[str] | None = None

    holder = _ScopeHolder()

    # BE-6042d: _scopes_from_request is read by the scope-filter/gate functions
    # that stayed in mcp_sdk_server (transport layer) — patch it there. But
    # _resolve_tenant/_resolve_user_id moved with _call_tool into mcp_tools._base,
    # so the in-memory-transport monkeypatch for those must target _base.
    from api.endpoints.mcp_tools import _base

    monkeypatch.setattr(
        mcp_sdk_server,
        "_scopes_from_request",
        lambda _request: holder.scopes,
    )
    monkeypatch.setattr(
        _base,
        "_resolve_tenant",
        lambda ctx: tenant_key,
    )
    monkeypatch.setattr(
        _base,
        "_resolve_user_id",
        lambda ctx: None,
    )

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, holder
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


# ---------------------------------------------------------------------------
# S1-S3: MCPAuthMiddleware stamps auth_method + scopes onto scope[state]
# ---------------------------------------------------------------------------


class TestS1JwtWithScopeClaimStampsScopes:
    @pytest.mark.asyncio
    async def test_aud_bound_jwt_with_scope_claim_propagates_scopes_to_state(
        self, jwt_env, mcp_canonical_uri_env, monkeypatch
    ):
        from api import app_state as _app_state_mod
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware
        from giljo_mcp.tenant import TenantManager

        # SEC-3001a: is_user_active skips when db_manager is None — ensure
        # isolation so DB state from other tests doesn't contaminate this test.
        monkeypatch.setattr(_app_state_mod.state, "db_manager", None)
        tenant_key = TenantManager.generate_tenant_key()
        token = _make_jwt(aud=CANONICAL_MCP_URI, tenant_key=tenant_key, scope="mcp:read mcp:write")

        inner = _CapturingInnerApp()
        mw = MCPAuthMiddleware(app=inner)
        status, _headers, _body = await _drive_middleware(mw, headers=[(b"authorization", f"Bearer {token}".encode())])

        assert status == 200, f"JWT auth returned {status}"
        assert inner.scope_state is not None
        assert inner.scope_state.get("auth_method") == "jwt"
        assert inner.scope_state.get("scopes") == ["mcp:read", "mcp:write"]


class TestS2JwtMissingScopeClaimDefaultsToReadWrite:
    @pytest.mark.asyncio
    async def test_jwt_without_scope_claim_defaults_to_read_write(self, jwt_env, mcp_canonical_uri_env, monkeypatch):
        from api import app_state as _app_state_mod
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware
        from giljo_mcp.tenant import TenantManager

        # SEC-3001a: is_user_active skips when db_manager is None — ensure
        # isolation so DB state from other tests doesn't contaminate this test.
        monkeypatch.setattr(_app_state_mod.state, "db_manager", None)
        tenant_key = TenantManager.generate_tenant_key()
        # API-0022: aud-less tokens are now hard-rejected at /mcp. Test only
        # the missing-scope-claim default; aud must be present and canonical.
        token = _make_jwt(aud=CANONICAL_MCP_URI, tenant_key=tenant_key, scope=None)

        inner = _CapturingInnerApp()
        mw = MCPAuthMiddleware(app=inner)
        status, _headers, _body = await _drive_middleware(mw, headers=[(b"authorization", f"Bearer {token}".encode())])

        assert status == 200
        assert inner.scope_state.get("auth_method") == "jwt"
        assert inner.scope_state.get("scopes") == ["mcp:read", "mcp:write"]


class TestS3ApiKeyStampsApiKeyAuthMethod:
    @pytest.mark.asyncio
    async def test_api_key_path_stamps_auth_method_api_key(self, db_manager, jwt_env):
        from api.app_state import state
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware
        from giljo_mcp.api_key_utils import hash_api_key
        from giljo_mcp.models.auth import APIKey, User
        from giljo_mcp.models.organizations import Organization
        from giljo_mcp.tenant import TenantManager

        tenant_key = TenantManager.generate_tenant_key()
        unique = uuid4().hex[:8]
        raw_key = f"gk_apikeyS3_{uuid4().hex}"
        key_hash = hash_api_key(raw_key)

        async with db_manager.get_session_async() as session:
            org = Organization(
                name=f"S3 Org {unique}",
                slug=f"s3-org-{unique}",
                tenant_key=tenant_key,
                is_active=True,
            )
            session.add(org)
            await session.flush()
            user = User(
                username=f"s3_user_{unique}",
                email=f"s3_{unique}@example.com",
                password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode("utf-8"),
                tenant_key=tenant_key,
                role="developer",
                org_id=org.id,
                is_active=True,
            )
            session.add(user)
            await session.flush()
            api_key = APIKey(
                id=str(uuid4()),
                tenant_key=tenant_key,
                user_id=user.id,
                name=f"S3 Key {unique}",
                key_hash=key_hash,
                key_prefix=f"{raw_key[:12]}...",
                permissions=["*"],
                is_active=True,
                created_at=datetime.now(UTC),
            )
            session.add(api_key)
            await session.commit()

        prior_db_manager = state.db_manager
        state.db_manager = db_manager
        try:
            inner = _CapturingInnerApp()
            mw = MCPAuthMiddleware(app=inner)
            status, _headers, _body = await _drive_middleware(mw, headers=[(b"x-api-key", raw_key.encode())])
            assert status == 200, f"API key auth returned {status}"
            assert inner.scope_state.get("auth_method") == "api_key"
            # Per design, API-key path leaves scopes unset (bypass).
            assert "scopes" not in inner.scope_state or inner.scope_state.get("scopes") is None
        finally:
            state.db_manager = prior_db_manager


# ---------------------------------------------------------------------------
# S4-S6: tools/list filter at the FastMCP transport boundary
# ---------------------------------------------------------------------------


class TestS4ListToolsReadOnlyToken:
    @pytest.mark.asyncio
    async def test_read_only_token_advertises_only_read_tools(self, scope_mcp_client):
        from api.endpoints.mcp_sdk_server import TOOL_SCOPES

        new_client, holder = scope_mcp_client
        holder.scopes = {"mcp:read"}

        async with new_client() as session:
            result = await session.list_tools()

        advertised = {t.name for t in result.tools}
        expected = {name for name, scope in TOOL_SCOPES.items() if scope == "mcp:read"}
        assert advertised == expected, (
            f"read-only token saw {advertised - expected} extra and missed {expected - advertised}"
        )


class TestS5ListToolsReadWriteToken:
    @pytest.mark.asyncio
    async def test_read_write_token_advertises_read_and_write_no_agent(self, scope_mcp_client):
        from api.endpoints.mcp_sdk_server import TOOL_SCOPES

        new_client, holder = scope_mcp_client
        holder.scopes = {"mcp:read", "mcp:write"}

        async with new_client() as session:
            result = await session.list_tools()

        advertised = {t.name for t in result.tools}
        expected = {name for name, scope in TOOL_SCOPES.items() if scope in {"mcp:read", "mcp:write"}}
        agent_tools = {name for name, scope in TOOL_SCOPES.items() if scope == "mcp:agent"}
        assert advertised == expected
        assert advertised.isdisjoint(agent_tools), (
            f"agent tools leaked into read+write advertise: {advertised & agent_tools}"
        )


class TestS6ListToolsApiKeyBypass:
    @pytest.mark.asyncio
    async def test_api_key_bypass_advertises_all_tools(self, scope_mcp_client):
        from api.endpoints.mcp_sdk_server import TOOL_SCOPES

        new_client, holder = scope_mcp_client
        holder.scopes = None  # API-key bypass

        async with new_client() as session:
            result = await session.list_tools()

        advertised = {t.name for t in result.tools}
        assert advertised == set(TOOL_SCOPES.keys()), f"API-key client missing {set(TOOL_SCOPES.keys()) - advertised}"
        # Ensure at least one mcp:agent tool is present (defense vs accidental
        # bypass-bypass).
        agent_tools = {name for name, scope in TOOL_SCOPES.items() if scope == "mcp:agent"}
        assert agent_tools.issubset(advertised), f"API-key bypass missed agent tools: {agent_tools - advertised}"


# ---------------------------------------------------------------------------
# S7-S9: tools/call dispatch gate (defense-in-depth)
# ---------------------------------------------------------------------------


class TestS7CallToolReadOnlyTokenAgainstWriteToolFails:
    @pytest.mark.asyncio
    async def test_read_only_token_call_write_tool_returns_error(self, scope_mcp_client):
        new_client, holder = scope_mcp_client
        holder.scopes = {"mcp:read"}

        async with new_client() as session:
            # `create_project` is mcp:write — must be rejected for a read-only token
            result = await session.call_tool(
                "create_project",
                {"name": "should not be created", "description": "test"},
            )

        assert result.is_error is True
        text_blocks = [getattr(b, "text", "") for b in result.content]
        joined = "\n".join(text_blocks)
        assert "not authorized" in joined or "scope" in joined.lower()


class TestS8CallToolReadWriteTokenAgainstAgentToolFails:
    @pytest.mark.asyncio
    async def test_read_write_token_call_agent_tool_returns_error(self, scope_mcp_client):
        new_client, holder = scope_mcp_client
        holder.scopes = {"mcp:read", "mcp:write"}

        async with new_client() as session:
            # `spawn_job` is mcp:agent — must be rejected for read+write token
            result = await session.call_tool(
                "spawn_job",
                {
                    "project_id": str(uuid4()),
                    "agent_name": "implementer",
                    "mission": "test",
                },
            )

        assert result.is_error is True
        text_blocks = [getattr(b, "text", "") for b in result.content]
        joined = "\n".join(text_blocks)
        assert "not authorized" in joined or "scope" in joined.lower()


class TestS9CallToolApiKeyBypassAllowsAgentTool:
    @pytest.mark.asyncio
    async def test_api_key_bypass_does_not_block_agent_tool_dispatch(self, scope_mcp_client):
        """Bypass means the gate doesn't reject; downstream tool may still error
        for missing args/state, but the rejection text must NOT mention scope.
        """
        new_client, holder = scope_mcp_client
        holder.scopes = None  # bypass

        async with new_client() as session:
            result = await session.call_tool(
                "get_workflow_status",
                {"project_id": str(uuid4())},
            )

        # The call may succeed (empty workflow) OR fail (missing project) — both
        # are fine; what must NOT happen is a scope-rejection error.
        text_blocks = [getattr(b, "text", "") for b in result.content]
        joined = "\n".join(text_blocks)
        assert "not authorized for this token's scope" not in joined


# ---------------------------------------------------------------------------
# S10: OAuth /authorize rejects mcp:agent
# ---------------------------------------------------------------------------


class TestS10AuthorizeAcceptsAgentScope:
    """BE-6168: OAuth /authorize now ACCEPTS `mcp:agent` (was rejected pre-6168).

    OAuth is the default auth method, so an OAuth client must reach API-key
    parity. The boundary rule lives in OAuthService._validate_scope_string; the
    HTTP-layer mirror is in tests/api/test_oauth_audience_binding.py.
    """

    @pytest.mark.asyncio
    async def test_validate_authorize_request_accepts_mcp_agent_scope(self, db_session):
        from giljo_mcp.services.oauth_service import (
            BUILTIN_CLIENT_ID,
            OAUTH_GRANTABLE_SCOPES,
            OAuthService,
        )

        service = OAuthService(db_session=db_session)
        # Must NOT raise — mcp:agent is grantable as of BE-6168.
        await service.validate_authorize_request(
            client_id=BUILTIN_CLIENT_ID,
            redirect_uri="http://localhost:8080/callback",
            code_challenge="E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            code_challenge_method="S256",
            response_type="code",
            scope="mcp:read mcp:write mcp:agent",
            tenant_key="tk_scope_filter_test",
        )
        assert "mcp:agent" in OAUTH_GRANTABLE_SCOPES

    @pytest.mark.asyncio
    async def test_validate_authorize_request_still_rejects_unknown_scope(self, db_session):
        """The grantable-set guard still bites: a bogus token is rejected."""
        from giljo_mcp.services.oauth_service import BUILTIN_CLIENT_ID, OAuthService

        service = OAuthService(db_session=db_session)
        with pytest.raises(ValueError, match="non-grantable"):
            await service.validate_authorize_request(
                client_id=BUILTIN_CLIENT_ID,
                redirect_uri="http://localhost:8080/callback",
                code_challenge="E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
                code_challenge_method="S256",
                response_type="code",
                scope="mcp:read mcp:superuser",
                tenant_key="tk_scope_filter_test",
            )

    @pytest.mark.asyncio
    async def test_validate_authorize_request_accepts_default_scope(self, db_session):
        from giljo_mcp.services.oauth_service import (
            BUILTIN_CLIENT_ID,
            DEFAULT_OAUTH_SCOPE,
            OAuthService,
        )

        service = OAuthService(db_session=db_session)
        # Should not raise.
        await service.validate_authorize_request(
            client_id=BUILTIN_CLIENT_ID,
            redirect_uri="http://localhost:8080/callback",
            code_challenge="E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            code_challenge_method="S256",
            response_type="code",
            scope=DEFAULT_OAUTH_SCOPE,
            tenant_key="tk_scope_filter_test",
        )


# ---------------------------------------------------------------------------
# S11: OAuthService.exchange_code_for_token forwards scope to JWT
# ---------------------------------------------------------------------------


class TestS11ExchangeForwardsScopeIntoJwt:
    @pytest.mark.asyncio
    async def test_auth_code_scope_is_baked_into_jwt(self, db_manager, db_session, jwt_env):
        from giljo_mcp.auth.jwt_manager import JWTManager
        from giljo_mcp.models.auth import User
        from giljo_mcp.models.oauth import OAuthAuthorizationCode
        from giljo_mcp.models.organizations import Organization
        from giljo_mcp.services.oauth_service import BUILTIN_CLIENT_ID, OAuthService
        from giljo_mcp.tenant import TenantManager

        tenant_key = TenantManager.generate_tenant_key()
        unique = uuid4().hex[:8]

        org = Organization(
            name=f"S11 Org {unique}",
            slug=f"s11-org-{unique}",
            tenant_key=tenant_key,
            is_active=True,
        )
        db_session.add(org)
        await db_session.flush()
        user = User(
            username=f"s11_user_{unique}",
            email=f"s11_{unique}@example.com",
            password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode("utf-8"),
            tenant_key=tenant_key,
            role="developer",
            org_id=org.id,
            is_active=True,
        )
        db_session.add(user)
        await db_session.flush()

        # Build a real S256 challenge for a known verifier
        import base64
        import hashlib

        verifier = "test_pkce_verifier_with_enough_entropy_to_satisfy_validation"
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

        code = f"test_code_{uuid4().hex}"
        auth_code = OAuthAuthorizationCode(
            code=code,
            client_id=BUILTIN_CLIENT_ID,
            user_id=str(user.id),
            tenant_key=tenant_key,
            redirect_uri="http://localhost:8080/callback",
            code_challenge=challenge,
            code_challenge_method="S256",
            scope="mcp:read mcp:write",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            used=False,
        )
        db_session.add(auth_code)
        await db_session.commit()

        service = OAuthService(db_session=db_session)
        result = await service.exchange_code_for_token(
            code=code,
            client_id=BUILTIN_CLIENT_ID,
            code_verifier=verifier,
            redirect_uri="http://localhost:8080/callback",
            audience=CANONICAL_MCP_URI,
        )

        decoded = JWTManager.verify_token(result["access_token"], expected_audience=CANONICAL_MCP_URI)
        assert decoded.get("scope") == "mcp:read mcp:write"


# ---------------------------------------------------------------------------
# S12: TOOL_SCOPES registry-completeness regression
# ---------------------------------------------------------------------------


class TestS12RegistryCompleteness:
    @pytest.mark.asyncio
    async def test_every_registered_tool_has_a_scope_entry(self):
        from api.endpoints import mcp_sdk_server

        tools = await mcp_sdk_server._orig_list_tools()
        registered_names = {t.name for t in tools}
        registry_names = set(mcp_sdk_server.TOOL_SCOPES.keys())

        missing = registered_names - registry_names
        orphaned = registry_names - registered_names

        assert not missing, f"tools registered without TOOL_SCOPES entry: {sorted(missing)}"
        assert not orphaned, f"TOOL_SCOPES entries with no registered tool: {sorted(orphaned)}"

    def test_every_scope_value_is_one_of_three_canonical_strings(self):
        from api.endpoints.mcp_sdk_server import TOOL_SCOPES

        valid = {"mcp:read", "mcp:write", "mcp:agent"}
        invalid = {name: scope for name, scope in TOOL_SCOPES.items() if scope not in valid}
        assert not invalid, f"invalid scope values: {invalid}"


# ---------------------------------------------------------------------------
# S13 (BE-6168): an OAuth token GRANTED mcp:agent reaches API-key parity —
# it both sees AND can dispatch the agent-lifecycle tools.
# ---------------------------------------------------------------------------


class TestS13OAuthAgentScopeReachesParity:
    @pytest.mark.asyncio
    async def test_agent_scoped_token_advertises_agent_tools(self, scope_mcp_client):
        from api.endpoints.mcp_sdk_server import TOOL_SCOPES

        new_client, holder = scope_mcp_client
        holder.scopes = {"mcp:read", "mcp:write", "mcp:agent"}

        async with new_client() as session:
            result = await session.list_tools()

        advertised = {t.name for t in result.tools}
        # Parity: an agent-scoped token sees the WHOLE surface (read+write+agent).
        assert advertised == set(TOOL_SCOPES.keys()), (
            f"agent-scoped token missing {set(TOOL_SCOPES.keys()) - advertised}"
        )
        # And specifically the agent-lifecycle tools the API-0021b boundary used
        # to hide from every OAuth client.
        for agent_tool in ("spawn_job", "post_to_thread", "launch_implementation", "get_staging_instructions"):
            assert agent_tool in advertised, f"agent-scoped token did not see {agent_tool}"

    @pytest.mark.asyncio
    async def test_agent_scoped_token_can_dispatch_agent_tool(self, scope_mcp_client):
        """The dispatch gate must NOT scope-reject an agent tool for an
        agent-scoped token (it may still error downstream on missing state —
        that is fine; what must not appear is the scope-rejection text)."""
        new_client, holder = scope_mcp_client
        holder.scopes = {"mcp:read", "mcp:write", "mcp:agent"}

        async with new_client() as session:
            result = await session.call_tool(
                "spawn_job", {"project_id": str(uuid4()), "agent_name": "implementer", "mission": "parity probe"}
            )

        text_blocks = [getattr(b, "text", "") for b in result.content]
        joined = "\n".join(text_blocks)
        assert "not authorized for this token's scope" not in joined


# ---------------------------------------------------------------------------
# S14 (BE-6167): get_staging_instructions is now mcp:agent — a read/write-only
# token CANNOT drive its BE-5122 self-close (project -> COMPLETED) write.
# ---------------------------------------------------------------------------


class TestS14StagingInstructionsIsAgentScoped:
    def test_get_staging_instructions_is_agent_scope(self):
        from api.endpoints.mcp_sdk_server import SCOPE_AGENT, TOOL_SCOPES

        assert TOOL_SCOPES["get_staging_instructions"] == SCOPE_AGENT, (
            "BE-6167: get_staging_instructions writes project.status=COMPLETED via "
            "the BE-5122 CTX self-close path; a read-scoped token must not reach it"
        )

    @pytest.mark.asyncio
    async def test_read_write_token_cannot_call_get_staging_instructions(self, scope_mcp_client):
        new_client, holder = scope_mcp_client
        # The strongest case: even a read+WRITE token (no agent) is rejected,
        # so the self-close write is unreachable without the agent grant.
        holder.scopes = {"mcp:read", "mcp:write"}

        async with new_client() as session:
            result = await session.call_tool("get_staging_instructions", {"job_id": str(uuid4())})

        assert result.is_error is True
        text_blocks = [getattr(b, "text", "") for b in result.content]
        joined = "\n".join(text_blocks)
        assert "not authorized" in joined or "scope" in joined.lower()


# ---------------------------------------------------------------------------
# S15 (BE-6168 guard): every state-mutating orchestration tool maps to
# mcp:agent. TOOL_SCOPES is the WHOLE boundary; a mis-map to read/write fails
# OPEN (a read-only OAuth token could then mutate orchestration state). This
# curated set is the canonical orchestration-mutation surface from the
# API-0021b audit; adding a new such tool without mcp:agent fails this test.
# ---------------------------------------------------------------------------


class TestS15StateMutatingToolsAreAgentScoped:
    STATE_MUTATING_ORCHESTRATION_TOOLS = frozenset(
        {
            "spawn_job",
            "complete_job",
            "close_job",
            # BE-9012b (BE-6225e): reactivate_job + dismiss_reactivation merged.
            "resolve_reactivation",
            "report_progress",
            "set_agent_status",
            "update_job_mission",
            "update_project_mission",
            "stage_project",
            "implement_project",
            "launch_implementation",
            "get_staging_instructions",  # BE-6167: mutates via BE-5122 self-close
            # BE-9012d: send_message / receive_messages hard-removed (bus retired).
            "create_thread",
            "join_thread",
            "post_to_thread",
            "pass_baton",
            "request_approval",
            "write_project_closeout",
            "write_memory_entry",
        }
    )

    def test_orchestration_mutation_tools_all_require_agent_scope(self):
        from api.endpoints.mcp_sdk_server import SCOPE_AGENT, TOOL_SCOPES

        mismapped = {
            name: TOOL_SCOPES.get(name)
            for name in self.STATE_MUTATING_ORCHESTRATION_TOOLS
            if TOOL_SCOPES.get(name) != SCOPE_AGENT
        }
        assert not mismapped, f"state-mutating orchestration tools NOT mapped to mcp:agent (fails OPEN): {mismapped}"
