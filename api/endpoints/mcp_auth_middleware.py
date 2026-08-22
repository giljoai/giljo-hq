# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
MCP ASGI auth middleware -- Bearer/API-key validation + tenant injection for /mcp.

BE-9060 (item 1): the auth boundary was split out of
``api.endpoints.mcp_sdk_server`` into this module. It hosts :class:`MCPAuthMiddleware`
(the ASGI middleware that authenticates the request, injects ``tenant_key`` into the
ASGI scope, runs the SaaS post-auth subscription gate, and manages the
Mcp-Session-Id lifecycle) plus the CE post-auth-gate extension point the middleware
consults. Behavior is unchanged -- extracted verbatim; ``mcp_sdk_server`` re-exports
``MCPAuthMiddleware`` and the gate register/clear functions so importers keep working.

The wire-level primitives the middleware composes (body buffer/replay, the raw-ASGI
status emitters, JSON-RPC peeking, protocol-version validation, the session-id send
wrapper, and the response builders) live in :mod:`api.endpoints.mcp_transport`.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from api.endpoints.mcp_tools import logger
from api.endpoints.mcp_transport import (
    _INITIALIZE_METHOD,
    _MAX_MCP_BODY_BYTES,
    _BodyTooLargeError,
    _not_found_response,
    _peek_jsonrpc_capabilities,
    _peek_jsonrpc_client_info,
    _peek_jsonrpc_method,
    _peek_jsonrpc_protocol_version,
    _read_full_body,
    _replay_receive,
    _send_method_not_allowed,
    _send_raw_status,
    _stamp_declared_profile,
    _stamp_resolved_harness,
    _stamp_resolved_preset,
    _stamp_url_profile,
    _subscription_required_response,
    _unauthenticated_response,
    _validate_protocol_version,
    _wrap_send_with_session_id,
)
from giljo_mcp.auth.jwt_manager import JWTAudienceMismatchError, JWTManager
from giljo_mcp.http.url_resolver import get_canonical_mcp_resource_uri_from_scope
from giljo_mcp.signals import SIGNAL_POST_AUTH_GATE_FAILED, publish_signal


# ---------------------------------------------------------------------------
# BE-6060d: post-auth gate hook (entitlement-check extension point).
#
# CE provides the foundation: a single optional async callable that the MCP auth
# middleware consults AFTER tenant_key is resolved, BEFORE the inner SDK app runs.
# CE never imports SaaS — in CE the gate is simply never registered, so the hook
# is a no-op and the Deletion Test holds. Deployment-specific entitlement checks
# may be registered here via the same conditional-registration family as the
# other SaaS middleware/router hooks; error handling for those checks is owned
# by the deployment that registers them. The gate takes the resolved tenant_key
# and returns a block message (the request is refused with a JSON-RPC 403
# carrying that message) or None to allow.
#
# If a registered gate raises, the request continues and CE announces the fact on
# giljo_mcp.signals.SIGNAL_POST_AUTH_GATE_FAILED. That publish is a no-op unless
# the deployment installed an observer, and it never raises, so the request path
# is unaffected either way.
# ---------------------------------------------------------------------------

McpPostAuthGate = Callable[[str], Awaitable[str | None]]

_mcp_post_auth_gate: McpPostAuthGate | None = None


def register_mcp_post_auth_gate(gate: McpPostAuthGate) -> None:
    """Install the post-auth gate the MCP auth middleware consults per request.

    Idempotent-by-replacement: the last registration wins. Called once at SaaS
    startup. Never called in CE (the hook stays None → no-op).
    """
    global _mcp_post_auth_gate  # noqa: PLW0603
    _mcp_post_auth_gate = gate


def clear_mcp_post_auth_gate() -> None:
    """Remove any registered gate (test teardown + CE-equivalent default)."""
    global _mcp_post_auth_gate  # noqa: PLW0603
    _mcp_post_auth_gate = None


def _initialize_capture(scope: Scope) -> dict[str, Any]:
    """The initialize-only values peeked pre-auth, shaped as ``create_session`` kwargs.

    Both mint paths — API-key and JWT — pass exactly these, and both read them off the
    scope state the pre-auth guard stashed them on. That vehicle is INF-9371's
    (``protocol_version``), extended by BE-9449 (``client_capabilities``); it exists
    because these are knowable only at ``initialize`` and ``stateless_http`` drops them
    on every later request.

    Read through one accessor so a fourth captured value is added at ONE site rather
    than at every mint path, where the two could silently drift apart.
    """
    request_state = scope.get("state", {})
    return {
        "protocol_version": request_state.get("mcp_protocol_version"),
        "capabilities": request_state.get("mcp_client_capabilities"),
    }


class MCPAuthMiddleware:
    """
    ASGI middleware that validates Bearer token (JWT or API key) and injects
    tenant_key into the ASGI scope state before the MCP SDK processes the request.

    Auth flow:
    1. Extract Authorization: Bearer <token> or X-API-Key header
    2. Try JWT validation first (fast, stateless). For Bearer JWTs, the
       canonical MCP URI is supplied as expected_audience — tokens carrying
       a foreign aud claim are rejected outright (RFC 8707 / API-0021a).
       Aud-less JWTs still authenticate during the transition window with a
       deprecation warning.
    3. Fall back to API key via MCPSessionManager (stateful, PostgreSQL)
    4. Attach tenant_key + user_id to scope["state"]

    All 401 responses include `WWW-Authenticate: Bearer realm="MCP",
    resource_metadata="<URL>"` so clients can self-discover the resource
    metadata document (RFC 6750 + RFC 9728).
    """

    # Cap on the setup:tool_connected de-dup memo. One entry per distinct
    # tenant:principal; an unbounded set is a slow leak for long-lived SaaS
    # workers. Beyond this we evict oldest-inserted (the de-dup window still
    # suppresses repeats for any key still resident).
    _NOTIFIED_KEYS_MAX = 10_000

    def __init__(self, app: ASGIApp):
        self.app = app
        # dict (insertion-ordered) used as a bounded ordered-set so we can
        # evict oldest-first once over _NOTIFIED_KEYS_MAX. Keys we've already
        # emitted setup:tool_connected for.
        self._notified_keys: dict[str, None] = {}

    def _mark_notified(self, notify_key: str) -> bool:
        """Record that we've emitted setup:tool_connected for ``notify_key``.

        Returns ``True`` if this is the FIRST time we've seen the key (caller
        should emit), ``False`` if it was already notified (suppress repeat).
        The memo is bounded at ``_NOTIFIED_KEYS_MAX``; once over, the
        oldest-inserted key is evicted so memory cannot grow without bound on
        long-lived workers.
        """
        if notify_key in self._notified_keys:
            return False
        self._notified_keys[notify_key] = None
        if len(self._notified_keys) > self._NOTIFIED_KEYS_MAX:
            # Evict oldest-inserted to keep the memo bounded.
            self._notified_keys.pop(next(iter(self._notified_keys)))
        return True

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Pre-auth transport edges (405 / 413 / 400 / 401 + body buffer-replay).
        guard = await self._pre_auth_guard(scope, receive, send)
        if guard is None:
            return
        receive, request, method, client_info, api_key_value, bearer_token = guard

        tenant_key: str | None = None
        user_id: str | None = None
        api_key_id: str | None = None
        auth_method: str | None = None
        token_scopes: list[str] | None = None
        # API-0021j: captured during API-key auth so initialize responses can
        # advertise Mcp-Session-Id without a second DB round-trip.
        mcp_session_id: str | None = None

        # Path 1: JWT token (with audience binding per API-0021a).
        #
        # SEC-3004c: the full decode → audience → revocation → is_active pipeline
        # is the single ``validate_principal`` validator. This transport supplies
        # the resource-server audience and maps the failure reason to an MCP wire
        # response. The MCP-only concerns stay here, layered around the shared
        # validator: the scope-claim default, and the api-key fallback (a Bearer
        # value that is not a *usable* JWT is retried as an API key — but a valid
        # JWT that must NOT authenticate, e.g. revoked/inactive/foreign-audience,
        # is never retried).
        if bearer_token and not api_key_value:
            expected_audience = get_canonical_mcp_resource_uri_from_scope(scope)
            from api.app_state import state as _app_state

            if _app_state.db_manager is not None:
                from giljo_mcp.auth.principal import (
                    JWT_FALLBACK_REASONS,
                    AuthErrorReason,
                    PrincipalValidationError,
                    validate_principal,
                )

                try:
                    async with _app_state.db_manager.get_session_async() as _auth_db:
                        principal = await validate_principal(
                            _auth_db, jwt_token=bearer_token, expected_audience=expected_audience
                        )
                    tenant_key = principal.tenant_key
                    user_id = principal.user_id
                    auth_method = "jwt"
                    # API-0021b: claim-less / cookie JWTs default to read+write.
                    # mcp:agent is never granted by default, so widening is safe.
                    token_scopes = principal.scopes if principal.scopes is not None else ["mcp:read", "mcp:write"]
                except PrincipalValidationError as exc:
                    if exc.reason in JWT_FALLBACK_REASONS:
                        # Not a usable JWT -- retry the same value as an API key.
                        api_key_value = bearer_token
                        auth_method = None
                        token_scopes = None
                    else:
                        # Hard reject (revoked / inactive / foreign audience).
                        _msg = {
                            AuthErrorReason.REVOKED: "Token revoked",
                            AuthErrorReason.INACTIVE: "User is inactive",
                            AuthErrorReason.INVALID_AUDIENCE: "Invalid token audience",
                        }.get(exc.reason, "Invalid credentials")
                        logger.warning("Rejecting JWT on /mcp (%s): %s", exc.reason.value, exc.detail)
                        resp = _unauthenticated_response(scope, _msg)
                        await resp(scope, receive, send)
                        return
            else:
                # No DB (setup window / degraded). Revocation + is_active cannot
                # be consulted, so validate on the decode + audience claims alone
                # — the prior SEC-3001a behavior (those DB reads were skipped when
                # db_manager was None). The full pipeline lives once, in
                # validate_principal; this is a decode-only degraded fallback.
                try:
                    payload = JWTManager.verify_token(bearer_token, expected_audience=expected_audience)
                    tenant_key = payload["tenant_key"]
                    user_id = payload["sub"]
                    auth_method = "jwt"
                    raw_scope = payload.get("scope")
                    token_scopes = (
                        ["mcp:read", "mcp:write"] if raw_scope is None else [s for s in str(raw_scope).split() if s]
                    )
                except JWTAudienceMismatchError as exc:
                    logger.warning("Rejecting JWT on /mcp (audience): %s", exc)
                    resp = _unauthenticated_response(scope, "Invalid token audience")
                    await resp(scope, receive, send)
                    return
                except (ValueError, KeyError, RuntimeError, HTTPException):
                    # Not a valid JWT -- treat as API key (backward compatibility).
                    api_key_value = bearer_token
                    auth_method = None
                    token_scopes = None

        # Path 2: API key — authenticate-only (BE-9066). The caller's identity
        # (tenant/user/key) comes straight from ``authenticate_api_key``; only an
        # ``initialize`` mints + INSERTs a session row, and the echoed
        # Mcp-Session-Id on every other request is validated downstream in
        # ``_apply_session_lifecycle``. (The old per-request get_or_create_session
        # reused ONE row per principal and deleted "duplicate" siblings on every
        # call — the last-writer-wins harness contamination C1 removes.)
        if not tenant_key and api_key_value:
            try:
                from api.app_state import state
                from api.endpoints.mcp_session import MCPSessionManager

                if not state.db_manager:
                    logger.error("db_manager not available for MCP auth")
                    resp = JSONResponse({"error": "Database not initialized"}, status_code=503)
                    await resp(scope, receive, send)
                    return

                async with state.db_manager.get_session_async() as db:
                    session_mgr = MCPSessionManager(db)
                    auth_result = await session_mgr.authenticate_api_key(api_key_value)
                    if auth_result:
                        key_record, user = auth_result
                        tenant_key = user.tenant_key
                        user_id = user.id
                        api_key_id = key_record.id
                        auth_method = "api_key"

                        if method == _INITIALIZE_METHOD:
                            session = await session_mgr.create_session(
                                tenant_key=user.tenant_key,
                                user_id=user.id,
                                api_key_id=key_record.id,
                                client_info=client_info,
                                **_initialize_capture(scope),
                            )
                            mcp_session_id = session.session_id

                        # Passive IP logging (non-blocking)
                        if api_key_id:
                            client_ip = request.client.host if request.client else "unknown"
                            try:
                                await session_mgr.log_ip(api_key_id, client_ip)
                            except (OSError, ValueError, KeyError):
                                logger.debug("IP logging failed (non-blocking)")
            except (OSError, ValueError, KeyError, RuntimeError):
                logger.exception("API key authentication failed")

        if not tenant_key:
            if api_key_value:
                # BE-6060b: throttle FAILED API-key auth per IP (a valid key never
                # reaches here). An over-budget IP gets 429 instead of 401 so a
                # sprayer cannot keep forcing prefix-narrowed verifies (bcrypt on
                # legacy rows). Reuses the shared per-IP auth rate limiter.
                from api.middleware.auth_rate_limiter import enforce_api_key_auth_failure

                try:
                    await enforce_api_key_auth_failure(request)
                except HTTPException as rl_exc:
                    if rl_exc.status_code == 429:
                        retry_after = (rl_exc.headers or {}).get("Retry-After", "60")
                        await _send_raw_status(
                            send,
                            status=429,
                            headers=[(b"retry-after", str(retry_after).encode("ascii"))],
                        )
                        return
                    raise
            resp = _unauthenticated_response(scope, "Invalid credentials")
            await resp(scope, receive, send)
            return

        # Inject into ASGI scope state -- accessible in tool handlers via ctx
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["tenant_key"] = tenant_key
        scope["state"]["user_id"] = user_id
        # API-0021b: stamp auth discriminator + token scopes for the
        # tools/list filter and tools/call dispatch gate.
        scope["state"]["auth_method"] = auth_method
        if token_scopes is not None:
            scope["state"]["scopes"] = token_scopes

        # BE-6060d: post-auth entitlement gate (no-op in CE — the hook is never
        # registered there). Consulted AFTER tenant_key is resolved, before the
        # inner SDK app runs, so a refused tenant gets a JSON-RPC 403 up front.
        # Deployment-specific entitlement checks may be registered here; error
        # handling for those checks is owned by the deployment that registers
        # them.
        gate = _mcp_post_auth_gate
        if gate is not None:
            try:
                block_message = await gate(tenant_key)
            except Exception:  # noqa: BLE001 - gate errors are handled per the registering deployment's policy
                logger.warning("mcp_post_auth_gate_failed tenant=%s", tenant_key, exc_info=True)
                publish_signal(SIGNAL_POST_AUTH_GATE_FAILED, {"tenant_key": tenant_key})
                block_message = None
            if block_message:
                resp = _subscription_required_response(block_message)
                await resp(scope, receive, send)
                return

        # Handover 0855b: Emit setup:tool_connected on FIRST MCP auth per key
        # (replaces emission from deleted mcp_http.py after 0846 SDK migration)
        notify_key = f"{tenant_key}:{api_key_id or user_id}"
        if self._mark_notified(notify_key):
            try:
                from api.app_state import state as app_state

                ws_manager = getattr(app_state, "websocket_manager", None)
                if ws_manager and tenant_key:
                    from giljo_mcp.events.schemas import EventFactory

                    event = EventFactory.setup_tool_connected(
                        tenant_key=tenant_key,
                        user_id=str(user_id) if user_id else "unknown",
                        tool_name="mcp_connected",
                    )
                    await ws_manager.broadcast_event_to_tenant(tenant_key=tenant_key, event=event)
            except (OSError, RuntimeError, ValueError, TypeError, AttributeError, ImportError):
                pass  # Fire-and-forget, non-blocking

        # API-0021j Phase 2: Mcp-Session-Id lifecycle.
        send = await self._apply_session_lifecycle(
            scope=scope,
            send=send,
            request=request,
            method=method,
            client_info=client_info,
            tenant_key=tenant_key,
            user_id=user_id,
            api_key_id=api_key_id,
            auth_method=auth_method,
            mcp_session_id=mcp_session_id,
        )
        if send is None:
            # _apply_session_lifecycle already sent a 404; do not invoke inner app.
            return

        # BE-9253: the URL-selected tool profile (?profile=listing on the published
        # connector URL). Stamped LAST, so the auth discriminator, the token scopes
        # and any session-DECLARED profile are all already on state — that resolved
        # ladder is the baseline the stamp is required to narrow within, and it
        # cannot widen. Sited here rather than inside _apply_session_lifecycle so it
        # covers every arm: initialize, the session-row path, and the BE-9066
        # no-session-header passthrough.
        _stamp_url_profile(scope)

        from giljo_mcp.tenant import TenantManager, current_tenant

        # Capture the token and reset() to the exact prior value (BE6004C-1);
        # set(previous)/clear could clobber an outer tenant and leak across
        # requests on a reused worker.
        tenant_token = TenantManager.set_current_tenant(tenant_key)
        try:
            await self.app(scope, receive, send)
        finally:
            current_tenant.reset(tenant_token)

    async def _pre_auth_guard(
        self, scope: Scope, receive: Receive, send: Send
    ) -> tuple[Receive, StarletteRequest, str | None, dict[str, Any] | None, str | None, str | None] | None:
        """Run the transport edges that MUST precede auth, in load-bearing order:
        405 (method) → 413 (size) → 400 (protocol version) → 401 (no creds), so a
        client gets the most specific reason. Returns ``None`` when an edge already
        emitted a response (caller short-circuits); otherwise
        ``(receive, request, method, client_info, api_key_value, bearer_token)`` —
        ``receive`` is the ``_replay_receive`` wrapper so the inner SDK sees
        byte-identical body. ``client_info`` (INF-8003d) is the peeked
        ``params.clientInfo`` dict, populated only for ``initialize`` requests."""
        # BE-6060a Fix 1: GET /mcp → 405 BEFORE body read / auth / bcrypt so the
        # TS SDK stops its 1000ms SSE re-poll. Rationale at _send_method_not_allowed.
        if scope.get("method") == "GET":
            await _send_method_not_allowed(send)
            return None

        # BE-6060a Fix 4 (Layer 1): Content-Length pre-check rejects an oversize
        # body before buffering/auth so an unauthenticated client can't pin memory.
        request = StarletteRequest(scope, receive)
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > _MAX_MCP_BODY_BYTES:
            await _send_raw_status(send, status=413)
            return None

        # Buffer the JSON-RPC body once (so `method` is peekable pre-auth) and
        # replay it downstream byte-for-byte. _read_full_body's max_bytes is the
        # Layer-2 streaming cap; _replay_receive delegates to original_receive
        # after the buffered frame (BE-6060a Fix 3 — no synthesized disconnect).
        original_receive = receive
        try:
            buffered_body = await _read_full_body(original_receive, max_bytes=_MAX_MCP_BODY_BYTES)
        except _BodyTooLargeError:
            await _send_raw_status(send, status=413)
            return None
        receive = _replay_receive(buffered_body, original_receive)
        method = _peek_jsonrpc_method(buffered_body)
        is_initialize = method == _INITIALIZE_METHOD
        client_info = _peek_jsonrpc_client_info(buffered_body) if is_initialize else None
        # INF-9371: capture the requested revision at the one point a client states it,
        # and ride the scope state the session-mint paths already read from -- rather than
        # widening this guard's return tuple and MCPAuthMiddleware.__call__ with it.
        # BE-9449 rides the same vehicle for the same reason (see the peek's docstring).
        if is_initialize:
            state_ = scope.setdefault("state", {})
            state_["mcp_protocol_version"] = _peek_jsonrpc_protocol_version(buffered_body)
            state_["mcp_client_capabilities"] = _peek_jsonrpc_capabilities(buffered_body)

        request = StarletteRequest(scope, receive)

        # API-0021j Phase 1: protocol-version validation MUST precede auth so an
        # unsupported client gets 400, not 401. Rationale at _validate_protocol_version.
        version_error = _validate_protocol_version(request, method)
        if version_error is not None:
            await version_error(scope, receive, send)
            return None

        api_key_value: str | None = request.headers.get("x-api-key")
        bearer_token: str | None = None

        if not api_key_value:
            auth_header = request.headers.get("authorization", "")
            if auth_header.lower().startswith("bearer "):
                bearer_token = auth_header[7:]

        if not api_key_value and not bearer_token:
            resp = _unauthenticated_response(scope, "Authentication required (Authorization: Bearer or X-API-Key)")
            await resp(scope, receive, send)
            return None

        return receive, request, method, client_info, api_key_value, bearer_token

    async def _apply_session_lifecycle(
        self,
        *,
        scope: Scope,
        send: Send,
        request: StarletteRequest,
        method: str | None,
        client_info: dict[str, Any] | None = None,
        tenant_key: str,
        user_id: str | None,
        api_key_id: str | None = None,
        auth_method: str | None,
        mcp_session_id: str | None,
    ) -> Send | None:
        """Resolve / validate the MCP session per API-0021j Phase 2.

        Returns a (possibly wrapped) ``send`` to use for the inner ASGI app, or
        ``None`` when the lifecycle has already emitted a 404 response (caller
        must short-circuit). Tenant scoping AND principal binding (BE-9066) are
        enforced by :meth:`MCPSessionManager.get_session` — a session id minted
        for another key/user/tenant behaves exactly like an unknown id.
        ``client_info`` (INF-8003d) is the peeked ``initialize`` clientInfo,
        threaded to the JWT session mint so it lands in ``session_data``
        alongside the API-key path's capture.
        """
        if method == _INITIALIZE_METHOD:
            session_id = mcp_session_id or await self._ensure_jwt_initialize_session(
                tenant_key=tenant_key,
                user_id=user_id,
                auth_method=auth_method,
                client_info=client_info,
                **_initialize_capture(request.scope),
            )
            if not session_id:
                return send
            return _wrap_send_with_session_id(send, session_id)

        header_session_id = request.headers.get("mcp-session-id")
        if not header_session_id:
            # BE-9066 decision: authenticated-generic PASSTHROUGH, not 400. The
            # spec's 400 clause binds "servers that REQUIRE a session ID"; under
            # stateless_http our sessions are render-hint bookkeeping, not a
            # requirement — a non-echoing (or never-initializing) client keeps
            # working with the generic render and simply owns no session row.
            logger.debug("Non-initialize request without Mcp-Session-Id; authenticated-generic passthrough")
            return send

        from api.app_state import state
        from api.endpoints.mcp_session import MCPSessionManager

        if not state.db_manager:
            logger.error("db_manager not available for MCP session validation")
            await _not_found_response("Not Found: Invalid or expired session ID")(scope, request.receive, send)
            return None

        async with state.db_manager.get_session_async() as db:
            session_mgr = MCPSessionManager(db)
            session_row = await session_mgr.get_session(
                header_session_id,
                tenant_key=tenant_key,
                caller_api_key_id=api_key_id,
                caller_user_id=user_id,
            )
            if session_row is None:
                # BE-9066 decision: soft-resurrection. A well-formed id from an
                # authenticated caller is revived credential-bound (or its
                # expired-but-unreaped row extended in place) instead of 404'd —
                # the never-terminate hedge for clients whose 404 auto-recovery
                # is unconfirmed. A malformed id, or one existing for another
                # principal/tenant, still yields the 404 below.
                session_row = await session_mgr.resurrect_session(
                    header_session_id,
                    tenant_key=tenant_key,
                    user_id=user_id,
                    api_key_id=api_key_id,
                    auth_method="oauth_jwt" if auth_method == "jwt" else None,
                )
            if session_row is None:
                logger.info(
                    "Rejecting unknown / cross-principal / cross-tenant Mcp-Session-Id=%s on tenant=%s",
                    header_session_id,
                    tenant_key,
                )
                await _not_found_response("Not Found: Invalid or expired session ID")(scope, request.receive, send)
                return None
            # WO-8003k: surface a session-DECLARED tool profile onto request state
            # so the tools/list filter + tools/call gate can honor "declared
            # profile wins". The declaration rides the (d) client_info capture
            # (session_data['client_info']) — reusing that vehicle, NOT a second
            # declaration mechanism. A missing/garbage value leaves state
            # untouched, so the resolver falls back to the auth-derived default.
            _stamp_declared_profile(scope, session_row)
            # BE-9035d: surface the persisted DETECTED harness so the tool render can
            # read it after stateless_http drops the live clientInfo on this tools/call.
            _stamp_resolved_harness(scope, session_row)
            # BE-9327: same vehicle for the PRESET axis — giljo_setup's no-filesystem
            # branch is a tools/call, so it can only see a preset that survived the
            # stateless_http clientInfo drop.
            _stamp_resolved_preset(scope, session_row)
            # BE-6070 (F5.4): the session SELECT above is the auth check and
            # STAYS. The extend is bookkeeping — since BE-9066 removed the
            # per-request get_or_create path (old F5.2), this is the SINGLE
            # extend site for every authenticated caller, debounced per session
            # id so N rapid calls collapse to one write per window. Note
            # extend_expiration also bumps last_accessed, which is what keeps
            # the 48h reaper away from an actively-used session.
            from api.endpoints.mcp_session import SESSION_EXTEND_DEBOUNCE_SECONDS, SESSION_EXTEND_NS
            from giljo_mcp.services.debounce import should_run

            if should_run(SESSION_EXTEND_NS, session_row.session_id, SESSION_EXTEND_DEBOUNCE_SECONDS):
                session_row.extend_expiration(MCPSessionManager.DEFAULT_SESSION_LIFETIME_HOURS)
                await db.commit()  # single-writer-allow: MCP transport session bookkeeping (BE-6070 debounce; pre-existing exception site relocated by hot-path refactor)
        return send

    async def _ensure_jwt_initialize_session(
        self,
        *,
        tenant_key: str,
        user_id: str | None,
        auth_method: str | None,
        client_info: dict[str, Any] | None = None,
        protocol_version: str | None = None,
        capabilities: dict[str, Any] | None = None,
    ) -> str | None:
        """Mint a fresh MCPSession on initialize over a JWT-authenticated request.

        The API-key auth path already mints a session in Path 2; for JWT callers
        we mint one explicitly so the initialize response can advertise an
        Mcp-Session-Id. One row per initialize (BE-9066) — no reuse. Returns the
        session_id, or ``None`` when the DB is unavailable.
        """
        if auth_method != "jwt" or not user_id:
            return None
        from api.app_state import state
        from api.endpoints.mcp_session import MCPSessionManager

        if not state.db_manager:
            return None
        async with state.db_manager.get_session_async() as db:
            session_mgr = MCPSessionManager(db)
            session = await session_mgr.create_session(
                tenant_key=tenant_key,
                user_id=user_id,
                client_info=client_info,
                auth_method="oauth_jwt",
                protocol_version=protocol_version,
                capabilities=capabilities,
            )
            return session.session_id
