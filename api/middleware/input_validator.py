# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import re
from typing import ClassVar

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


logger = logging.getLogger(__name__)


class InputValidationMiddleware:

    MAX_INSPECTED_CHARS: ClassVar[int] = 8192

    XSS_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"<script\b|javascript:|onerror\s*=|onload\s*=|onclick\s*=|onmouseover\s*=|<iframe\b|<embed\b|<object\b",
        re.IGNORECASE,
    )

    PATH_TRAVERSAL_PATTERNS: ClassVar[list[str]] = [
        r"\.\./",
        r"\.\.\\",
    ]

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)

        for key, value in request.query_params.items():
            if not self._is_safe(value):
                logger.warning(
                    f"Blocked unsafe query parameter: {key} "
                    f"from IP: {request.client.host if request.client else 'unknown'}"
                )
                response = JSONResponse(
                    status_code=400,
                    content={"detail": f"Invalid input detected in query parameter: {key}"},
                )
                await response(scope, receive, send)
                return

        path = request.url.path
        if not self._is_safe_path(path):
            logger.warning(
                f"Blocked path traversal attempt: {path} "
                f"from IP: {request.client.host if request.client else 'unknown'}"
            )
            response = JSONResponse(status_code=400, content={"detail": "Invalid path - path traversal detected"})
            await response(scope, receive, send)
            return


        await self.app(scope, receive, send)

    def _is_safe(self, value: str) -> bool:
        if not isinstance(value, str):
            return True
        return self.XSS_PATTERN.search(value, 0, self.MAX_INSPECTED_CHARS) is None

    def _is_safe_path(self, path: str) -> bool:
        for pattern in self.PATH_TRAVERSAL_PATTERNS:
            if re.search(pattern, path):
                logger.debug(f"Path traversal pattern detected: {pattern} in path: {path}")
                return False
        return True
