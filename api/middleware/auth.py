# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Authentication Middleware

Handles authentication for all API requests.

This is the existing AuthMiddleware from api/middleware.py,
moved to the new middleware directory structure in Handover 0129c.
"""

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
    """Allow private edition modules to register public auth bypass prefixes."""
    normalized = (prefix or "").strip()
    if normalized:
        _EXTRA_PUBLIC_PATH_PREFIXES.add(normalized)


class AuthMiddleware:
    """
    Authentication middleware - ALWAYS ACTIVE (unified auth).

    All clients (localhost and network) require JWT or API key.
    No special treatment for localhost - ensures production parity.

    This middleware provides consistent authentication regardless
    of client location (localhost or network).

    Pure-ASGI (BE-6063c): no BaseHTTPMiddleware task-group/stream tax. State is
    written through ``request.state`` (backed by ``scope["state"]``) so all
    downstream middleware and endpoints read the exact same ``tenant_key`` /
    ``auth_user`` / etc. as before. The ContextVar reset-at-entry leak guard
    (BE6004C-1) and the bcrypt-off-loop pre-auth path (BE-6060a/BE-6061, inside
    ``authenticate_request``) are preserved unchanged.
    """

    def __init__(self, app: ASGIApp, auth_manager=None):
        """
        Initialize authentication middleware.

        Args:
            app: ASGI application
            auth_manager: Optional callable that returns AuthManager instance
                         (e.g., lambda: state.auth)
        """
        self.app = app
        # Store callable that returns auth manager
        self.get_auth_manager = auth_manager
        self._auth_manager = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process all HTTP requests through authentication."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Reset-at-entry for ALL branches (BE6004C-1): neutralize any tenant
        # value left on a reused worker task by a prior request, and capture a
        # token so we restore the EXACT pre-request value on every exit path
        # (public, failed-auth, authenticated, exception). Without this a
        # contextvar set during one request could be observed by the next one
        # routed to the same worker — a latent cross-tenant leak.
        entry_token = current_tenant.set(None)
        try:
            await self._dispatch(Request(scope, receive), scope, receive, send)
        finally:
            current_tenant.reset(entry_token)

    async def _dispatch(self, request: Request, scope: Scope, receive: Receive, send: Send) -> None:
        """Authentication body. Wrapped by __call__() for ContextVar lifecycle."""
        # Public endpoints bypass auth as early as possible
        if self._is_public_endpoint(request.url.path):
            await self.app(scope, receive, send)
            return

        # Get auth manager (from callable or fallback to app state)
        if self.get_auth_manager:
            auth_manager = self.get_auth_manager()
        else:
            # Fallback: get from app state
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

        # DIAGNOSTIC: Log incoming request details
        logger.debug(
            "auth_request_received method=%s path=%s ip=%s has_cookie=%s has_auth=%s",
            request.method,
            request.url.path,
            request.client.host if request.client else "unknown",
            bool(request.headers.get("cookie")),
            bool(request.headers.get("authorization")),
        )

        auth_result = await auth_manager.authenticate_request(request)

        # DIAGNOSTIC: Log auth result
        logger.debug(
            "auth_result authenticated=%s user=%s error=%s is_auto_login=%s",
            auth_result.get("authenticated"),
            auth_result.get("user"),
            auth_result.get("error"),
            auth_result.get("is_auto_login", False),
        )

        # Set request state consistently
        request.state.authenticated = auth_result.get("authenticated", False)

        if auth_result.get("authenticated"):
            request.state.is_auto_login = auth_result.get("is_auto_login", False)
            # Authenticated principal identity for downstream middleware. This is
            # edition-neutral request context (not a SaaS feature): user_id is the
            # JWT username / API-key name, org_api_key_id is set only when a SaaS
            # org API key authenticated the request. The SaaS per-user rate limiter
            # (BE-6022) keys its bucket off these; CE never reads them.
            request.state.user_id = auth_result.get("user_id")
            request.state.org_api_key_id = auth_result.get("org_api_key_id")
            # BE-6063a: stash the User the middleware already resolved so the
            # request-scoped get_current_user dependency can reuse it instead of
            # issuing a SECOND identical SELECT User per request. The object is
            # detached (loaded in auth_manager's own session, expire_on_commit=
            # False so its column values survive); get_current_user re-asserts
            # is_active + identity + tenant and merge(load=False)s it onto the
            # request session, so no security check is dropped and no query runs.
            request.state.auth_user = auth_result.get("user_obj")
            tenant_key = auth_result.get("tenant_key")
            if not tenant_key:
                logger.warning(
                    "authenticated_missing_tenant_key user_id=%s path=%s",
                    auth_result.get("user_id"),
                    request.url.path,
                )
                # Fall back to config-based default for setup/localhost mode only
                from api.dependencies.core import _get_default_tenant_key

                tenant_key = _get_default_tenant_key()
            request.state.tenant_key = tenant_key
            # Stash token expiry for downstream use and response header
            request.state.token_exp = auth_result.get("exp")
        else:
            # Auth failed.
            logger.warning(
                "authentication_failed error_code=%s path=%s method=%s ip=%s reason=%s",
                ErrorCode.AUTH_UNAUTHORIZED.value,
                request.url.path,
                request.method,
                request.client.host if request.client else "unknown",
                auth_result.get("error", "No credentials provided"),
            )

            # SPA fallback: if a browser navigated to an authenticated route
            # while logged out (bookmark, F5 refresh, address-bar entry), serve
            # index.html so Vue Router can boot and redirect to /login. Without
            # this the user sees a raw JSON 401 — terrible UX, looks broken.
            #
            # Detection: GET requests where Accept includes text/html and the
            # path is NOT an API/WebSocket/static path. API callers (axios,
            # fetch, MCP clients) send Accept: application/json and still get
            # the canonical 401, preserving the API contract.
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
            # Capture the token so the finally restores the EXACT prior value
            # via reset() instead of set(previous), which would clobber an
            # outer tenant if one were ever active (BE6004C-1 leak fix).
            tenant_token = TenantManager.set_current_tenant(tenant_key)

        # Add the token-expiry header on the downstream response's start message
        # (frontend tracks remaining session time). Computed at send time so it
        # reflects the same request.state.token_exp set above.
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
        """Check if endpoint is public (no authentication required)"""
        # BE-9420: /robots.txt joins the root files a crawler fetches unauthenticated.
        # It answered 401 because ".txt" is absent from the static-extension list
        # below -- so the one file whose entire job is to be read before anything
        # else was the one file that required a session. Carved out by LITERAL PATH,
        # never by extension: admitting ".txt" would make every future text file
        # under the SPA root world-readable, which is a far wider change than this.
        if path in {"/", "/index.html", "/favicon.ico", "/robots.txt"} or path.startswith("/assets/"):
            return True
        # Static files served from frontend/public (logos, icons, mascot)
        static_extensions = (".svg", ".png", ".jpg", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".css")
        if path.endswith(static_extensions) or path.startswith(("/icons/", "/mascot/")):
            return True
        # Vue Router SPA routes — must serve index.html without auth so F5 refresh works
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
        # Setup wizard routes must be accessible before any user exists
        if path in {"/welcome", "/create-admin"} or path.startswith("/api/setup/"):
            return True
        public_paths = [
            "/health",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/api/auth/login",  # Login endpoint
            "/api/auth/refresh",  # Token refresh (handles own auth via cookie)
            "/api/auth/create-first-admin",  # First admin creation (Handover 0034)
            "/api/auth/verify-pin",  # PIN verification step (no auth — user forgot password)
            "/api/auth/verify-pin-and-reset-password",  # Password reset via recovery PIN (no auth — user forgot password)
            "/api/setup/status",  # Fresh install detection (Handover 0034)
            "/api/v1/config/frontend",  # Frontend config
            "/api/auth/me",  # Auth status check
            "/mcp",  # MCP-over-HTTP endpoint (handles own auth via X-API-Key)
            "/api/download/slash-commands.zip",  # Public slash command downloads
            "/api/download/install-script",  # Public install scripts
            "/api/download/agent-templates.zip",  # Optional-auth downloads (handles own auth logic)
            "/api/download/temp",  # Public download with token auth (one-time tokens)
            "/api/oauth/token",  # OAuth token exchange (public, PKCE-protected)
            "/api/oauth/refresh",  # OAuth refresh-token grant (public route; rotating-token / secret protected)
            "/api/oauth/revoke",  # RFC 7009 token revocation (public — the token IS the credential, API-0022)
            "/api/oauth/register",  # CE RFC 7591 Dynamic Client Registration (public — external MCP clients, BE-6235)
            "/api/oauth/.well-known/oauth-authorization-server",  # OAuth server metadata
            "/.well-known/oauth-authorization-server",  # RFC 8414 root mirror (API-0021a)
            "/.well-known/oauth-protected-resource",  # RFC 9728 resource metadata (API-0021a)
            "/.well-known/mcp-server-info",  # MCP spec-version + capability discovery (API-0021h)
            "/.well-known/openid-configuration",  # OIDC discovery probe — handler returns 404 (API-0021i)
            "/api/version/",  # Version check (installers need this before auth exists)
        ]
        # Always allow token download path (token is the auth)
        if path.startswith("/api/download/temp") or "/api/download/temp/" in path:
            return True
        return any(path.startswith(p) for p in public_paths) or any(
            path.startswith(p) for p in _EXTRA_PUBLIC_PATH_PREFIXES
        )


# ─── SPA-fallback helpers ──────────────────────────────────────────────────
# Used by the auth middleware to serve index.html instead of a JSON 401 when
# a logged-out browser navigates to an authenticated route. Mirrors the
# 404-handler pattern in api/app.py so behavior stays consistent across the
# two fallback paths.

_API_PREFIXES = ("/api", "/ws", "/mcp", "/health", "/docs", "/redoc", "/openapi.json", "/assets/")


def _is_api_or_static_path(path: str) -> bool:
    """True if the path is an API route, WebSocket, or built asset (not an SPA route)."""
    return path.startswith(_API_PREFIXES)


def _resolve_spa_index(request: Request) -> Path | None:
    """Locate the SPA index.html, or None if frontend isn't built."""
    state = getattr(request.app.state, "config", None)
    static_path = state.get_nested("paths.static", "frontend/dist") if state else "frontend/dist"
    index_html = Path(static_path) / "index.html"
    return index_html if index_html.exists() else None
