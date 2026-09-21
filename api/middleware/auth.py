# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import time
from pathlib import Path

from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from giljo_mcp.logging import ErrorCode
from giljo_mcp.tenant import TenantManager, current_tenant


logger = logging.getLogger(__name__)

_EXTRA_PUBLIC_PATH_PREFIXES: set[str] = set()


def register_public_path_prefix(prefix: str) -> None:
    normalized = (prefix or "").strip()
    if normalized:
        _EXTRA_PUBLIC_PATH_PREFIXES.add(normalized)


class AuthMiddleware:

    def __init__(self, app: ASGIApp, auth_manager=None):
        self.app = app
        self.get_auth_manager = auth_manager
        self._auth_manager = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        entry_token = current_tenant.set(None)
        try:
            await self._dispatch(Request(scope, receive), scope, receive, send)
        finally:
            current_tenant.reset(entry_token)

    async def _dispatch(self, request: Request, scope: Scope, receive: Receive, send: Send) -> None:
        if self._is_public_endpoint(request.url.path):
            await self.app(scope, receive, send)
            return

        if self.get_auth_manager:
            auth_manager = self.get_auth_manager()
        else:
            auth_manager = getattr(request.app.state, "auth", None)
            if not auth_manager:
                logger.error(
                    "auth_manager_not_configured error_code=%s path=%s method=%s",
                    ErrorCode.API_INTERNAL_ERROR.value,
                    request.url.path,
                    request.method,
                )
                response = JSONResponse(
                    status_code=500,
                    content={
                        "error": "Authentication system error",
                        "detail": "AuthManager not configured",
                    },
                )
                await response(scope, receive, send)
                return

        logger.debug(
            "auth_request_received method=%s path=%s ip=%s has_cookie=%s has_auth=%s",
            request.method,
            request.url.path,
            request.client.host if request.client else "unknown",
            bool(request.headers.get("cookie")),
            bool(request.headers.get("authorization")),
        )

        auth_result = await auth_manager.authenticate_request(request)

        logger.debug(
            "auth_result authenticated=%s user=%s error=%s is_auto_login=%s",
            auth_result.get("authenticated"),
            auth_result.get("user"),
            auth_result.get("error"),
            auth_result.get("is_auto_login", False),
        )

        request.state.authenticated = auth_result.get("authenticated", False)

        if auth_result.get("authenticated"):
            request.state.is_auto_login = auth_result.get("is_auto_login", False)
            request.state.user_id = auth_result.get("user_id")
            request.state.org_api_key_id = auth_result.get("org_api_key_id")
            request.state.auth_user = auth_result.get("user_obj")
            tenant_key = auth_result.get("tenant_key")
            if not tenant_key:
                logger.warning(
                    "authenticated_missing_tenant_key user_id=%s path=%s",
                    auth_result.get("user_id"),
                    request.url.path,
                )
                from api.dependencies.core import _get_default_tenant_key

                tenant_key = _get_default_tenant_key()
            request.state.tenant_key = tenant_key
            request.state.token_exp = auth_result.get("exp")
        else:
            logger.warning(
                "authentication_failed error_code=%s path=%s method=%s ip=%s reason=%s",
                ErrorCode.AUTH_UNAUTHORIZED.value,
                request.url.path,
                request.method,
                request.client.host if request.client else "unknown",
                auth_result.get("error", "No credentials provided"),
            )

            if (
                request.method == "GET"
                and "text/html" in request.headers.get("accept", "")
                and not _is_api_or_static_path(request.url.path)
            ):
                index_html = _resolve_spa_index(request)
                if index_html is not None:
                    response = FileResponse(str(index_html), status_code=200)
                    await response(scope, receive, send)
                    return

            response = JSONResponse(
                status_code=401,
                content={
                    "error": "Authentication required",
                    "detail": auth_result.get("error", "No credentials provided"),
                },
            )
            await response(scope, receive, send)
            return

        tenant_token = None
        if TenantManager.validate_tenant_key(tenant_key):
            tenant_token = TenantManager.set_current_tenant(tenant_key)

        token_exp = getattr(request.state, "token_exp", None)

        async def send_with_token_header(message: Message) -> None:
            if message["type"] == "http.response.start" and token_exp:
                seconds_remaining = max(0, int(token_exp - time.time()))
                MutableHeaders(raw=message["headers"])["X-Token-Expires-In"] = str(seconds_remaining)
            await send(message)

        try:
            await self.app(scope, receive, send_with_token_header)
        finally:
            if tenant_token is not None:
                current_tenant.reset(tenant_token)

    def _is_public_endpoint(self, path: str) -> bool:
        if path in {"/", "/index.html", "/favicon.ico", "/robots.txt"} or path.startswith("/assets/"):
            return True
        static_extensions = (".svg", ".png", ".jpg", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".css")
        if path.endswith(static_extensions) or path.startswith(("/icons/", "/mascot/")):
            return True
        if path in {
            "/login",
            "/first-login",
            "/server-down",
            "/oauth/authorize",
            "/landing",
            "/register",
            "/reset-password",
            "/privacy",
            "/terms",
        }:
            return True
        if path in {"/welcome", "/create-admin"} or path.startswith("/api/setup/"):
            return True
        public_paths = [
            "/health",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/api/auth/login",
            "/api/auth/refresh",
            "/api/auth/create-first-admin",
            "/api/auth/verify-pin",
            "/api/auth/verify-pin-and-reset-password",
            "/api/setup/status",
            "/api/v1/config/frontend",
            "/api/auth/me",
            "/mcp",
            "/api/download/slash-commands.zip",
            "/api/download/install-script",
            "/api/download/temp",
            "/api/oauth/token",
            "/api/oauth/refresh",
            "/api/oauth/revoke",
            "/api/oauth/register",
            "/api/oauth/.well-known/oauth-authorization-server",
            "/.well-known/oauth-authorization-server",
            "/.well-known/oauth-protected-resource",
            "/.well-known/mcp-server-info",
            "/.well-known/openai-apps-challenge",
            "/.well-known/openid-configuration",
            "/api/version/",
        ]
        if path.startswith("/api/download/temp") or "/api/download/temp/" in path:
            return True
        return any(path.startswith(p) for p in public_paths) or any(
            path.startswith(p) for p in _EXTRA_PUBLIC_PATH_PREFIXES
        )



_API_PREFIXES = ("/api", "/ws", "/mcp", "/health", "/docs", "/redoc", "/openapi.json", "/assets/")


def _is_api_or_static_path(path: str) -> bool:
    return path.startswith(_API_PREFIXES)


def _resolve_spa_index(request: Request) -> Path | None:
    state = getattr(request.app.state, "config", None)
    static_path = state.get_nested("paths.static", "frontend/dist") if state else "frontend/dist"
    index_html = Path(static_path) / "index.html"
    return index_html if index_html.exists() else None
