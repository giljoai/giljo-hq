# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import secrets

from fastapi import HTTPException, Request
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send


logger = logging.getLogger(__name__)

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

    def _get_token_from_cookie(self, request: Request) -> str:
        return request.cookies.get(self.cookie_name)

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

            if request_token != cookie_token:
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

        existing_token = request.cookies.get(self.cookie_name)
        set_cookie_value: str | None = None
        if not existing_token or request.method == "GET":
            token = existing_token or self._generate_token()
            cookie_carrier = Response()
            cookie_carrier.set_cookie(
                key=self.cookie_name,
                value=token,
                httponly=False,
                secure=request.url.scheme == "https",
                samesite="lax",
                path="/",
                max_age=86400,
            )
            set_cookie_value = cookie_carrier.headers["set-cookie"]
            if not existing_token:
                logger.debug(f"Generated new CSRF token for IP: {request.client.host if request.client else 'unknown'}")

        if set_cookie_value is None:
            await self.app(scope, receive, send)
            return

        async def send_with_cookie(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(raw=message["headers"]).append("set-cookie", set_cookie_value)
            await send(message)

        await self.app(scope, receive, send_with_cookie)


def get_csrf_token(request: Request) -> str:
    return request.cookies.get("csrf_token", "")


class CSRFProtectionOptional:

    def __init__(self, cookie_name: str = "csrf_token", header_name: str = "X-CSRF-Token"):
        self.cookie_name = cookie_name
        self.header_name = header_name

    def __call__(self, func):

        async def wrapper(*args, **kwargs):
            request = kwargs.get("request") or (args[0] if args else None)

            if not request or not isinstance(request, Request):
                logger.error("CSRFProtectionOptional: Could not extract Request object")
                return await func(*args, **kwargs)

            request_token = request.headers.get(self.header_name)
            cookie_token = request.cookies.get(self.cookie_name)

            if not request_token or not cookie_token or request_token != cookie_token:
                logger.warning(
                    f"CSRF validation failed in decorator: "
                    f"path={request.url.path}, IP={request.client.host if request.client else 'unknown'}"
                )
                raise HTTPException(status_code=403, detail="CSRF validation failed")

            return await func(*args, **kwargs)

        return wrapper
