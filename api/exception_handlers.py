# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import UTC, datetime

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from giljo_mcp.exceptions import BaseGiljoError


logger = logging.getLogger(__name__)


def register_exception_handlers(app):

    @app.exception_handler(BaseGiljoError)
    async def giljo_exception_handler(request: Request, exc: BaseGiljoError):
        status_code = exc.default_status_code
        log_method = logger.warning if 400 <= status_code < 500 else logger.error
        log_method(f"{exc.error_code}: {exc.message}", extra={"context": exc.context})
        return JSONResponse(status_code=status_code, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/api/oauth/"):
            fields = ", ".join(
                f"{'.'.join(str(part) for part in error.get('loc', ()) if part != 'body')}: {error.get('type', '')}"
                for error in exc.errors()
            )
            logger.warning("OAuth request validation failed on %s: %s", request.url.path, fields)
        sanitized_errors = []
        for error in exc.errors():
            sanitized = {
                "loc": error.get("loc", []),
                "msg": error.get("msg", ""),
                "type": error.get("type", ""),
            }
            input_val = error.get("input")
            if input_val is not None and isinstance(input_val, (str, int, float, bool, list, dict, type(None))):
                sanitized["input"] = input_val
            sanitized_errors.append(sanitized)

        return JSONResponse(
            status_code=422,
            content={
                "error_code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "errors": sanitized_errors,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        detail = exc.detail
        if isinstance(detail, dict) and isinstance(detail.get("error_code"), str):
            content = {
                "error_code": detail["error_code"],
                "message": detail.get("message", ""),
                "timestamp": datetime.now(UTC).isoformat(),
            }
            context = {k: v for k, v in detail.items() if k not in {"error_code", "message"}}
            if context:
                content["context"] = context
            return JSONResponse(status_code=exc.status_code, content=content, headers=getattr(exc, "headers", None))

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error_code": "HTTP_ERROR",
                "message": detail,
                "timestamp": datetime.now(UTC).isoformat(),
            },
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def unexpected_exception_handler(request: Request, exc: Exception):
        logger.exception(f"Unexpected error: {exc}")
        return JSONResponse(
            status_code=500,
            content={
                "error_code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
