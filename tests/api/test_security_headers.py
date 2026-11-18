# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import re
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.testclient import TestClient

from api.middleware.security import (
    SecurityHeadersMiddleware,
    clear_registered_csp_sources_for_tests,
)


LONG_LIVED = "public, max-age=31536000, immutable"


@pytest.fixture
def app():
    clear_registered_csp_sources_for_tests()
    application = FastAPI()
    application.add_middleware(SecurityHeadersMiddleware)

    @application.get("/")
    async def root():
        return {"ok": True}

    yield application
    clear_registered_csp_sources_for_tests()


def test_static_security_headers_present(app):
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
    response = TestClient(app, base_url="http://testserver").get("/")

    assert "Strict-Transport-Security" not in response.headers


def test_hsts_present_on_https(app):
    response = TestClient(app, base_url="https://testserver").get("/")

    hsts = response.headers["Strict-Transport-Security"]
    assert "max-age=31536000" in hsts
    assert "includeSubDomains" in hsts
    assert "preload" in hsts


def test_csp_core_directives(app):
    response = TestClient(app).get("/")

    csp = response.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "base-uri 'self'" in csp
    assert "form-action 'self'" in csp


def test_csp_img_src_allows_only_first_party_images(app):
    csp = TestClient(app).get("/").headers["Content-Security-Policy"]

    assert "img-src 'self' data:;" in csp
    assert "https:;" not in csp.split("img-src", 1)[1].split(";", 1)[0] + ";"




@pytest.fixture
def asset_app():
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
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    @application.get("/icons/{rest:path}")
    async def icon_miss(rest: str):
        return HTMLResponse("<!doctype html><html></html>")

    yield application
    clear_registered_csp_sources_for_tests()


def test_asset_404_is_not_long_cached(asset_app):
    response = TestClient(asset_app).get("/assets/main-DEADBEEF.js")

    assert response.status_code == 404
    cache_control = response.headers.get("Cache-Control", "")
    assert "immutable" not in cache_control
    assert "max-age=31536000" not in cache_control
    assert cache_control == "no-store"


def test_asset_404_from_an_exception_handler_is_not_long_cached(asset_app):
    response = TestClient(asset_app).get("/assets/raises.js")

    assert response.status_code == 404
    assert response.headers["Cache-Control"] == "no-store"


def test_asset_200_still_long_cached(asset_app):
    response = TestClient(asset_app).get("/assets/present.js")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == LONG_LIVED


def test_asset_304_keeps_long_lived_policy(asset_app):
    response = TestClient(asset_app).get("/assets/revalidated.js")

    assert response.status_code == 304
    assert response.headers["Cache-Control"] == LONG_LIVED


def test_asset_5xx_is_not_long_cached(asset_app):
    response = TestClient(asset_app).get("/assets/boom.js")

    assert response.status_code == 500
    assert response.headers["Cache-Control"] == "no-store"


def test_long_lived_policy_is_scoped_to_the_assets_prefix(asset_app):
    response = TestClient(asset_app).get("/icons/does-not-exist.png")

    assert response.status_code == 200
    assert "immutable" not in response.headers.get("Cache-Control", "")


def test_non_asset_html_policy_unchanged(app):

    @app.get("/some-spa-route")
    async def spa_route():
        return HTMLResponse("<!doctype html><html></html>")

    response = TestClient(app).get("/some-spa-route")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-cache, no-store, must-revalidate"



_ONBOARDING_MEDIA_DIRECTIVE = "media-src 'self' https://giljo.ai"

_POLICY_BEFORE_INF_0072B = (
    "default-src 'self'; "
    "script-src 'self' 'sha256-LRJOHmw/kARrWFQNFXTam7BNVjtucN2V1FzuxKtEUg0=' "
    "'sha256-T+y4FnL+BP2aiGWNs6H5HdyLosVMnGaNc9v+5DaNNJM=' https://static.cloudflareinsights.com; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self' data:; "
    "connect-src 'self' ws: wss: https://cloudflareinsights.com; "
    "frame-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


def test_csp_allows_media_only_from_self_and_the_website(app):
    csp = TestClient(app).get("/").headers["Content-Security-Policy"]

    directives = [d.strip() for d in csp.split(";")]
    assert _ONBOARDING_MEDIA_DIRECTIVE in directives
    assert sum(d.startswith("media-src") for d in directives) == 1


def test_csp_other_directives_unchanged_by_media_src(app):
    csp = TestClient(app).get("/").headers["Content-Security-Policy"]

    without_media = "; ".join(d.strip() for d in csp.split(";") if not d.strip().startswith("media-src"))
    assert without_media == _POLICY_BEFORE_INF_0072B
    assert "img-src 'self' data:;" in csp
    assert "connect-src 'self' ws: wss: https://cloudflareinsights.com;" in csp


def test_media_policy_host_equals_the_registry_host(app):
    registry = (Path(__file__).resolve().parents[2] / "frontend/src/content/onboarding/videos.js").read_text()
    registry_host = re.search(r"export const MEDIA_HOST = '([^']+)'", registry).group(1)
    csp = TestClient(app).get("/").headers["Content-Security-Policy"]

    assert f"media-src 'self' {registry_host}" in [d.strip() for d in csp.split(";")]
