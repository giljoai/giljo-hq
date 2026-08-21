# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Regression tests for SecurityHeadersMiddleware.

These headers are emitted on every response by api/middleware/security.py but
were previously untested. A regression (dropping X-Frame-Options, breaking the
HTTPS-only HSTS guard, or weakening the CSP framing rules) would have shipped
silently. This locks the static headers, the HSTS scheme-gating, and the core
CSP directives in at the middleware layer.

Edition Scope: CE. The middleware itself is CE; SaaS only *adds* extra CSP
sources via register_csp_sources(), which we reset here so the assertions hold
regardless of test execution order.
"""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.testclient import TestClient

from api.middleware.security import (
    SecurityHeadersMiddleware,
    clear_registered_csp_sources_for_tests,
)


# The exact policy the middleware attaches to a content-hashed build asset.
LONG_LIVED = "public, max-age=31536000, immutable"


@pytest.fixture
def app():
    """Minimal FastAPI app with only SecurityHeadersMiddleware mounted.

    Isolated from the full app/DB on purpose — header behavior is middleware-only.
    """
    clear_registered_csp_sources_for_tests()
    application = FastAPI()
    application.add_middleware(SecurityHeadersMiddleware)

    @application.get("/")
    async def root():
        return {"ok": True}

    yield application
    clear_registered_csp_sources_for_tests()


def test_static_security_headers_present(app):
    """The five static OWASP headers are emitted with their exact values."""
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-XSS-Protection"] == "1; mode=block"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    permissions_policy = response.headers["Permissions-Policy"]
    assert "geolocation=()" in permissions_policy
    assert "microphone=()" in permissions_policy
    assert "camera=()" in permissions_policy
    assert "payment=()" in permissions_policy


def test_hsts_absent_on_http(app):
    """HSTS is meaningless over HTTP and must NOT be sent for http requests."""
    response = TestClient(app, base_url="http://testserver").get("/")

    assert "Strict-Transport-Security" not in response.headers


def test_hsts_present_on_https(app):
    """HSTS is sent on HTTPS requests with the hardened directive set."""
    response = TestClient(app, base_url="https://testserver").get("/")

    hsts = response.headers["Strict-Transport-Security"]
    assert "max-age=31536000" in hsts
    assert "includeSubDomains" in hsts
    assert "preload" in hsts


def test_csp_core_directives(app):
    """Core CSP anti-XSS / anti-clickjacking directives are present."""
    response = TestClient(app).get("/")

    csp = response.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "base-uri 'self'" in csp
    assert "form-action 'self'" in csp


# ─── SEC-9454: the cache policy must follow the RESPONSE, not just the path ───
#
# The middleware chose the asset cache policy from request.url.path alone, so a
# 404 for a not-yet-deployed hashed chunk was served
# `public, max-age=31536000, immutable`. An upstream CDN/proxy cached that miss
# for a year; a brief deploy window turned into an extended outage, and it would
# recur on every deploy that changed an asset hash. The file existed the whole
# time -- the edge was serving a year-long cached miss.


@pytest.fixture
def asset_app():
    """App exercising every status the /assets/ path can actually produce.

    The 404 body mirrors api/app.py's spa_fallback non-SPA branch verbatim
    (`{"detail": "Not Found"}`) -- that is the exact response measured in
    production, so this reproduces the real artifact rather than a stand-in.
    """
    clear_registered_csp_sources_for_tests()
    application = FastAPI()
    application.add_middleware(SecurityHeadersMiddleware)

    @application.get("/assets/present.js")
    async def asset_hit():
        return Response(content="console.log(1)", media_type="application/javascript")

    @application.get("/assets/revalidated.js")
    async def asset_not_modified():
        return Response(status_code=304)

    @application.get("/assets/boom.js")
    async def asset_server_error():
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

    @application.get("/assets/raises.js")
    async def asset_raises():
        raise HTTPException(status_code=404, detail="Not Found")

    @application.get("/assets/{rest:path}")
    async def asset_miss(rest: str):
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    @application.exception_handler(404)
    async def spa_fallback(request, exc):
        # Mirrors api/app.py's _install_spa_fallback: an asset path gets a real
        # JSON 404 rather than the SPA shell (FE-6120).
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    @application.get("/icons/{rest:path}")
    async def icon_miss(rest: str):
        # A missing icon falls through the SPA fallback to index.html at 200.
        return HTMLResponse("<!doctype html><html></html>")

    yield application
    clear_registered_csp_sources_for_tests()


def test_asset_404_is_not_long_cached(asset_app):
    """SEC-9454 (the defect): a MISS on the asset path must never be cacheable.

    A 404 declared immutable for a year pins that URL as broken at every edge
    that saw it, and nothing short of a manual purge clears it.
    """
    response = TestClient(asset_app).get("/assets/main-DEADBEEF.js")

    assert response.status_code == 404
    cache_control = response.headers.get("Cache-Control", "")
    assert "immutable" not in cache_control
    assert "max-age=31536000" not in cache_control
    assert cache_control == "no-store"


def test_asset_404_from_an_exception_handler_is_not_long_cached(asset_app):
    """The production 404 is RAISED, not returned -- cover that path too.

    In production nothing returns the asset 404 from a route: Starlette's
    StaticFiles mount raises HTTPException(404) and api/app.py's registered
    404 handler renders it. That is a different code path from the test above,
    and a fix that only covered returned responses would leave the real one
    broken. The middleware is pure-ASGI and wraps `send`, so it must stamp
    every response including this one -- asserted rather than assumed.
    """
    response = TestClient(asset_app).get("/assets/raises.js")

    assert response.status_code == 404
    assert response.headers["Cache-Control"] == "no-store"


def test_asset_200_still_long_cached(asset_app):
    """Both-sides guard: the fix must NOT weaken caching for a real asset.

    Content-hashed filenames change when their content does, so a hit is
    correctly immutable for a year. Fixing the miss by dropping this would
    quietly destroy asset caching for every user -- a worse regression than
    the bug.
    """
    response = TestClient(asset_app).get("/assets/present.js")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == LONG_LIVED


def test_asset_304_keeps_long_lived_policy(asset_app):
    """A 304 is a cache HIT and must keep the long-lived policy (RFC 7232).

    This is why the rule is not a bare `status < 400`: stamping `no-store` on a
    revalidation tells the browser to discard the copy it just confirmed fresh,
    which is the same "weaken the hit" regression as the test above wearing a
    different status code.
    """
    response = TestClient(asset_app).get("/assets/revalidated.js")

    assert response.status_code == 304
    assert response.headers["Cache-Control"] == LONG_LIVED


def test_asset_5xx_is_not_long_cached(asset_app):
    """Not just 404: no error on the asset path may be cached for a year."""
    response = TestClient(asset_app).get("/assets/boom.js")

    assert response.status_code == 500
    assert response.headers["Cache-Control"] == "no-store"


def test_long_lived_policy_is_scoped_to_the_assets_prefix(asset_app):
    """The immutable policy reaches /assets/ only -- never /icons/ or /mascot/.

    Load-bearing because the SEC-9454 fix keys on STATUS: a missing icon does
    not 404, it falls through to index.html at 200. If the long-lived policy
    ever reached that path, a status-keyed fix could not see the miss and would
    pin the wrong body at an icon URL for a year.
    """
    response = TestClient(asset_app).get("/icons/does-not-exist.png")

    assert response.status_code == 200
    assert "immutable" not in response.headers.get("Cache-Control", "")


def test_non_asset_html_policy_unchanged(app):
    """Instrument check -- must pass on BOTH sides of the SEC-9454 change.

    index.html must stay revalidated so a browser cannot hold a stale shell
    pointing at rebuilt bundle hashes. If this goes red, suspect the harness
    before the fix: it asserts behavior the change does not touch.
    """

    @app.get("/some-spa-route")
    async def spa_route():
        return HTMLResponse("<!doctype html><html></html>")

    response = TestClient(app).get("/some-spa-route")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-cache, no-store, must-revalidate"
