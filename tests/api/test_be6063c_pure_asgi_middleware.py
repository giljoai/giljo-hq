# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
BE-6063c: pure-ASGI middleware-stack behavior locks.

The six custom security middleware (auth, csrf, metrics, rate_limiter,
security, input_validator) were converted from ``BaseHTTPMiddleware`` to pure
ASGI to shed the per-layer anyio task-group + memory-stream tax (~45us/layer,
~271us across the stack — see the BE6063C perf spike results).
This file locks the two behaviors a pure-ASGI rewrite is most likely to break
and that the per-middleware tests do not cover end-to-end:

1. **Streaming / SSE pass-through is unbuffered.** A pure-ASGI middleware must
   forward each ``http.response.body`` chunk as the downstream app emits it and
   must NOT consume+replay the response body the way BaseHTTPMiddleware did.
   This is the /mcp SSE regression class (BE-6060 lore). We drive the FULL
   wired middleware stack and assert a chunked StreamingResponse arrives
   chunk-by-chunk with the security headers still injected on the start message.

2. **The stack composes correctly across layers.** A CORS OPTIONS preflight is
   answered (CORS pure-ASGI, untouched) and security headers + rate-limit
   headers ride on a normal response — i.e. the send-wrapping layers (auth /
   security / rate_limit / csrf) all chain without clobbering one another.

Edition Scope: Both (core runtime). CE-mode app; no SaaS middleware involved.
"""

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


def _build_stacked_app() -> FastAPI:
    """A FastAPI app wired with the same converted middleware in the same
    security-load-bearing order as ``api/wiring/middleware.py`` (last added =
    first executed). Endpoints are public so the auth layer passes through —
    this isolates the *plumbing* (streaming + header injection + ordering) from
    auth credential mechanics, which the auth unit tests cover separately."""

    app = FastAPI()
    app.state.api_state = type("S", (), {"api_call_count": {}})()

    @app.get("/api/setup/status")
    async def public_json():
        return {"ok": True}

    # Auth-public (in AuthMiddleware._is_public_endpoint) but NOT under any CSRF
    # exempt prefix — so the CSRF layer runs its cookie-set path on this GET.
    @app.get("/api/v1/config/frontend")
    async def public_non_csrf_exempt():
        return {"ok": True}

    @app.get("/api/setup/stream")
    async def public_stream():
        async def gen():
            for i in range(5):
                yield f"chunk-{i};".encode()

        # text/event-stream-shaped: no Content-Length, body emitted in parts.
        return StreamingResponse(gen(), media_type="text/event-stream")

    # Added first => executes last (innermost), mirroring wiring order.
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
    # Added last => executes first (outermost): CORS preflight handling.
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
    """A StreamingResponse must arrive chunk-by-chunk (not buffered/replayed)
    AND still carry the security headers injected on the start message.

    httpx's ``aiter_bytes`` yields the body as the ASGI app sends it; we assert
    every emitted chunk is present and in order, and that the response is not
    served with a Content-Length (which a buffering middleware would add by
    materializing the whole body)."""
    app = _build_stacked_app()
    transport = ASGITransport(app=app)
    async with HTTPXAsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream("GET", "/api/setup/stream") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            # Security headers ride on the start message of a streaming response.
            assert response.headers["X-Frame-Options"] == "DENY"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert "Content-Security-Policy" in response.headers
            # Rate-limit headers injected on the allow path.
            assert response.headers["X-RateLimit-Limit"] == "300"
            # Streaming = no Content-Length; a buffering middleware would add one.
            assert "content-length" not in response.headers

            chunks = [chunk async for chunk in response.aiter_bytes()]

    body = b"".join(chunks)
    assert body == b"chunk-0;chunk-1;chunk-2;chunk-3;chunk-4;"


@pytest.mark.asyncio
async def test_cors_preflight_answered_through_full_stack():
    """An OPTIONS preflight is answered by the outermost CORS layer with the
    allow-origin echoed — proving the converted inner layers don't swallow the
    preflight and CORS still executes first."""
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
    """A plain JSON response through the full stack carries the union of the
    send-wrapping layers' headers: security headers (security.py), rate-limit
    headers (rate_limiter.py), and a CSRF Set-Cookie (csrf.py on GET) — proving
    the wrapped ``send`` callables chain without clobbering each other."""
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
