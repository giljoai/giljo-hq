# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9449: capture the client's DECLARED MCP capabilities at ``initialize``.

``session_data["capabilities"]`` has been initialised ``{}`` and never filled
since the table was created, so the one signal that distinguishes Claude Desktop
from claude.ai web -- both of which declare the byte-identical
``Anthropic/ClaudeAI`` v1.0.0 clientInfo -- is thrown away at the only moment it
is ever knowable. This module pins the NEW ``client_capabilities`` key that
carries it, verbatim.

Failing-layer discipline (per CLAUDE.md): the capture lives in the ASGI auth
middleware's ``initialize`` special-case, so the regression tests drive a real
``initialize`` JSON-RPC payload through ``MCPAuthMiddleware`` end-to-end -- the
same boundary a real MCP client hits -- and assert what lands in the persisted
``MCPSession.session_data`` row. **The observable is the row, never the fact
that a helper was called.** Both mint paths are covered, because two mint paths
means two places the value can silently fail to land: the API-key path
(``mcp_auth_middleware.py:302``) and the JWT path (``:527`` ->
``_ensure_jwt_initialize_session`` -> ``:640``).

Reuses the seed + middleware drivers from ``tests/api/test_mcp_session.py``,
matching ``test_be8003d_clientinfo_capture.py`` (the INF-8003d mirror this
project copies).

READ THIS BEFORE COUNTING THE PRE-FIX RED
-----------------------------------------
Against unmodified master this module produces two DIFFERENT kinds of failure
and only one of them is evidence. They are separated into named classes here so
a later reader cannot miscount them:

* **EVIDENCE -- assertion-class.** Everything in ``TestCapturedAtTheApiKeyMint``
  and ``TestCapturedAtTheJwtMint``. On master the session is created normally,
  nothing imports wrong, the row is fully populated, and
  ``session_data.get("client_capabilities")`` is simply ``None`` where the
  declared object is expected. The ASSERTION fails. That is the reproduction.

* **NOT EVIDENCE -- surface-absent class.** ``TestPeekHelperContract`` and
  ``TestClientInfoPatchVehicle`` fail on master with ``ImportError`` /
  ``TypeError`` because ``_peek_jsonrpc_capabilities`` and the new
  ``capabilities`` keyword do not exist yet. A red against a surface that has
  not been written proves nothing about the defect. These are worth having
  AFTER the fix; they are not reproduction and must not be reported as such.

* **BOTH-SIDES GUARDS.** ``TestUnchangedBehaviour`` passes on unmodified master
  AND after the change. If any of it goes red, the instrument is broken and the
  red above proves nothing.
"""

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


# The MCP middleware derives the expected JWT audience from the request scope's
# base URL. With a ``host: test`` header and an http scope the canonical URI is
# deterministic, so the JWT's ``aud`` must match exactly (same constant and same
# reason as tests/api/test_sec3001a_mcp_deactivation.py).
_CANONICAL_AUD = "http://test/mcp"

# A capabilities object that is deliberately NOT a tidy spec subset. It carries
# a spec-declared key the BE-9440 consumer needs (``elicitation``), a nested
# structure (``roots``), and two things no MCP spec declares at all. The last
# two are the point: a live prod row shows ``claude-code`` sending an undeclared
# ``description`` key inside clientInfo, so a filtered capture would hide
# exactly the class of thing this project exists to observe.
_DECLARED_CAPABILITIES = {
    "elicitation": {},
    "roots": {"listChanged": True},
    "sampling": {},
    "experimental": {"vendorPrivate": {"nested": [1, 2, 3]}},
    "anUndeclaredTopLevelKey": "must survive verbatim",
}

_CLIENT_INFO = {"name": "test-harness", "version": "9.9.9"}


class _CapturingProbe:
    """Minimal inner ASGI app that returns 200 and drains the body."""

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
    """Drive one real ``initialize`` over the API-key path; return the session id."""
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
    """Create org+user for the JWT mint path; return (user_id, username, tenant_key)."""
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
    """Drive one real ``initialize`` over the JWT path; return the session id."""
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


# ---------------------------------------------------------------------------
# EVIDENCE (assertion-class) -- this is the reproduction.
# ---------------------------------------------------------------------------


class TestCapturedAtTheApiKeyMint:
    """API-key mint path (``mcp_auth_middleware.py:302``) -> ``create_session``."""

    @pytest.mark.asyncio
    async def test_declared_capabilities_land_verbatim(self, db_manager, jwt_env):
        """DoD 1 + DoD 3: the WHOLE declared object reaches session_data, unfiltered.

        Equality against the full dict is deliberate. A subset assertion would
        pass a filtered capture, and a filter is precisely what this project
        forbids -- the undeclared keys are the ones worth seeing.
        """
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
        """DoD 3, stated as its own failure: an arbitrary key no spec declares survives.

        Separate from the equality test above so that a partial regression (a
        capture that keeps the spec keys and drops the rest) names itself
        instead of hiding inside a whole-object mismatch.
        """
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
        """DoD 4: the BE-9440 consumer's read.

        Whether a client declares elicitation support decides whether per-decision
        confirmation is available at all as a headless-safety mechanism. This
        asserts the exact shape that consumer will read, ``.get``-chained the way
        a legacy row (which simply lacks the key) requires.
        """
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
    """JWT mint path (``:527`` -> ``_ensure_jwt_initialize_session`` -> ``:640``).

    Covered observably rather than by code reading: two mint paths are two
    places the capture can silently fail to land, and the API-key test would
    stay green through a JWT-path regression.
    """

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


# ---------------------------------------------------------------------------
# BOTH-SIDES GUARDS -- green on unmodified master AND after the change.
# If one of these goes red, the instrument is broken and the reds above prove
# nothing -- when one goes red, suspect the instrument first.
# ---------------------------------------------------------------------------


class TestUnchangedBehaviour:
    @pytest.mark.asyncio
    async def test_existing_capture_keys_still_land(self, db_manager, jwt_env):
        """DoD 2: client_info, resolved_harness, resolved_preset and protocol_version
        are untouched by this change -- the three keys already riding the
        ``_client_info_patch`` vehicle (BE-9327, INF-9371) plus the raw clientInfo."""
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
        """DoD 5: ``session_data["capabilities"]`` stays exactly as it is -- ``{}``.

        Deliberately NOT filled. ``capabilities`` is an overloaded word here:
        ``platform_registry.py`` takes a ``capabilities`` argument that is Giljo's
        OWN derived vector (preset, can_spawn_terminals), a different concept from
        the client's declared MCP capabilities. Merging the two meanings into one
        JSONB field could change preset and terminal resolution.
        """
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
        """DoD 2: a client that declares nothing must still get a session.

        The absent-field path, asserted at the boundary rather than as a unit
        test of the peek helper, so it is green on both sides of the change.
        """
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
        """DoD 2: a ``capabilities`` that is not an object is tolerated, never fatal.

        Same tolerate-malformed-body policy the sibling peeks carry: this is
        session bookkeeping, never a security boundary. Asserted through the
        transport (the observable) rather than against the helper, so it holds on
        both sides.
        """
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
        """A body that is not JSON at all must not 500 out of the middleware.

        The strongest instrument guard in the file: it exercises the same peek
        machinery with a body no parser can read, and it must behave identically
        before and after the change.
        """
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


# ---------------------------------------------------------------------------
# NOT EVIDENCE -- surface-absent class.
#
# Everything below fails on unmodified master with ImportError / TypeError,
# because the surface does not exist yet. A red against a surface that has not
# been written proves nothing about the defect and MUST NOT be counted as
# reproduction. These are worth having after the fix; they are not the fix's
# justification.
# ---------------------------------------------------------------------------


class TestPeekHelperContract:
    """Unit contract for ``_peek_jsonrpc_capabilities`` -- NOT reproduction evidence."""

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
    """``_client_info_patch`` gains a 5th key -- NOT reproduction evidence."""

    def test_patch_carries_client_capabilities(self):
        from api.endpoints.mcp_session import _client_info_patch

        patch = _client_info_patch(
            dict(_CLIENT_INFO),
            protocol_version="2025-06-18",
            capabilities=_DECLARED_CAPABILITIES,
        )
        assert patch["client_capabilities"] == _DECLARED_CAPABILITIES

    def test_patch_defaults_the_new_key_to_none(self):
        """A caller that supplies nothing still gets the key, valued None -- matching
        how ``protocol_version`` behaves, so the shape is uniform across the vehicle."""
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
