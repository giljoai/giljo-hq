# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re

from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


DEFAULT_MAX_BODY_BYTES = 1024 * 1024

_MULTIPART_OVERHEAD_BYTES = 64 * 1024

_UPLOAD_ROUTES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("POST", re.compile(r"^/api/v1/products/[^/]+/vision/?$")),
    ("POST", re.compile(r"^/api/vision-documents/?$")),
    ("PUT", re.compile(r"^/api/vision-documents/[^/]+/?$")),
)


PRODUCT_WRITE_MAX_BODY_BYTES = 2 * 1024 * 1024

_PRODUCT_WRITE_ROUTES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("POST", re.compile(r"^/api/v1/products/?$")),
    ("PUT", re.compile(r"^/api/v1/products/[^/]+/?$")),
)


def _matches(routes: tuple[tuple[str, re.Pattern[str]], ...], method: str, path: str) -> bool:
    return any(method == route_method and pattern.match(path) for route_method, pattern in routes)


def _upload_max_bytes() -> int:
    from giljo_mcp.config_manager import get_config

    return get_config().upload.max_upload_bytes + _MULTIPART_OVERHEAD_BYTES


class BodySizeLimitMiddleware:

    def __init__(self, app: ASGIApp, default_max_bytes: int = DEFAULT_MAX_BODY_BYTES) -> None:
        self.app = app
        self.default_max_bytes = default_max_bytes

    def _limit_for(self, method: str, path: str) -> int:
        if _matches(_UPLOAD_ROUTES, method, path):
            return max(self.default_max_bytes, _upload_max_bytes())
        if _matches(_PRODUCT_WRITE_ROUTES, method, path):
            return max(self.default_max_bytes, PRODUCT_WRITE_MAX_BODY_BYTES)
        return self.default_max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = self._limit_for(scope.get("method", ""), scope.get("path", ""))
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await _too_large(limit)(scope, receive, send)
            return

        received = 0
        app_started_response = False
        cut_off = False
        rejected = False

        async def capped_receive() -> Message:
            nonlocal received, cut_off, rejected
            if cut_off:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    cut_off = True
                    if not app_started_response:
                        rejected = True
                        await _too_large(limit)(scope, receive, send)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal app_started_response
            if rejected:
                return
            if message["type"] == "http.response.start":
                app_started_response = True
            await send(message)

        try:
            await self.app(scope, capped_receive, guarded_send)
        except Exception:
            if not rejected:
                raise


def _too_large(limit: int) -> JSONResponse:
    return JSONResponse(
        status_code=413,
        content={"detail": f"Request body is too large. The limit is {limit} bytes."},
    )


CONNECTOR_ORIGINS: tuple[str, ...] = ("https://claude.ai", "https://claude.com")
_CONNECTOR_PATH_PREFIXES: tuple[str, ...] = ("/mcp/", "/.well-known/", "/api/oauth/")


def _is_connector_path(path: str) -> bool:
    return path == "/mcp" or path.startswith(_CONNECTOR_PATH_PREFIXES)


class ConnectorCorsMiddleware:

    def __init__(self, app: ASGIApp, **cors_options) -> None:
        self.app = app
        self._connector_cors = CORSMiddleware(
            app, allow_origins=list(CONNECTOR_ORIGINS), allow_credentials=False, **cors_options
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and _is_connector_path(scope.get("path", ""))
            and Headers(scope=scope).get("origin") in CONNECTOR_ORIGINS
        ):
            await self._connector_cors(scope, receive, _without_credentials(send))
            return
        await self.app(scope, receive, send)


def _without_credentials(send: Send) -> Send:
    async def send_without_credentials(message: Message) -> None:
        if message["type"] == "http.response.start":
            del MutableHeaders(scope=message)["access-control-allow-credentials"]
        await send(message)

    return send_without_credentials
