# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import re
from typing import Any, ClassVar

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


logger = logging.getLogger(__name__)


class InputValidationMiddleware:

    SQL_INJECTION_PATTERNS: ClassVar[list[str]] = [
        r"(\bUNION\b.*\bSELECT\b)",
        r"(\bDROP\b.*\bTABLE\b)",
        r"(\bEXEC\b.*\()",
        r"(--|#|\/\*|\*\/)",
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

    def __init__(self, app: ASGIApp, strict_mode: bool = False):
        self.app = app
        self.strict_mode = strict_mode
        logger.info(f"InputValidationMiddleware initialized (strict_mode: {strict_mode})")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)

        for key, value in request.query_params.items():
            if not self._is_safe(value):
                logger.warning(
                    f"Blocked unsafe query parameter: {key}={value[:50]}... "
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

        for pattern in self.SQL_INJECTION_PATTERNS:
            if re.search(pattern, value, re.IGNORECASE):
                logger.debug(f"SQL injection pattern detected: {pattern} in value: {value[:50]}...")
                return False

        for pattern in self.XSS_PATTERNS:
            if re.search(pattern, value, re.IGNORECASE):
                logger.debug(f"XSS pattern detected: {pattern} in value: {value[:50]}...")
                return False

        return True

    def _is_safe_path(self, path: str) -> bool:
        for pattern in self.PATH_TRAVERSAL_PATTERNS:
            if re.search(pattern, path):
                logger.debug(f"Path traversal pattern detected: {pattern} in path: {path}")
                return False
        return True


class RequestSanitizer:

    @staticmethod
    def sanitize_string(value: str) -> str:
        if not isinstance(value, str):
            return value

        return (
            value.strip()
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#x27;")
            .replace("/", "&#x2F;")
        )

    @staticmethod
    def sanitize_dict(data: dict) -> dict:
        sanitized = {}
        for key, value in data.items():
            if isinstance(value, str):
                sanitized[key] = RequestSanitizer.sanitize_string(value)
            elif isinstance(value, dict):
                sanitized[key] = RequestSanitizer.sanitize_dict(value)
            elif isinstance(value, list):
                sanitized[key] = RequestSanitizer.sanitize_list(value)
            else:
                sanitized[key] = value
        return sanitized

    @staticmethod
    def sanitize_list(data: list) -> list:
        sanitized = []
        for item in data:
            if isinstance(item, str):
                sanitized.append(RequestSanitizer.sanitize_string(item))
            elif isinstance(item, dict):
                sanitized.append(RequestSanitizer.sanitize_dict(item))
            elif isinstance(item, list):
                sanitized.append(RequestSanitizer.sanitize_list(item))
            else:
                sanitized.append(item)
        return sanitized

    def sanitize(self, data: Any) -> Any:
        if isinstance(data, str):
            return self.sanitize_string(data)
        if isinstance(data, dict):
            return self.sanitize_dict(data)
        if isinstance(data, list):
            return self.sanitize_list(data)
        return data


def sanitize(data: Any) -> Any:
    return RequestSanitizer().sanitize(data)
