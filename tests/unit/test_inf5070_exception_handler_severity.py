# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI

from api.exception_handlers import register_exception_handlers
from giljo_mcp.exceptions import BaseGiljoError


pytestmark = pytest.mark.informational


class _Boom4xxError(BaseGiljoError):
    default_status_code = 401


class _BoomForbiddenError(BaseGiljoError):
    default_status_code = 403


class _BoomNotFoundError(BaseGiljoError):
    default_status_code = 404


class _BoomConflictError(BaseGiljoError):
    default_status_code = 409


class _BoomUnprocessableError(BaseGiljoError):
    default_status_code = 422


class _BoomRateLimitError(BaseGiljoError):
    default_status_code = 429


class _Boom5xxError(BaseGiljoError):
    default_status_code = 500


class _BoomBadGatewayError(BaseGiljoError):
    default_status_code = 502


class _BoomServiceUnavailableError(BaseGiljoError):
    default_status_code = 503


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    return app


def _make_request() -> MagicMock:
    request = MagicMock()
    request.url.path = "/api/test"
    return request


def _get_handler(app: FastAPI):
    return app.exception_handlers[BaseGiljoError]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc_cls",
    [
        _Boom4xxError,
        _BoomForbiddenError,
        _BoomNotFoundError,
        _BoomConflictError,
        _BoomUnprocessableError,
        _BoomRateLimitError,
    ],
)
async def test_4xx_logged_at_warning(caplog, exc_cls):
    app = _build_app()
    handler = _get_handler(app)
    exc = exc_cls("client did something wrong")

    with caplog.at_level(logging.DEBUG, logger="api.exception_handlers"):
        response = await handler(_make_request(), exc)

    assert response.status_code == exc.default_status_code
    records = [r for r in caplog.records if r.name == "api.exception_handlers"]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING, (
        f"4xx ({exc.default_status_code}) was logged at {records[0].levelname}, "
        f"expected WARNING -- this would re-flood Sentry"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("exc_cls", [_Boom5xxError, _BoomBadGatewayError, _BoomServiceUnavailableError])
async def test_5xx_logged_at_error(caplog, exc_cls):
    app = _build_app()
    handler = _get_handler(app)
    exc = exc_cls("backend exploded")

    with caplog.at_level(logging.DEBUG, logger="api.exception_handlers"):
        response = await handler(_make_request(), exc)

    assert response.status_code == exc.default_status_code
    records = [r for r in caplog.records if r.name == "api.exception_handlers"]
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR, (
        f"5xx ({exc.default_status_code}) was logged at {records[0].levelname}, "
        f"expected ERROR -- this would suppress real alerts"
    )


@pytest.mark.asyncio
async def test_response_shape_preserved(caplog):
    app = _build_app()
    handler = _get_handler(app)
    exc = _BoomNotFoundError("project xyz", context={"id": "xyz"})

    with caplog.at_level(logging.DEBUG, logger="api.exception_handlers"):
        response = await handler(_make_request(), exc)

    import json

    body = json.loads(bytes(response.body).decode())
    assert body["error_code"] == "_BOOMNOTFOUNDERROR"
    assert body["message"] == "project xyz"
    assert body["context"] == {"id": "xyz"}
    assert body["status_code"] == 404


@pytest.mark.asyncio
async def test_log_message_carries_error_code(caplog):
    app = _build_app()
    handler = _get_handler(app)
    exc = _Boom4xxError("invalid password", error_code="AUTHENTICATION_ERROR")

    with caplog.at_level(logging.DEBUG, logger="api.exception_handlers"):
        await handler(_make_request(), exc)

    records = [r for r in caplog.records if r.name == "api.exception_handlers"]
    assert "AUTHENTICATION_ERROR" in records[0].getMessage()
    assert "invalid password" in records[0].getMessage()
