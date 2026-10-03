# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from httpx import AsyncClient as HTTPXAsyncClient

from api.middleware.input_validator import InputValidationMiddleware


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/setup/status")
    async def public_json():
        return {"ok": True}

    app.add_middleware(InputValidationMiddleware)
    return app


@pytest.mark.asyncio
async def test_token_param_with_sql_comment_marker_is_never_logged(caplog):
    app = _build_app()
    transport = ASGITransport(app=app)
    with caplog.at_level(logging.DEBUG, logger="api.middleware.input_validator"):
        async with HTTPXAsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/api/setup/status", params={"token": "abc--def"})

    logged_text = "\n".join(
        record.getMessage() for record in caplog.records if record.name == "api.middleware.input_validator"
    )
    assert "abc--def" not in logged_text


@pytest.mark.asyncio
async def test_token_param_with_sql_comment_marker_is_not_blocked():
    app = _build_app()
    transport = ASGITransport(app=app)
    async with HTTPXAsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/setup/status", params={"token": "abc--def"})

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_non_token_param_with_sql_comment_marker_still_blocked_but_not_logged(caplog):
    app = _build_app()
    transport = ASGITransport(app=app)
    with caplog.at_level(logging.DEBUG, logger="api.middleware.input_validator"):
        async with HTTPXAsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/setup/status", params={"q": "abc--def"})

    assert response.status_code == 400
    logged_text = "\n".join(
        record.getMessage() for record in caplog.records if record.name == "api.middleware.input_validator"
    )
    assert "abc--def" not in logged_text


@pytest.mark.asyncio
async def test_token_param_still_blocks_a_real_sql_injection_pattern():
    app = _build_app()
    transport = ASGITransport(app=app)
    async with HTTPXAsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/setup/status", params={"token": "x UNION SELECT password FROM users"})

    assert response.status_code == 400
