# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.testclient import TestClient

from api.middleware.security import (
    STATIC_MEDIA_CACHE_CONTROL,
    SecurityHeadersMiddleware,
    clear_registered_csp_sources_for_tests,
)


LONG_LIVED = "public, max-age=31536000, immutable"


@pytest.fixture
def app():
    clear_registered_csp_sources_for_tests()
    application = FastAPI()
    application.add_middleware(SecurityHeadersMiddleware)

    @application.get("/giljo_logo.png")
    async def brand_png():
        return Response(content=b"\x89PNG", media_type="image/png")

    @application.get("/icons/Giljo_YW_Face.svg")
    async def brand_svg():
        return Response(content=b"<svg/>", media_type="image/svg+xml")

    @application.get("/assets/main-DxIqQVpb.js")
    async def hashed_asset():
        return Response(content=b"console.log(1)", media_type="application/javascript")

    @application.get("/some-spa-route")
    async def spa_route():
        return HTMLResponse("<!doctype html><html></html>")

    @application.get("/icons/does-not-exist.png")
    async def missing_icon_falls_through():
        return HTMLResponse("<!doctype html><html></html>")

    @application.get("/api/tenant-avatar.png")
    async def private_api_image():
        return Response(content=b"\x89PNG", media_type="image/png")

    @application.get("/api/explicit-no-store.png")
    async def explicit_policy():
        return Response(
            content=b"\x89PNG",
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    @application.get("/broken-image.png")
    async def broken_image():
        raise HTTPException(status_code=404, detail="gone")

    yield application
    clear_registered_csp_sources_for_tests()


def test_root_brand_png_is_cacheable(app):
    response = TestClient(app).get("/giljo_logo.png")

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == STATIC_MEDIA_CACHE_CONTROL


def test_root_brand_svg_is_cacheable(app):
    response = TestClient(app).get("/icons/Giljo_YW_Face.svg")

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == STATIC_MEDIA_CACHE_CONTROL


def test_static_media_is_not_immutable(app):
    cache_control = TestClient(app).get("/giljo_logo.png").headers.get("Cache-Control", "")

    assert "immutable" not in cache_control
    assert "max-age=31536000" not in cache_control


def test_missing_icon_falling_through_to_html_keeps_the_html_policy(app):
    response = TestClient(app).get("/icons/does-not-exist.png")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-cache, no-store, must-revalidate"


def test_api_served_image_is_never_publicly_cached(app):
    cache_control = TestClient(app).get("/api/tenant-avatar.png").headers.get("Cache-Control", "")

    assert "public" not in cache_control


def test_endpoint_supplied_cache_control_still_wins(app):
    response = TestClient(app).get("/api/explicit-no-store.png")

    assert response.headers["Cache-Control"] == "no-store"


def test_error_on_an_image_path_is_not_cached(app):
    response = TestClient(app).get("/broken-image.png")

    assert response.status_code == 404
    assert "public" not in response.headers.get("Cache-Control", "")


def test_hashed_assets_keep_the_long_lived_policy(app):
    response = TestClient(app).get("/assets/main-DxIqQVpb.js")

    assert response.headers["Cache-Control"] == LONG_LIVED


def test_html_policy_unchanged(app):
    response = TestClient(app).get("/some-spa-route")

    assert response.headers["Cache-Control"] == "no-cache, no-store, must-revalidate"


def test_json_responses_are_untouched(app):
    application = FastAPI()
    application.add_middleware(SecurityHeadersMiddleware)

    @application.get("/api/thing")
    async def thing():
        return JSONResponse({"ok": True})

    response = TestClient(application).get("/api/thing")

    assert "Cache-Control" not in response.headers
