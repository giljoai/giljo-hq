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

    TOKEN_LIKE_PARAMS: ClassVar[frozenset[str]] = frozenset({"token", "code", "state"})

    _SQL_COMMENT_MARKER_PATTERN: ClassVar[str] = r"(--|#|\/\*|\*\/)"

    SQL_INJECTION_PATTERNS: ClassVar[list[str]] = [
        r"(\bUNION\b.*\bSELECT\b)",
        r"(\bDROP\b.*\bTABLE\b)",
        r"(\bEXEC\b.*\()",
        _SQL_COMMENT_MARKER_PATTERN,
        r"(\bOR\b.*=.*)",
        r"(\bAND\b.*=.*)",
        r"(\bINSERT\b.*\bINTO\b)",
        r"(\bUPDATE\b.*\bSET\b)",
        r"(\bDELETE\b.*\bFROM\b)",
    ]

    XSS_PATTERNS: ClassVar[list[str]] = [
        r"<script[^>]*>.*?</script>",
        r"javascript:",
        r"onerror\s*=",
        r"onload\s*=",
        r"onclick\s*=",
        r"onmouseover\s*=",
        r"<iframe[^>]*>",
        r"<embed[^>]*>",
        r"<object[^>]*>",
    ]

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
            if not self._is_safe(value, key=key):
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

    def _is_safe(self, value: str, key: str | None = None) -> bool:
        if not isinstance(value, str):
            return True

        skip_comment_marker = key is not None and key.lower() in self.TOKEN_LIKE_PARAMS

        for pattern in self.SQL_INJECTION_PATTERNS:
            if skip_comment_marker and pattern is self._SQL_COMMENT_MARKER_PATTERN:
                continue
            if re.search(pattern, value, re.IGNORECASE):
                logger.debug(f"SQL injection pattern detected: {pattern}")
                return False

        for pattern in self.XSS_PATTERNS:
            if re.search(pattern, value, re.IGNORECASE):
                logger.debug(f"XSS pattern detected: {pattern}")
                return False

        return True

    def _is_safe_path(self, path: str) -> bool:
        for pattern in self.PATH_TRAVERSAL_PATTERNS:
            if re.search(pattern, path):
                logger.debug(f"Path traversal pattern detected: {pattern} in path: {path}")
                return False
        return True
