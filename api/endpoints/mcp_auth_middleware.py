# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from api.endpoints.mcp_tools import logger
from api.endpoints.mcp_transport import (
    _DISCOVER_METHOD,
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
    announces_client,
)
from giljo_mcp.auth.jwt_manager import JWTAudienceMismatchError, JWTManager
from giljo_mcp.http.url_resolver import get_canonical_mcp_resource_uri_from_scope
from giljo_mcp.signals import SIGNAL_POST_AUTH_GATE_FAILED, publish_signal



McpPostAuthGate = Callable[[str], Awaitable[str | None]]

_mcp_post_auth_gate: McpPostAuthGate | None = None


def register_mcp_post_auth_gate(gate: McpPostAuthGate) -> None:
    global _mcp_post_auth_gate  # noqa: PLW0603
    _mcp_post_auth_gate = gate


def clear_mcp_post_auth_gate() -> None:
    global _mcp_post_auth_gate  # noqa: PLW0603
    _mcp_post_auth_gate = None


def _initialize_capture(scope: Scope) -> dict[str, Any]:
    request_state = scope.get("state", {})
    return {
        "protocol_version": request_state.get("mcp_protocol_version"),
        "capabilities": request_state.get("mcp_client_capabilities"),
    }


class MCPAuthMiddleware:


    def __init__(self, app: ASGIApp):
        self.app = app

    @staticmethod
    async def _announce_client_connected(
        tenant_key: str | None, user_id: str | None, client_info: dict | None = None
    ) -> None:
        try:
            from api.app_state import state as app_state

            ws_manager = getattr(app_state, "websocket_manager", None)
            if ws_manager and tenant_key:
                from giljo_mcp.events.schemas import EventFactory

                from giljo_mcp.harness_resolver import harness_from_client_info

                harness = harness_from_client_info((client_info or {}).get("name"), (client_info or {}).get("version"))
                event = EventFactory.setup_tool_connected(
                    tenant_key=tenant_key,
                    user_id=str(user_id) if user_id else "unknown",
                    tool_name=harness,
                )
                await ws_manager.broadcast_event_to_tenant(tenant_key=tenant_key, event=event)
        except (OSError, RuntimeError, ValueError, TypeError, AttributeError, ImportError):
            pass

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        guard = await self._pre_auth_guard(scope, receive, send)
        if guard is None:
            return
        receive, request, method, client_info, api_key_value, bearer_token = guard

        tenant_key: str | None = None
        user_id: str | None = None
        api_key_id: str | None = None
        auth_method: str | None = None
        token_scopes: list[str] | None = None
        mcp_session_id: str | None = None

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
                    token_scopes = principal.scopes if principal.scopes is not None else ["mcp:read", "mcp:write"]
                except PrincipalValidationError as exc:
                    if exc.reason in JWT_FALLBACK_REASONS:
                        api_key_value = bearer_token
                        auth_method = None
                        token_scopes = None
                    else:
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
                    api_key_value = bearer_token
                    auth_method = None
                    token_scopes = None

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

        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["tenant_key"] = tenant_key
        scope["state"]["user_id"] = user_id
        scope["state"]["auth_method"] = auth_method
        if token_scopes is not None:
            scope["state"]["scopes"] = token_scopes

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

        if announces_client(method):
            await self._announce_client_connected(tenant_key, user_id, client_info)

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
            return

        _stamp_url_profile(scope)

        from giljo_mcp.tenant import TenantManager, current_tenant

        tenant_token = TenantManager.set_current_tenant(tenant_key)
        try:
            await self.app(scope, receive, send)
        finally:
            current_tenant.reset(tenant_token)

    async def _pre_auth_guard(
        self, scope: Scope, receive: Receive, send: Send
    ) -> tuple[Receive, StarletteRequest, str | None, dict[str, Any] | None, str | None, str | None] | None:
        if scope.get("method") == "GET":
            await _send_method_not_allowed(send)
            return None

        request = StarletteRequest(scope, receive)
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > _MAX_MCP_BODY_BYTES:
            await _send_raw_status(send, status=413)
            return None

        original_receive = receive
        try:
            buffered_body = await _read_full_body(original_receive, max_bytes=_MAX_MCP_BODY_BYTES)
        except _BodyTooLargeError:
            await _send_raw_status(send, status=413)
            return None
        receive = _replay_receive(buffered_body, original_receive)
        method = _peek_jsonrpc_method(buffered_body)
        is_initialize = method == _INITIALIZE_METHOD
        client_info = _peek_jsonrpc_client_info(buffered_body) if announces_client(method) else None
        if is_initialize:
            state_ = scope.setdefault("state", {})
            state_["mcp_protocol_version"] = _peek_jsonrpc_protocol_version(buffered_body)
            state_["mcp_client_capabilities"] = _peek_jsonrpc_capabilities(buffered_body)

        request = StarletteRequest(scope, receive)

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
        if method == _DISCOVER_METHOD:
            await self._record_announced_client(
                tenant_key=tenant_key,
                user_id=user_id,
                api_key_id=api_key_id,
                auth_method=auth_method,
                client_info=client_info,
                **_initialize_capture(request.scope),
            )
            return send

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
            _stamp_declared_profile(scope, session_row)
            _stamp_resolved_harness(scope, session_row)
            _stamp_resolved_preset(scope, session_row)
            from api.endpoints.mcp_session import SESSION_EXTEND_DEBOUNCE_SECONDS, SESSION_EXTEND_NS
            from giljo_mcp.services.debounce import should_run

            if should_run(SESSION_EXTEND_NS, session_row.session_id, SESSION_EXTEND_DEBOUNCE_SECONDS):
                session_row.extend_expiration(MCPSessionManager.DEFAULT_SESSION_LIFETIME_HOURS)
                await db.commit()
        return send

    async def _record_announced_client(
        self,
        *,
        tenant_key: str,
        user_id: str | None,
        api_key_id: str | None = None,
        auth_method: str | None = None,
        client_info: dict[str, Any] | None = None,
        protocol_version: str | None = None,
        capabilities: dict[str, Any] | None = None,
    ) -> None:
        if not tenant_key:
            return
        from api.app_state import state
        from api.endpoints.mcp_session import MCPSessionManager

        if not state.db_manager:
            return
        try:
            async with state.db_manager.get_session_async() as db:
                await MCPSessionManager(db).touch_or_create_client_session(
                    tenant_key=tenant_key,
                    user_id=user_id,
                    api_key_id=api_key_id,
                    client_info=client_info,
                    auth_method="oauth_jwt" if auth_method == "jwt" else auth_method,
                    protocol_version=protocol_version,
                    capabilities=capabilities,
                )
        except (OSError, RuntimeError, ValueError, KeyError, TypeError):
            logger.warning("BE-9586d: could not record announced client (non-fatal)", exc_info=True)

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
