# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Regression tests for API-0021j Phase 2 — Mcp-Session-Id lifecycle in middleware.

Per the MCP Streamable HTTP spec, the server issues an ``Mcp-Session-Id``
HTTP response header on the successful initialize response. Subsequent
requests SHOULD include that header so the server can re-attach the
session context; an unknown / expired / cross-tenant ID MUST return 404.

FastMCP is configured ``stateless_http=True`` (api/endpoints/mcp_sdk_server.py:42),
so the SDK does not emit the header itself. ``MCPAuthMiddleware`` is the
only layer that can correctly attribute (tenant, user) to a session, so
the lifecycle lives there — backed by the existing ``mcp_sessions`` table
and ``MCPSessionManager``. No new infrastructure.

Failing-layer discipline (per CLAUDE.md): tests drive the ASGI middleware
directly so the boundary that emits / validates the header is the boundary
under test.

Test categories:
- TestInitializeIssuesSessionId: initialize response carries Mcp-Session-Id.
- TestSubsequentRequestValidatesSession: valid id accepted, unknown id 404.
- TestSessionIsTenantScoped: id from tenant A under tenant B credentials → 404.
- TestSessionExtendOnUse: last_accessed updates on subsequent use.
"""

from __future__ import annotations

import contextlib
import json
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import bcrypt
import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.tenant import TenantManager, current_tenant


_SESSION_ID_RE = re.compile(r"^[\x21-\x7E]+$")


class _CapturingInnerApp:
    """ASGI app that records invocation + drains the receive stream."""

    def __init__(self, response_status: int = 200) -> None:
        self.called: bool = False
        self.tenant_key_seen: str | None = None
        self.session_id_seen: str | None = None
        self.body_seen: bytes = b""
        self.response_status = response_status

    async def __call__(self, scope, receive, send) -> None:
        self.called = True
        self.tenant_key_seen = scope.get("state", {}).get("tenant_key")
        # Drain receive so the middleware's body-buffer + replay path is exercised.
        message = await receive()
        self.body_seen = message.get("body", b"")
        # Read header to mirror what a real handler would observe.
        for name, value in scope.get("headers", []):
            key = name.decode("latin-1") if isinstance(name, bytes) else name
            if key.lower() == "mcp-session-id":
                val = value.decode("latin-1") if isinstance(value, bytes) else value
                self.session_id_seen = val
                break
        await send({"type": "http.response.start", "status": self.response_status, "headers": []})
        await send({"type": "http.response.body", "body": b'{"jsonrpc":"2.0","id":1,"result":{}}'})


async def _drive_middleware_with_body(
    middleware,
    headers: list[tuple[bytes, bytes]],
    body: bytes,
    query_string: bytes = b"",
) -> tuple[int, dict[str, str], bytes]:
    """Drive a single ASGI request through ``middleware`` with the given JSON body.

    ``query_string`` mirrors the ASGI key of the same name (BE-9253 uses it to
    drive the ``/mcp?profile=...`` selection vehicle). ASGI carries the query
    separately from ``path``/``raw_path``, so those stay bare.
    """
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "method": "POST",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": query_string,
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
        "scheme": "http",
        "root_path": "",
    }

    captured_status: dict = {"code": 0}
    captured_headers: dict[str, str] = {}
    captured_body = bytearray()
    body_sent = {"done": False}

    async def receive() -> dict:
        if body_sent["done"]:
            return {"type": "http.disconnect"}
        body_sent["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}

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


def _jsonrpc_body(method: str, params: dict | None = None) -> bytes:
    """Build a minimal JSON-RPC 2.0 request body."""
    payload: dict = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        payload["params"] = params
    return json.dumps(payload).encode("utf-8")


@pytest_asyncio.fixture
async def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    yield "test_secret_key"


async def _seed_api_key(db_manager, tenant_key: str | None = None) -> tuple[str, str]:
    """Create an org+user+api_key triplet. Returns ``(raw_api_key, tenant_key)``."""
    from giljo_mcp.api_key_utils import hash_api_key
    from giljo_mcp.models.auth import APIKey, User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tk = tenant_key or TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    raw_key = f"gk_sessionTest_{uuid4().hex}"

    async with db_manager.get_session_async() as session:
        org = Organization(
            name=f"Session Org {unique}",
            slug=f"session-org-{unique}",
            tenant_key=tk,
            is_active=True,
        )
        session.add(org)
        await session.flush()

        user = User(
            username=f"session_user_{unique}",
            email=f"session_{unique}@example.com",
            password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode("utf-8"),
            tenant_key=tk,
            role="developer",
            org_id=org.id,
            is_active=True,
        )
        session.add(user)
        await session.flush()

        api_key = APIKey(
            id=str(uuid4()),
            tenant_key=tk,
            user_id=user.id,
            name=f"Session Key {unique}",
            key_hash=hash_api_key(raw_key),
            key_prefix=f"{raw_key[:12]}...",
            permissions=["*"],
            is_active=True,
            created_at=datetime.now(UTC),
        )
        session.add(api_key)
        await session.commit()

    return raw_key, tk


class TestInitializeIssuesSessionId:
    """The initialize 200 response MUST carry an ``Mcp-Session-Id`` header."""

    @pytest.mark.asyncio
    async def test_initialize_response_has_session_id_header(self, db_manager, jwt_env):
        from api.app_state import state
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

        raw_key, _tenant_key = await _seed_api_key(db_manager)

        prior_db = state.db_manager
        state.db_manager = db_manager
        try:
            inner = _CapturingInnerApp(response_status=200)
            mw = MCPAuthMiddleware(app=inner)

            status, headers, _body = await _drive_middleware_with_body(
                mw,
                headers=[
                    (b"x-api-key", raw_key.encode()),
                    (b"content-type", b"application/json"),
                ],
                body=_jsonrpc_body(
                    "initialize",
                    params={"protocolVersion": "2025-06-18", "capabilities": {}},
                ),
            )

            assert status == 200, f"initialize returned {status}"
            assert inner.called is True, "auth must reach inner app on valid key"
            session_id = headers.get("mcp-session-id")
            assert session_id, f"initialize response missing Mcp-Session-Id: headers={headers!r}"
            # Spec format: printable ASCII without whitespace.
            assert _SESSION_ID_RE.fullmatch(session_id), (
                f"Mcp-Session-Id {session_id!r} is not printable ASCII per spec"
            )
        finally:
            state.db_manager = prior_db


class TestSubsequentRequestValidatesSession:
    """Non-initialize requests with a known id pass; unknown / expired ids → 404."""

    @pytest.mark.asyncio
    async def test_valid_session_id_accepted(self, db_manager, jwt_env):
        from api.app_state import state
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

        raw_key, _tenant_key = await _seed_api_key(db_manager)

        prior_db = state.db_manager
        state.db_manager = db_manager
        try:
            # Step 1: initialize to mint a session id.
            inner = _CapturingInnerApp(response_status=200)
            mw = MCPAuthMiddleware(app=inner)
            _status, init_headers, _body = await _drive_middleware_with_body(
                mw,
                headers=[
                    (b"x-api-key", raw_key.encode()),
                    (b"content-type", b"application/json"),
                ],
                body=_jsonrpc_body(
                    "initialize",
                    params={"protocolVersion": "2025-06-18", "capabilities": {}},
                ),
            )
            session_id = init_headers.get("mcp-session-id")
            assert session_id

            # Step 2: subsequent non-initialize request with the same id.
            inner2 = _CapturingInnerApp(response_status=200)
            mw2 = MCPAuthMiddleware(app=inner2)
            status, _headers, _body = await _drive_middleware_with_body(
                mw2,
                headers=[
                    (b"x-api-key", raw_key.encode()),
                    (b"mcp-protocol-version", b"2025-06-18"),
                    (b"mcp-session-id", session_id.encode("ascii")),
                    (b"content-type", b"application/json"),
                ],
                body=_jsonrpc_body("tools/list"),
            )
            assert status == 200, f"valid session reuse returned {status}"
            assert inner2.called is True
        finally:
            state.db_manager = prior_db

    @pytest.mark.asyncio
    async def test_unknown_session_id_returns_404(self, db_manager, jwt_env):
        # BE-9066 note: the probe id below (uuid4().hex — no dashes) is NOT in
        # this server's minted shape, so it 404s. An unknown id in the CANONICAL
        # minted shape now soft-resurrects instead — covered by
        # tests/api/test_be9066_per_connection_sessions.py.
        from api.app_state import state
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

        raw_key, _tenant_key = await _seed_api_key(db_manager)

        prior_db = state.db_manager
        state.db_manager = db_manager
        try:
            inner = _CapturingInnerApp()
            mw = MCPAuthMiddleware(app=inner)
            status, _headers, body = await _drive_middleware_with_body(
                mw,
                headers=[
                    (b"x-api-key", raw_key.encode()),
                    (b"mcp-protocol-version", b"2025-06-18"),
                    (b"mcp-session-id", uuid4().hex.encode("ascii")),
                    (b"content-type", b"application/json"),
                ],
                body=_jsonrpc_body("tools/list"),
            )
            assert status == 404, f"unknown Mcp-Session-Id returned {status}"
            assert inner.called is False, "inner app must not run for unknown session"
            assert b"session" in body.lower() or b"Not Found" in body, (
                f"404 body should mention invalid session: {body!r}"
            )
        finally:
            state.db_manager = prior_db


class TestSessionIsTenantScoped:
    """A session id issued to tenant A must NOT be replayable under tenant B."""

    @pytest.mark.asyncio
    async def test_cross_tenant_session_id_returns_404(self, db_manager, jwt_env):
        from api.app_state import state
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

        key_a, tenant_a = await _seed_api_key(db_manager)
        key_b, tenant_b = await _seed_api_key(db_manager)
        assert tenant_a != tenant_b

        prior_db = state.db_manager
        state.db_manager = db_manager
        try:
            inner = _CapturingInnerApp(response_status=200)
            mw = MCPAuthMiddleware(app=inner)
            _status, init_headers, _body = await _drive_middleware_with_body(
                mw,
                headers=[
                    (b"x-api-key", key_a.encode()),
                    (b"content-type", b"application/json"),
                ],
                body=_jsonrpc_body(
                    "initialize",
                    params={"protocolVersion": "2025-06-18", "capabilities": {}},
                ),
            )
            session_id = init_headers.get("mcp-session-id")
            assert session_id, "tenant A initialize must mint a session"

            inner2 = _CapturingInnerApp(response_status=200)
            mw2 = MCPAuthMiddleware(app=inner2)
            status, _headers, _body = await _drive_middleware_with_body(
                mw2,
                headers=[
                    (b"x-api-key", key_b.encode()),
                    (b"mcp-protocol-version", b"2025-06-18"),
                    (b"mcp-session-id", session_id.encode("ascii")),
                    (b"content-type", b"application/json"),
                ],
                body=_jsonrpc_body("tools/list"),
            )
            assert status == 404, f"cross-tenant session must 404, got {status} — tenant isolation breached"
            assert inner2.called is False
        finally:
            state.db_manager = prior_db


class TestSessionExtendOnUse:
    """``last_accessed`` advances on subsequent use of a valid session id."""

    @pytest.mark.asyncio
    async def test_last_accessed_advances(self, db_manager, jwt_env):
        from api.app_state import state
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware
        from giljo_mcp.models import MCPSession

        raw_key, tenant_key = await _seed_api_key(db_manager)

        prior_db = state.db_manager
        state.db_manager = db_manager
        try:
            inner = _CapturingInnerApp(response_status=200)
            mw = MCPAuthMiddleware(app=inner)
            _status, init_headers, _body = await _drive_middleware_with_body(
                mw,
                headers=[
                    (b"x-api-key", raw_key.encode()),
                    (b"content-type", b"application/json"),
                ],
                body=_jsonrpc_body(
                    "initialize",
                    params={"protocolVersion": "2025-06-18", "capabilities": {}},
                ),
            )
            session_id = init_headers.get("mcp-session-id")
            assert session_id

            # Snapshot the row state, then artificially backdate last_accessed.
            async with db_manager.get_session_async() as db:
                with tenant_session_context(db, tenant_key):
                    row = (
                        await db.execute(
                            select(MCPSession).where(
                                MCPSession.session_id == session_id,
                                MCPSession.tenant_key == tenant_key,
                            )
                        )
                    ).scalar_one()
                    row.last_accessed = datetime.now(UTC) - timedelta(hours=1)
                    backdated = row.last_accessed
                    await db.commit()

            # Drive a second request that should bump last_accessed. BE-6070 note:
            # the session-extend write is debounced per session id, but `initialize`
            # CREATES the row (the create path does not record the debounce), so
            # this first reuse is the first extend and lands — last_accessed
            # advances exactly as before.
            inner2 = _CapturingInnerApp(response_status=200)
            mw2 = MCPAuthMiddleware(app=inner2)
            await _drive_middleware_with_body(
                mw2,
                headers=[
                    (b"x-api-key", raw_key.encode()),
                    (b"mcp-protocol-version", b"2025-06-18"),
                    (b"mcp-session-id", session_id.encode("ascii")),
                    (b"content-type", b"application/json"),
                ],
                body=_jsonrpc_body("tools/list"),
            )

            async with db_manager.get_session_async() as db:
                with tenant_session_context(db, tenant_key):
                    row = (
                        await db.execute(
                            select(MCPSession).where(
                                MCPSession.session_id == session_id,
                                MCPSession.tenant_key == tenant_key,
                            )
                        )
                    ).scalar_one()
                    assert row.last_accessed > backdated, (
                        f"last_accessed did not advance: was {backdated}, now {row.last_accessed}"
                    )
        finally:
            state.db_manager = prior_db


@contextlib.contextmanager
def _no_ambient_tenant():
    """Force the tenant ContextVar to None, then restore (BE6004C-3 pattern).

    The crux of the regression: the JWT session path must succeed with NO
    caller-set tenant context, proving it binds ``session.info['tenant_key']``
    itself rather than leaning on the ambient ContextVar. Token-restore so a
    concurrent xdist worker's context is never clobbered.
    """
    token = current_tenant.set(None)
    try:
        assert TenantManager.get_current_tenant() is None
        yield
    finally:
        current_tenant.reset(token)


class TestJwtSessionEnforceTenantScope:
    """REGRESSION (BE6004C enforce): the JWT (OAuth) session-init path must bind
    the session tenant context so the ``do_orm_execute`` guard does not raise.

    ``mcp_sdk_server._ensure_jwt_initialize_session`` opens a BARE db session and
    calls ``MCPSessionManager.create_session``. The original bug (when the call
    was still ``get_or_create_session_from_jwt``, pre-BE-9066): the manager
    touched ``MCPSession`` WITHOUT setting ``session.info['tenant_key']``, so
    under enforce the guard raised ``TenantIsolationError`` and ``POST /mcp``
    returned 500 on EVERY JWT (OAuth) connect. Caught live on test.giljo.ai
    2026-05-31 the moment the OAuth multi-tenant fix unblocked the connection.
    This drives the failing layer (the service fn) against a REAL session with
    NO ambient tenant ContextVar. BE-9066 re-target: a second connect now mints
    a SECOND session (one row per connection) instead of reusing the first.
    """

    @pytest.mark.asyncio
    async def test_jwt_session_create_under_enforce_is_per_connection(self, db_manager):
        from api.endpoints.mcp_session import MCPSessionManager
        from giljo_mcp.models import MCPSession
        from giljo_mcp.models.auth import User
        from giljo_mcp.models.organizations import Organization

        tk = TenantManager.generate_tenant_key()
        unique = uuid4().hex[:8]

        async with db_manager.get_session_async() as db:
            with tenant_session_context(db, tk):
                org = Organization(
                    name=f"JWT Sess Org {unique}",
                    slug=f"jwt-sess-{unique}",
                    tenant_key=tk,
                    is_active=True,
                )
                db.add(org)
                await db.flush()
                user = User(
                    username=f"jwt_sess_user_{unique}",
                    email=f"jwt_sess_{unique}@example.com",
                    password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode("utf-8"),
                    tenant_key=tk,
                    role="developer",
                    org_id=org.id,
                    is_active=True,
                )
                db.add(user)
                await db.flush()
                user_id = user.id
                await db.commit()

        try:
            with _no_ambient_tenant():
                # First connect: pre-fix this raised TenantIsolationError under enforce.
                async with db_manager.get_session_async() as db:
                    s1 = await MCPSessionManager(db).create_session(
                        tenant_key=tk,
                        user_id=user_id,
                        auth_method="oauth_jwt",
                        username=f"jwt_sess_user_{unique}",
                    )
                    assert s1 is not None, "JWT session creation returned None"
                    assert s1.tenant_key == tk, "session bound to the wrong tenant"
                    first_session_id = s1.session_id

                # Second connect: a NEW connection mints its OWN session (BE-9066).
                async with db_manager.get_session_async() as db:
                    s2 = await MCPSessionManager(db).create_session(
                        tenant_key=tk,
                        user_id=user_id,
                        auth_method="oauth_jwt",
                        username=f"jwt_sess_user_{unique}",
                    )
                    assert s2.session_id != first_session_id, (
                        "each connect must mint its own session (per-connection, BE-9066)"
                    )
        finally:
            async with db_manager.get_session_async() as db:
                with tenant_session_context(db, tk):
                    await db.execute(delete(MCPSession).where(MCPSession.tenant_key == tk))
                    await db.execute(delete(User).where(User.tenant_key == tk))
                    await db.execute(delete(Organization).where(Organization.tenant_key == tk))
                    await db.commit()
