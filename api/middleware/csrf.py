# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import secrets

from fastapi import Request
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send


logger = logging.getLogger(__name__)

HOST_COOKIE_PREFIX = "__Host-"

_STATE_EXEMPT_PATHS = "csrf_exempt_paths"
_STATE_EXEMPT_PREFIXES = "csrf_exempt_prefixes"


def register_csrf_exempt_path(app, path: str) -> None:
    normalized = (path or "").strip()
    if not normalized:
        return
    current: set[str] = getattr(app.state, _STATE_EXEMPT_PATHS, set())
    current.add(normalized)
    setattr(app.state, _STATE_EXEMPT_PATHS, current)


def register_csrf_exempt_prefix(app, prefix: str) -> None:
    normalized = (prefix or "").strip()
    if not normalized:
        return
    current: set[str] = getattr(app.state, _STATE_EXEMPT_PREFIXES, set())
    current.add(normalized)
    setattr(app.state, _STATE_EXEMPT_PREFIXES, current)


class CSRFProtectionMiddleware:

    def __init__(
        self,
        app: ASGIApp,
        exempt_paths: list = None,
        exempt_prefixes: list = None,
        cookie_name: str = "csrf_token",
        header_name: str = "X-CSRF-Token",
        api_key_header: str = "X-API-Key",
    ):
        self.app = app
        self.exempt_paths = exempt_paths or []
        self.exempt_prefixes = exempt_prefixes or []
        self.cookie_name = cookie_name
        self.header_name = header_name
        self.api_key_header = api_key_header
        logger.info(
            f"CSRFProtectionMiddleware initialized: "
            f"cookie={cookie_name}, header={header_name}, "
            f"exempt_paths={self.exempt_paths}, exempt_prefixes={self.exempt_prefixes}"
        )

    def _generate_token(self) -> str:
        return secrets.token_urlsafe(32)

    def _get_token_from_request(self, request: Request) -> str:
        token = request.headers.get(self.header_name)
        if token:
            return token


        return None

    def _cookie_name_for(self, request: Request) -> str:
        if request.url.scheme == "https":
            return f"{HOST_COOKIE_PREFIX}{self.cookie_name}"
        return self.cookie_name

    def _get_token_from_cookie(self, request: Request) -> str:
        return request.cookies.get(self._cookie_name_for(request))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)

        path = request.url.path
        extra_paths: set[str] = getattr(request.app.state, _STATE_EXEMPT_PATHS, set())
        extra_prefixes: set[str] = getattr(request.app.state, _STATE_EXEMPT_PREFIXES, set())
        if (
            path in self.exempt_paths
            or path in extra_paths
            or any(path.startswith(p) for p in self.exempt_prefixes)
            or any(path.startswith(p) for p in extra_prefixes)
        ):
            await self.app(scope, receive, send)
            return

        if request.headers.get(self.api_key_header):
            await self.app(scope, receive, send)
            return

        if request.method in ["POST", "PUT", "PATCH", "DELETE"]:
            request_token = self._get_token_from_request(request)
            cookie_token = self._get_token_from_cookie(request)

            if not request_token or not cookie_token:
                logger.warning(
                    f"CSRF validation failed - missing token: "
                    f"path={request.url.path}, method={request.method}, "
                    f"IP={request.client.host if request.client else 'unknown'}, "
                    f"has_cookie={bool(cookie_token)}, has_header={bool(request_token)}"
                )
                response = JSONResponse(
                    status_code=403,
                    content={
                        "detail": "CSRF validation failed - missing token. "
                        "Include X-CSRF-Token header in state-changing requests."
                    },
                )
                await response(scope, receive, send)
                return

            if not secrets.compare_digest(request_token.encode(), cookie_token.encode()):
                logger.warning(
                    f"CSRF validation failed - token mismatch: "
                    f"path={request.url.path}, method={request.method}, "
                    f"IP={request.client.host if request.client else 'unknown'}"
                )
                response = JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF validation failed - invalid token"},
                )
                await response(scope, receive, send)
                return

        existing_token = self._get_token_from_cookie(request)
        cookie_carrier = Response()
        if not existing_token or request.method == "GET":
            token = existing_token or self._generate_token()
            cookie_carrier.set_cookie(
                key=self._cookie_name_for(request),
                value=token,
                httponly=False,
                secure=request.url.scheme == "https",
                samesite="lax",
                path="/",
                max_age=86400,
            )
            if not existing_token:
                logger.debug(f"Generated new CSRF token for IP: {request.client.host if request.client else 'unknown'}")
        if request.url.scheme == "https" and self.cookie_name in request.cookies:
            cookie_carrier.delete_cookie(key=self.cookie_name, path="/", secure=True, samesite="lax")

        set_cookie_values = [
            value.decode("latin-1") for key, value in cookie_carrier.raw_headers if key == b"set-cookie"
        ]
        if not set_cookie_values:
            await self.app(scope, receive, send)
            return

        async def send_with_cookie(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(raw=message["headers"])
                for value in set_cookie_values:
                    headers.append("set-cookie", value)
            await send(message)

        await self.app(scope, receive, send_with_cookie)


def get_csrf_token(request: Request) -> str:
    return request.cookies.get(f"{HOST_COOKIE_PREFIX}csrf_token") or request.cookies.get("csrf_token", "")
