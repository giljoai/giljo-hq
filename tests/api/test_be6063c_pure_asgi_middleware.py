# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport
from httpx import AsyncClient as HTTPXAsyncClient
from starlette.responses import StreamingResponse

from api.middleware import (
    APIMetricsMiddleware,
    AuthMiddleware,
    CSRFProtectionMiddleware,
    InputValidationMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)


pytestmark = pytest.mark.usefixtures("real_rate_limiter")


def _build_stacked_app() -> FastAPI:

    app = FastAPI()
    app.state.api_state = type("S", (), {"api_call_count": {}})()

    @app.get("/api/setup/status")
    async def public_json():
        return {"ok": True}

    @app.get("/api/v1/config/frontend")
    async def public_non_csrf_exempt():
        return {"ok": True}

    @app.get("/api/setup/stream")
    async def public_stream():
        async def gen():
            for i in range(5):
                yield f"chunk-{i};".encode()

        return StreamingResponse(gen(), media_type="text/event-stream")

    app.add_middleware(APIMetricsMiddleware)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(RateLimitMiddleware, requests_per_minute=300)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(InputValidationMiddleware, strict_mode=False)
    app.add_middleware(
        CSRFProtectionMiddleware,
        exempt_paths=["/health"],
        exempt_prefixes=["/api/setup/"],
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:7272"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )
    return app


@pytest.mark.asyncio
async def test_streaming_response_passes_through_unbuffered_with_headers():
    app = _build_stacked_app()
    transport = ASGITransport(app=app)
    async with HTTPXAsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream("GET", "/api/setup/stream") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers["X-Frame-Options"] == "DENY"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert "Content-Security-Policy" in response.headers
            assert response.headers["X-RateLimit-Limit"] == "300"
            assert "content-length" not in response.headers

            chunks = [chunk async for chunk in response.aiter_bytes()]

    body = b"".join(chunks)
    assert body == b"chunk-0;chunk-1;chunk-2;chunk-3;chunk-4;"


@pytest.mark.asyncio
async def test_cors_preflight_answered_through_full_stack():
    app = _build_stacked_app()
    transport = ASGITransport(app=app)
    async with HTTPXAsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.options(
            "/api/setup/status",
            headers={
                "Origin": "http://localhost:7272",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-CSRF-Token",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:7272"
    assert response.headers["access-control-allow-credentials"] == "true"


@pytest.mark.asyncio
async def test_normal_response_carries_combined_header_set():
    app = _build_stacked_app()
    transport = ASGITransport(app=app)
    async with HTTPXAsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/config/frontend")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-RateLimit-Limit"] == "300"
    set_cookie = response.headers.get_list("set-cookie")
    assert any("csrf_token=" in c for c in set_cookie)
