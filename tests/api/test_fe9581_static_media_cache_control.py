# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""FE-9581: unhashed static media at the SPA root must be cacheable.

Edition Scope: Both.

Content-hashed bundles under ``/assets/*`` already carry a long-lived policy.
The files served from the SPA ROOT did not: ``giljo_logo.png``, ``Giljo_YW.svg``,
the ``icons/`` set and the agent marks all shipped with only etag +
last-modified and NO cache-control, so every browser revalidated them on every
navigation, generating avoidable request volume for users and CI alike.

The policy is set in ``api/middleware/security.py``, not by ``StaticFiles``, so
that is where these assertions live.

Two deliberate design choices, both load-bearing and both tested here:

* The policy keys on the RESPONSE content-type, never on the path. A request
  for a missing icon does not 404 — it falls through to ``index.html`` at 200
  (see ``test_long_lived_policy_is_scoped_to_the_assets_prefix`` in
  ``test_security_headers.py``). A path-keyed rule would stamp a cache policy
  for an image onto an HTML body. Same discipline as the SEC-9454 fix: the
  policy describes the body being sent.
* It is a moderate max-age, NOT ``immutable``. These filenames carry no content
  hash, so a rebuilt logo must be able to win within a day; ``immutable`` would
  pin a stale brand image for a year with no way to revoke it.
"""

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
    """Minimal app with only SecurityHeadersMiddleware — header behavior is middleware-only."""
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
        """The real SPA fallback: a missing icon serves index.html at 200."""
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
    """The defect: a root brand image shipped with no cache policy at all."""
    response = TestClient(app).get("/giljo_logo.png")

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == STATIC_MEDIA_CACHE_CONTROL


def test_root_brand_svg_is_cacheable(app):
    """Same for the SVG marks under /icons/ — the largest group by request count."""
    response = TestClient(app).get("/icons/Giljo_YW_Face.svg")

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == STATIC_MEDIA_CACHE_CONTROL


def test_static_media_is_not_immutable(app):
    """These filenames carry no content hash, so the policy must stay revocable.

    A rebuilt logo under the same filename has to be able to win. ``immutable``
    tells the browser not even to revalidate, which would pin a stale brand
    image for the life of the max-age with no way to recall it.
    """
    cache_control = TestClient(app).get("/giljo_logo.png").headers.get("Cache-Control", "")

    assert "immutable" not in cache_control
    assert "max-age=31536000" not in cache_control


def test_missing_icon_falling_through_to_html_keeps_the_html_policy(app):
    """The reason this keys on content-type and never on path.

    A missing icon does not 404 — the SPA fallback returns index.html at 200 on
    an image-looking URL. If the media policy keyed on the path it would tell
    browsers to cache that HTML body at an icon URL, which is how a stale shell
    gets served in place of an asset.
    """
    response = TestClient(app).get("/icons/does-not-exist.png")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-cache, no-store, must-revalidate"


def test_api_served_image_is_never_publicly_cached(app):
    """Anything under /api may be tenant-scoped; ``public`` there is a privacy defect.

    No such endpoint exists today, but the middleware runs on every response and
    the next person to add an avatar or export endpoint must not inherit a
    shared-cache policy by accident.
    """
    cache_control = TestClient(app).get("/api/tenant-avatar.png").headers.get("Cache-Control", "")

    assert "public" not in cache_control


def test_endpoint_supplied_cache_control_still_wins(app):
    """An explicit policy from the route is never overwritten."""
    response = TestClient(app).get("/api/explicit-no-store.png")

    assert response.headers["Cache-Control"] == "no-store"


def test_error_on_an_image_path_is_not_cached(app):
    """The policy describes a body we actually sent (SEC-9454 discipline)."""
    response = TestClient(app).get("/broken-image.png")

    assert response.status_code == 404
    assert "public" not in response.headers.get("Cache-Control", "")


def test_hashed_assets_keep_the_long_lived_policy(app):
    """Instrument check — must pass on BOTH sides of the FE-9581 change."""
    response = TestClient(app).get("/assets/main-DxIqQVpb.js")

    assert response.headers["Cache-Control"] == LONG_LIVED


def test_html_policy_unchanged(app):
    """Instrument check — index.html must stay revalidated (stale-shell guard)."""
    response = TestClient(app).get("/some-spa-route")

    assert response.headers["Cache-Control"] == "no-cache, no-store, must-revalidate"


def test_json_responses_are_untouched(app):
    """The change must not start stamping a cache policy on API JSON."""
    application = FastAPI()
    application.add_middleware(SecurityHeadersMiddleware)

    @application.get("/api/thing")
    async def thing():
        return JSONResponse({"ok": True})

    response = TestClient(application).get("/api/thing")

    assert "Cache-Control" not in response.headers
