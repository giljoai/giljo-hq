# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock

from fastapi import FastAPI

from api.exception_handlers import _SANITIZED_SERVER_ERROR, register_exception_handlers
from giljo_mcp.exceptions import BaseGiljoError, DatabaseError, ResourceNotFoundError, ValidationError


_RAW_SQL_ERROR = (
    "(psycopg2.errors.UniqueViolation) duplicate key value violates unique constraint "
    "[SQL: SELECT products.id FROM products WHERE products.tenant_key = %(tenant_key_1)s] "
    "[parameters: {'tenant_key_1': 'tk_aaaaaaaaaaaaaaaa'}]"
)
_BIND_VALUE = "tk_aaaaaaaaaaaaaaaa"


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


async def test_a_5xx_database_error_does_not_leak_sql_or_bind_values():
    app = _build_app()
    handler = _get_handler(app)
    exc = DatabaseError(_RAW_SQL_ERROR)

    response = await handler(_make_request(), exc)

    raw_body = bytes(response.body).decode()
    assert response.status_code == 500
    assert "SELECT" not in raw_body, "raw SQL reached the REST body"
    assert _BIND_VALUE not in raw_body, "a bind value reached the REST body"

    body = json.loads(raw_body)
    assert body["message"] == _SANITIZED_SERVER_ERROR
    assert "context" not in body


async def test_a_5xx_error_carrying_the_leak_in_context_is_also_sanitized():
    app = _build_app()
    handler = _get_handler(app)
    exc = DatabaseError("orchestration step failed", context={"error": _RAW_SQL_ERROR})

    response = await handler(_make_request(), exc)

    raw_body = bytes(response.body).decode()
    assert "SELECT" not in raw_body
    assert _BIND_VALUE not in raw_body


async def test_4xx_not_found_message_and_context_are_unchanged():
    app = _build_app()
    handler = _get_handler(app)
    exc = ResourceNotFoundError("Product 'p-1' not found for tenant", context={"product_id": "p-1"})

    response = await handler(_make_request(), exc)

    body = json.loads(bytes(response.body).decode())
    assert response.status_code == 404
    assert body["message"] == "Product 'p-1' not found for tenant"
    assert body["context"] == {"product_id": "p-1"}


async def test_4xx_validation_error_message_is_unchanged():
    app = _build_app()
    handler = _get_handler(app)
    exc = ValidationError("nope")

    response = await handler(_make_request(), exc)

    body = json.loads(bytes(response.body).decode())
    assert response.status_code == 400
    assert body["message"] == "nope"


async def test_the_server_log_still_carries_the_full_error(caplog):
    app = _build_app()
    handler = _get_handler(app)
    exc = DatabaseError(_RAW_SQL_ERROR)

    with caplog.at_level(logging.DEBUG, logger="api.exception_handlers"):
        await handler(_make_request(), exc)

    records = [r for r in caplog.records if r.name == "api.exception_handlers"]
    assert len(records) == 1
    assert "SELECT" in records[0].getMessage()
    assert _BIND_VALUE in records[0].getMessage()
    assert records[0].levelno == logging.ERROR
